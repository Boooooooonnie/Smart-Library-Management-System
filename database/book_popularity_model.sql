USE library_system2;
GO

IF OBJECT_ID('dbo.BookFeatures') IS NOT NULL DROP TABLE dbo.BookFeatures;
GO
CREATE TABLE dbo.BookFeatures (
    book_id VARCHAR(10) PRIMARY KEY,
    borrow_count INT,
    reservation_count INT,
    avg_borrow_interval_days FLOAT,
    publish_year INT,
    category_id INT,
    label_bit BIT  -- 1 = high-borrow (hot), 0 = low-borrow
);
GO

INSERT INTO dbo.BookFeatures (book_id, borrow_count, reservation_count, avg_borrow_interval_days, publish_year, category_id)
SELECT 
    b.book_id,
    ISNULL(bc.borrow_count,0) AS borrow_count,
    ISNULL(rc.reservation_count,0) AS reservation_count,
    ISNULL(bi.avg_interval, 3650) AS avg_borrow_interval_days,
    b.publish_year,
    b.category_id
FROM Books b
LEFT JOIN (
    SELECT book_id, COUNT(*) AS borrow_count
    FROM BorrowItems
    GROUP BY book_id
) AS bc ON b.book_id = bc.book_id
LEFT JOIN (
    SELECT book_id, COUNT(*) AS reservation_count
    FROM ReservationItems
    GROUP BY book_id
) AS rc ON b.book_id = rc.book_id
LEFT JOIN (
    -- 計算每本書的平均借閱間隔
    SELECT t.book_id,
           AVG(DATEDIFF(DAY, t.prev_date, t.borrow_date)) AS avg_interval
    FROM (
        SELECT bi.book_id,
               br.borrow_date,
               LAG(br.borrow_date) OVER (PARTITION BY bi.book_id ORDER BY br.borrow_date) AS prev_date
        FROM BorrowItems bi
        JOIN Borrows br ON bi.borrow_id = br.borrow_id
    ) AS t
    WHERE t.prev_date IS NOT NULL
    GROUP BY t.book_id
) AS bi ON b.book_id = bi.book_id;
GO

-- 3) 計算中位數並標記 label_bit (hot if borrow_count >= median)
DECLARE @median INT;
SELECT @median = MAX(borrow_count) FROM (
    SELECT borrow_count, ROW_NUMBER() OVER (ORDER BY borrow_count) rn, COUNT(*) OVER() total_count
    FROM (SELECT ISNULL(bc.borrow_count,0) borrow_count FROM Books b LEFT JOIN (SELECT book_id, COUNT(*) borrow_count FROM BorrowItems GROUP BY book_id) bc ON b.book_id=bc.book_id) x
) y WHERE rn = CEILING((total_count+1)/2.0);
IF @median IS NULL SET @median = 1;
UPDATE dbo.BookFeatures SET label_bit = CASE WHEN borrow_count >= @median THEN 1 ELSE 0 END;
GO

-- 4) 建立 BookPredictions 與 ModelMetrics
IF OBJECT_ID('dbo.BookPredictions') IS NOT NULL DROP TABLE dbo.BookPredictions;
GO
CREATE TABLE dbo.BookPredictions (
    book_id VARCHAR(10) PRIMARY KEY,
    predicted_prob FLOAT,
    predicted_label BIT,
    model_date DATETIME DEFAULT GETDATE()
);
GO

IF OBJECT_ID('dbo.ModelMetrics') IS NOT NULL DROP TABLE dbo.ModelMetrics;
GO
CREATE TABLE dbo.ModelMetrics (
    model_date DATETIME DEFAULT GETDATE(),
    accuracy FLOAT,
    precision FLOAT,
    recall FLOAT,
    f1 FLOAT
);
GO

-- 5) 使用 sp_execute_external_script 執行 Python 訓練 LogisticRegression
-- 請先確認 SQL Server 支援 Python (Machine Learning Services) 並安裝 pandas, scikit-learn, numpy
-- 下面執行會回傳測試集的預測結果與 model metrics

