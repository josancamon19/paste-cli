import sqlite3
from datetime import datetime
from pathlib import Path

from pastepy.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clipboard_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'text',
            source_app TEXT,
            source_url TEXT,
            size_bytes INTEGER,
            content_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            last_used_at TEXT DEFAULT (datetime('now', 'localtime')),
            use_count INTEGER DEFAULT 1
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_last_used ON clipboard_items(last_used_at DESC)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_content_hash ON clipboard_items(content_hash)"
    )
    conn.commit()
    conn.close()


def add_item(
    content: str,
    content_type: str,
    source_app: str | None,
    source_url: str | None,
    size_bytes: int,
    content_hash: str,
) -> int:
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = conn.execute(
        "SELECT id FROM clipboard_items WHERE content_hash = ?",
        (content_hash,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE clipboard_items SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
            (now, existing["id"]),
        )
        conn.commit()
        item_id = existing["id"]
        conn.close()
        return item_id

    cursor = conn.execute(
        """INSERT INTO clipboard_items
           (content, content_type, source_app, source_url, size_bytes, content_hash, created_at, last_used_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (content, content_type, source_app, source_url, size_bytes, content_hash, now, now),
    )
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()
    return item_id


def get_items(
    limit: int = 50,
    offset: int = 0,
    content_type: str | None = None,
    app: str | None = None,
    search: str | None = None,
) -> list[sqlite3.Row]:
    conn = get_connection()
    query = "SELECT * FROM clipboard_items WHERE 1=1"
    params: list = []
    if content_type:
        query += " AND content_type = ?"
        params.append(content_type)
    if app:
        query += " AND source_app LIKE ?"
        params.append(f"%{app}%")
    if search:
        query += " AND content LIKE ?"
        params.append(f"%{search}%")
    query += " ORDER BY last_used_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    items = conn.execute(query, params).fetchall()
    conn.close()
    return items


def get_item(item_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    item = conn.execute(
        "SELECT * FROM clipboard_items WHERE id = ?", (item_id,)
    ).fetchone()
    conn.close()
    return item


def bump_item(item_id: int) -> None:
    conn = get_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE clipboard_items SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
        (now, item_id),
    )
    conn.commit()
    conn.close()


def delete_item(item_id: int) -> bool:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM clipboard_items WHERE id = ?", (item_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def clear_all() -> int:
    conn = get_connection()
    cursor = conn.execute("DELETE FROM clipboard_items")
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count


def get_stats() -> dict:
    conn = get_connection()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM clipboard_items").fetchone()[0],
        "text": conn.execute(
            "SELECT COUNT(*) FROM clipboard_items WHERE content_type = 'text'"
        ).fetchone()[0],
        "image": conn.execute(
            "SELECT COUNT(*) FROM clipboard_items WHERE content_type = 'image'"
        ).fetchone()[0],
        "file": conn.execute(
            "SELECT COUNT(*) FROM clipboard_items WHERE content_type = 'file'"
        ).fetchone()[0],
    }
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    stats["db_size_mb"] = round(db_size / (1024 * 1024), 2)
    conn.close()
    return stats
