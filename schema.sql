PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    city TEXT
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    price REAL NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date TEXT,
    total REAL
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL
);

INSERT INTO customers VALUES (1,'Asha','asha@example.com','Chennai'),(2,'Ravi','ravi@example.com','Madurai'),(3,'Meena',NULL,'Chennai');
INSERT INTO products VALUES (1,'Keyboard',1200.0),(2,'Mouse',500.0),(3,'Monitor',9000.0);
INSERT INTO orders VALUES (1,1,'2026-01-05',1700.0),(2,1,'2026-02-11',9000.0),(3,2,'2026-02-20',500.0);
INSERT INTO order_items VALUES (1,1,1,1),(2,1,2,1),(3,2,3,1),(4,3,2,1);
