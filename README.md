# Smart Library Management System

A web-based library management system developed with **Flask** and **SQL Server**, integrating book management, borrowing and reservation functions, user records, and basic book recommendation features.

The project combines database design, web development, and a machine learning experiment for book popularity prediction.

## Features

- User login and session management
- Book browsing and category filtering
- Book borrowing and returning
- Book reservation
- Personal borrowing history
- Overdue-day calculation
- Popular book ranking
- Personalized book recommendations
- Automatic book status updates
- Book popularity prediction using Logistic Regression

## System Overview

The web application is built with Flask and connects to a Microsoft SQL Server database through `pyodbc`.

```text
User
  │
  ▼
Flask Web Application
  │
  ├── Login / Session
  ├── Book Search
  ├── Borrow / Return
  ├── Reservation
  └── Recommendation
  │
  ▼
SQL Server
  │
  ├── Users
  ├── Books
  ├── Borrows / BorrowItems
  ├── Reservations / ReservationItems
  └── BookFeatures
```

## Database Design

The database contains relational tables for managing users, books, borrowing records, reservations, book categories, and book statuses.

Database-side logic is also implemented using:

- Stored procedures for borrowing and returning books
- User-defined functions for overdue-day calculation and borrowing statistics
- Triggers for automatic book status updates
- Transactions for maintaining data consistency

## Recommendation System

The system includes two types of recommendation-related functions.

### Personalized Recommendations

The web application analyzes the categories a user has borrowed most frequently and recommends books from the user's preferred category that have not been borrowed before.

### Book Popularity Prediction

A separate machine learning experiment uses **Logistic Regression** to predict whether a book belongs to the high-borrowing group.

Features include:

- Borrow count
- Reservation count
- Average interval between borrowings
- Publication year
- Book category

The model evaluation includes accuracy, precision, recall, and F1-score.

## Technologies

- Python
- Flask
- Microsoft SQL Server
- T-SQL
- pyodbc
- HTML
- Bootstrap
- pandas
- scikit-learn

## Main Functions

### Book Management

Users can browse the library collection and filter books by category. The interface displays the current availability of each book.

### Borrowing and Returning

Available books can be borrowed directly through the system. Borrowing records and due dates are stored in the database, while returning a book updates both the borrowing record and book status.

### Reservation

Books that are currently unavailable can be reserved. Reservation information is stored separately from borrowing records.

### Personal Records

Users can view their current and historical borrowing records, including:

- Borrow date
- Due date
- Return status
- Overdue days
- Current reservations

## Project Report

The included project report documents the database structure, data processing workflow, system functions, interface, and development results.

## Notes

This project was developed as a course project to practice integrating database design with web application development.

It also explores the use of historical borrowing data for basic recommendation and book popularity prediction.