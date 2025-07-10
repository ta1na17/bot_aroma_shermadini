# redirect_service.py

from flask import Flask, request, redirect
import sqlite3, string, random, os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "urls.db")

app = Flask(__name__)
SHORT_CODE_LEN = 6
CHARS = string.ascii_letters + string.digits

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS redirects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT NOT NULL,
        user_id TEXT,
        short_code TEXT NOT NULL UNIQUE,
        original_url TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    """)
    conn.close()

def generate_code(db):
    while True:
        code = "".join(random.choices(CHARS, k=SHORT_CODE_LEN))
        if not db.execute("SELECT 1 FROM redirects WHERE short_code = ?", (code,)).fetchone():
            return code

# Инициализируем БД при старте
init_db()

@app.route('/redirect')
def track_and_short():
    item    = request.args.get('item')
    user_id = request.args.get('user_id')
    original = f"https://www.wildberries.ru/catalog/{item}/detail.aspx"
    timestamp = datetime.utcnow().isoformat()

    db = get_db()
    short_code = generate_code(db)
    db.execute("""
        INSERT INTO redirects (item, user_id, short_code, original_url, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (item, user_id, short_code, original, timestamp))
    db.commit()
    db.close()

    # Сразу редирект на короткий путь — клиент увидит в всплывающем окне короткий URL
    return redirect(f"/{short_code}", code=302)

@app.route('/<code>')
def redirect_short(code):
    db = get_db()
    row = db.execute("SELECT original_url FROM redirects WHERE short_code = ?", (code,)).fetchone()
    db.close()
    if row:
        return redirect(row["original_url"], code=302)
    return "Ссылка не найдена", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
