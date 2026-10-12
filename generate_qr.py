from pathlib import Path
import sqlite3
import qrcode

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "canteen.db"
QR_DIR = BASE_DIR / "static" / "qrcodes"

BASE_URL = "https://axis-sometimes-sense-inclusion.trycloudflare.com"

def generate_qr_codes():
    QR_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    tables = conn.execute(
        """
        SELECT id, table_code, table_name
        FROM canteen_tables
        WHERE is_active = 1
        ORDER BY id
        """
    ).fetchall()

    for table in tables:
        table_code = table["table_code"]
        url = f"{BASE_URL}/table/{table_code}"
        file_path = QR_DIR / f"{table_code}.png"

        img = qrcode.make(url)
        img.save(file_path)

        conn.execute(
            """
            UPDATE canteen_tables
            SET qr_path = ?
            WHERE id = ?
            """,
            (
                f"/static/qrcodes/{table_code}.png",
                table["id"]
            )
        )

        print(f"Generated QR: {table_code} -> {url}")

    conn.commit()
    conn.close()

    print("\nAll QR codes generated successfully.")

if __name__ == "__main__":
    generate_qr_codes()
