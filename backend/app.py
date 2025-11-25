# backend/app.py
import os
import sqlite3
from flask import Flask, request, jsonify, g
from dotenv import load_dotenv
import requests

load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

DB_PATH = "chat.db"
app = Flask(__name__)

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_conn(exception):
    db = getattr(g, "_database", None)
    if db:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS lorebook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT
        );
    """)
    db.commit()

@app.route("/set_personality", methods=["POST"])
def set_personality():
    data = request.json
    key = "personality"
    value = data.get("personality", "")
    db = get_db()
    db.execute(
        "INSERT INTO lorebook (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value)
    )
    db.commit()
    return jsonify({"ok": True})

@app.route("/get_personality", methods=["GET"])
def get_personality():
    db = get_db()
    r = db.execute("SELECT value FROM lorebook WHERE key=?", ("personality",)).fetchone()
    return jsonify({"personality": r["value"] if r else ""})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    session_id = data.get("session_id", "default")
    message = data.get("message", "")

    db = get_db()
    db.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, "user", message),
    )
    db.commit()

    r = db.execute("SELECT value FROM lorebook WHERE key=?", ("personality",)).fetchone()
    personality = r["value"] if r else ""

    rows = db.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 10",
        (session_id,),
    ).fetchall()

    history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    messages = []
    if personality:
        messages.append({"role": "system", "content": personality})
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {"model": "gpt-4o-mini", "messages": messages, "max_tokens": 500}

    resp = requests.post(OPENAI_CHAT_URL, headers=headers, json=payload)
    result = resp.json()
    reply = result["choices"][0]["message"]["content"]

    db.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, "assistant", reply),
    )
    db.commit()

    return jsonify({"reply": reply})

@app.route("/history", methods=["GET"])
def history():
    session_id = request.args.get("session_id", "default")
    db = get_db()
    rows = db.execute(
        "SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()
    return jsonify({"messages": [dict(r) for r in rows]})

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)
