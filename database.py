import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "canteen.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()

    with open(SCHEMA_PATH, "r", encoding="utf-8") as file:
        schema = file.read()

    conn.executescript(schema)
    seed_data(conn)
    conn.commit()
    conn.close()

    print("Database initialized successfully.")
    print(f"Database location: {DB_PATH}")

def seed_data(conn):
    conn.execute(
        """
        INSERT OR IGNORE INTO admins (username, password)
        VALUES (?, ?)
        """,
        ("admin", "admin123")
    )

    categories = [
        ("Snacks", "Quick snacks and light food"),
        ("Main Course", "Main meals"),
        ("Beverages", "Cold and hot beverages"),
        ("Desserts", "Sweet dishes")
    ]

    for name, description in categories:
        conn.execute(
            """
            INSERT OR IGNORE INTO categories (name, description)
            VALUES (?, ?)
            """,
            (name, description)
        )

    category_rows = conn.execute(
        "SELECT id, name FROM categories"
    ).fetchall()

    category_map = {
        row["name"]: row["id"]
        for row in category_rows
    }

    menu_items = [
        (
            category_map["Snacks"],
            "Samosa",
            "Crispy potato-filled samosa",
            20,
            50
        ),
        (
            category_map["Snacks"],
            "Veg Sandwich",
            "Fresh vegetable sandwich",
            60,
            30
        ),
        (
            category_map["Main Course"],
            "Veg Noodles",
            "Vegetable noodles",
            90,
            25
        ),
        (
            category_map["Main Course"],
            "Chole Bhature",
            "Chole served with bhature",
            100,
            20
        ),
        (
            category_map["Beverages"],
            "Cold Coffee",
            "Chilled creamy cold coffee",
            70,
            30
        ),
        (
            category_map["Beverages"],
            "Masala Tea",
            "Indian masala tea",
            25,
            50
        ),
        (
            category_map["Desserts"],
            "Gulab Jamun",
            "Two pieces of gulab jamun",
            40,
            30
        )
    ]

    for item in menu_items:
        conn.execute(
            """
            INSERT INTO menu_items
            (category_id, name, description, price, stock)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1
                FROM menu_items
                WHERE name = ?
            )
            """,
            (*item, item[1])
        )

    for number in range(1, 9):
        code = f"T{number}"
        name = f"Table {number}"

        conn.execute(
            """
            INSERT OR IGNORE INTO canteen_tables
            (table_code, table_name)
            VALUES (?, ?)
            """,
            (code, name)
        )

    print("Seed data inserted/verified.")

if __name__ == "__main__":
    init_db()
