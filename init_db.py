import sqlite3
from pathlib import Path

DB_PATH = "redirects.db"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()
        print(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