-- 重新計算 label_bit，確保有 0 和 1
WITH OrderedBooks AS (
    SELECT 
        book_id, 
        borrow_count,
        NTILE(2) OVER (ORDER BY borrow_count) AS percentile_group
    FROM dbo.BookFeatures
)
UPDATE b
SET label_bit = CASE WHEN o.percentile_group = 2 THEN 1 ELSE 0 END
FROM dbo.BookFeatures b
JOIN OrderedBooks o ON b.book_id = o.book_id;

SELECT label_bit, COUNT(*) 
FROM dbo.BookFeatures
GROUP BY label_bit;

EXEC sp_execute_external_script
    @language = N'Python',
    @script = N'
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

df = InputDataSet.copy()

# 填補缺值
df["avg_borrow_interval_days"] = df["avg_borrow_interval_days"].fillna(3650)
df["publish_year"] = df["publish_year"].fillna(df["publish_year"].median())
df["category_id"] = df["category_id"].fillna(-1)

features = ["borrow_count","reservation_count","avg_borrow_interval_days","publish_year","category_id"]
X = df[features].astype(float)
y = df["label_bit"].astype(int)

# 若資料量太少則跳出
if len(df) < 10:
    OutputDataSet = pd.DataFrame([], columns=["book_id","predicted_prob","predicted_label","accuracy","precision","recall","f1"])
else:
    # 切分
    stratify_param = y if len(y.unique())>1 else None
    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, df["book_id"], test_size=0.3, random_state=42, stratify=stratify_param
    )
    model = LogisticRegression(max_iter=500)
    model.fit(X_train, y_train)
    prob = model.predict_proba(X_test)[:,1]
    pred = (prob >= 0.5).astype(int)
    acc = float(accuracy_score(y_test, pred))
    try:
        prec = float(precision_score(y_test, pred))
    except ZeroDivisionError:
        prec = 0.0
    try:
        rec = float(recall_score(y_test, pred))
    except ZeroDivisionError:
        rec = 0.0
    try:
        f1 = float(f1_score(y_test, pred))
    except ZeroDivisionError:
        f1 = 0.0
    out = pd.DataFrame({
        "book_id": idx_test.values,
        "predicted_prob": prob,
        "predicted_label": pred,
        "accuracy":[acc]*len(prob),
        "precision":[prec]*len(prob),
        "recall":[rec]*len(prob),
        "f1":[f1]*len(prob)
    })
    OutputDataSet = out
',
    @input_data_1 = N'SELECT book_id, borrow_count, reservation_count, avg_borrow_interval_days, publish_year, category_id, label_bit FROM dbo.BookFeatures',
    @output_data_1_name = N'OutputDataSet'
WITH RESULT SETS ((book_id VARCHAR(10), predicted_prob FLOAT, predicted_label INT, accuracy FLOAT, precision FLOAT, recall FLOAT, f1 FLOAT));
GO

-- 6) 建議：把上一步 Python 的結果寫回 BookPredictions 與 ModelMetrics
-- 在 SSMS 中可以使用 INSERT ... EXEC 方式（或先將 Python 輸出暫存到暫存表中）
-- 範例（示意）：
/*
IF OBJECT_ID('tempdb..#ml_out') IS NOT NULL DROP TABLE #ml_out;
CREATE TABLE #ml_out (book_id VARCHAR(10), predicted_prob FLOAT, predicted_label INT, accuracy FLOAT, precision FLOAT, recall FLOAT, f1 FLOAT);
INSERT INTO #ml_out EXEC sp_execute_external_script
    @language = N''Python'',
    @script = N''...'',  -- 同上完整 python 內容
    @input_data_1 = N''SELECT ... FROM dbo.BookFeatures'',
    @output_data_1_name = N''OutputDataSet''
;
-- 然後：
INSERT INTO dbo.BookPredictions (book_id, predicted_prob, predicted_label)
SELECT book_id, predicted_prob, predicted_label FROM #ml_out;

INSERT INTO dbo.ModelMetrics (accuracy, precision, recall, f1)
SELECT TOP 1 accuracy, precision, recall, f1 FROM #ml_out;
*/

PRINT '請在支援 Python 的 SQL Server 上執行 sp_execute_external_script 並依環境選擇合適的方式將結果寫回資料表。';
GO
