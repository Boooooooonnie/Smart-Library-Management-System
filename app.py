from flask import Flask, render_template, request, redirect, url_for, session, flash
import pyodbc
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your_very_secret_key'

# --- 資料庫連線 ---
def get_db_connection():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=.;' 
        'DATABASE=library_system3;'
        'Trusted_Connection=yes;'
    )

# ---------------- 登入 ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uid = request.form.get('user_id')
        pwd = request.form.get('password')
        conn = get_db_connection()
        cursor = conn.cursor()
        # 對應 Users 表：user_id, user_password
        cursor.execute("SELECT user_id, user_name FROM Users WHERE user_id=? AND user_password=?", uid, pwd)
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            # U001 設為管理員範例
            session['is_admin'] = (user[0] == 'U001')
            return redirect(url_for('home'))
        else:
            flash("帳號或密碼錯誤", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------- 首頁 (含推薦與熱門排行) ----------------
@app.route('/')
def home():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    uid = session['user_id']
    cat_id = request.args.get('category_id')
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 分類選單
    cursor.execute("SELECT category_id, category_name FROM Categories")
    categories = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]

    # 2. 個性化推薦 (找該用戶借最多次的分類，推他沒借過的)
    rec_query = """
        SELECT TOP 3 b.book_id, b.book_name, b.author
        FROM Books b
        WHERE b.category_id = (
            SELECT TOP 1 b2.category_id
            FROM Borrows br
            JOIN BorrowItems bi ON br.borrow_id = bi.borrow_id
            JOIN Books b2 ON bi.book_id = b2.book_id
            WHERE br.user_id = ?
            GROUP BY b2.category_id
            ORDER BY COUNT(*) DESC
        ) AND b.book_id NOT IN (
            SELECT bi2.book_id FROM BorrowItems bi2 
            JOIN Borrows br2 ON bi2.borrow_id = br2.borrow_id WHERE br2.user_id = ?
        )
    """
    recommendations = []
    try:
        cursor.execute(rec_query, uid, uid)
        recommendations = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]
    except: pass 

    # 3. 熱門排行 (從 BorrowItems 統計)
    cursor.execute("""
        SELECT TOP 5 b.book_name, COUNT(bi.book_id) as count
        FROM Books b
        JOIN BorrowItems bi ON b.book_id = bi.book_id
        GROUP BY b.book_name ORDER BY count DESC
    """)
    hot_ranking = cursor.fetchall()

    # 4. 書籍列表 (修正點：對應正確的表名與欄位)
    query = """
        SELECT b.book_id, b.book_name, b.author, b.publish_year,
               s.book_status_name, c.category_name
        FROM Books b
        LEFT JOIN BookStatuses s ON b.book_status_id = s.book_status_id
        LEFT JOIN Categories c ON b.category_id = c.category_id
    """
    params = []
    if cat_id and cat_id != 'all':
        query += " WHERE b.category_id = ?"
        params.append(cat_id)
    
    cursor.execute(query, params)
    books = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()
    return render_template('home.html', books=books, categories=categories, 
                           recommendations=recommendations, hot_ranking=hot_ranking, selected_cat=cat_id)

# ---------------- 功能：借書 (使用預存程序) ----------------
@app.route('/borrow', methods=['POST'])
def borrow():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    book_id = request.form.get('book_id')
    # 生成唯一 ID (SQL 限制為 VARCHAR(10))
    borrow_id = "BR" + datetime.now().strftime("%H%M%S") 
    now = datetime.now()
    due_date = now + timedelta(days=14)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 呼叫預存程序: @borrow_id, @user_id, @book_id, @borrow_date, @due_date
        # 這裡的 @borrow_date 會存入 Borrows 的 created_at
        cursor.execute("{CALL sp_AddBorrowRecord (?, ?, ?, ?, ?)}", 
                       (borrow_id, session['user_id'], book_id, now, due_date))
        conn.commit()
        flash("借閱成功！", "success")
    except Exception as e:
        flash(f"借閱失敗：{str(e)}", "danger")
    finally:
        conn.close()
    return redirect(url_for('home'))

# ---------------- 功能：個人借閱紀錄 (修正無效欄位) ----------------
@app.route('/mybooks')
def my_books():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 嚴格對應 SQLQuery2.sql 的結構：
    # borrow_date 與 due_date 都在 Borrows (br) 表中
    # return_date 在 BorrowItems (bi) 表中
    cursor.execute("""
        SELECT b.book_id, 
               b.book_name, 
               br.borrow_date, 
               br.due_date, 
               bi.return_date,
               dbo.fn_GetOverdueDays(br.due_date, bi.return_date) AS overdue_days
        FROM Borrows br
        JOIN BorrowItems bi ON br.borrow_id = bi.borrow_id
        JOIN Books b ON bi.book_id = b.book_id
        WHERE br.user_id = ? 
        ORDER BY br.borrow_date DESC
    """, (session['user_id'],))
    
    # 轉換成字典格式供 HTML 讀取
    records = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()
    return render_template('mybooks.html', records=records)

# ---------------- 功能：還書 (使用預存程序) ----------------
@app.route('/return', methods=['POST'])
def return_book():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    book_id = request.form.get('book_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 找出該使用者名下、該書、尚未歸還的借閱單 ID
        cursor.execute("""
            SELECT bi.borrow_id FROM BorrowItems bi
            JOIN Borrows br ON bi.borrow_id = br.borrow_id
            WHERE br.user_id = ? AND bi.book_id = ? AND bi.return_date IS NULL
        """, (session['user_id'], book_id))
        row = cursor.fetchone()
        
        if row:
            borrow_id = row[0]
            # 呼叫預存程序: @borrow_id, @book_id, @return_date
            cursor.execute("{CALL sp_UpdateReturnDate (?, ?, ?)}", 
                           (borrow_id, book_id, datetime.now()))
            conn.commit()
            flash("書籍已歸還", "success")
        else:
            flash("找不到未歸還的借閱紀錄", "warning")
    except Exception as e:
        flash(f"歸還失敗：{str(e)}", "danger")
    finally:
        conn.close()
    return redirect(url_for('my_books'))

# ---------------- 功能：預約 ----------------
@app.route('/reserve', methods=['POST'])
def reserve():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    book_id = request.form.get('book_id')
    res_id = "RS" + datetime.now().strftime("%H%M%S") # 生成預約 ID
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. 插入預約主檔 (reservation_status_id = 1 代表未完成)
        cursor.execute("""
            INSERT INTO Reservations (reservation_id, user_id, reservation_date, reservation_status_id) 
            VALUES (?, ?, ?, 1)
        """, (res_id, session['user_id'], datetime.now()))
        
        # 2. 插入預約明細
        cursor.execute("INSERT INTO ReservationItems (reservation_id, book_id) VALUES (?, ?)", (res_id, book_id))
        
        conn.commit()
        flash("預約成功", "info")
    except Exception as e:
        flash(f"預約失敗: {str(e)}", "danger")
    finally:
        conn.close()
    return redirect(url_for('home'))

if __name__ == '__main__':
    # 確保資料庫中已有 Categories, BookStatuses 等基礎資料
    app.run(debug=True)