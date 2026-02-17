"""
Conversation history storage using SQLite.

Each VAPI call has a unique call_id. All messages for that call are stored
in chronological order so the LLM receives full conversational context.
"""

import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / "conversations.db"


class ConversationStore:
    """Thread-safe, file-based conversation memory backed by SQLite."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        # Single connection reused across calls (check_same_thread=False
        # lets Flask's threaded mode work; the lock serialises writes).
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    # ── private helpers ─────────────────────────────────────────────────────

    def _init_db(self):
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id    TEXT    NOT NULL,
                    role       TEXT    NOT NULL,
                    content    TEXT    NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_call_id
                ON messages(call_id)
            """)

    # ── public API ──────────────────────────────────────────────────────────

    def add_message(self, call_id: str, role: str, content: str):
        """Append a message to a call's history."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (call_id, role, content) VALUES (?, ?, ?)",
                (call_id, role, content),
            )
            self._conn.commit()

    def get_history(self, call_id: str) -> list[dict]:
        """Return the full ordered message list for a call."""
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE call_id = ? ORDER BY id ASC",
            (call_id,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def clear_call(self, call_id: str):
        """Delete all messages for a finished call (optional cleanup)."""
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE call_id = ?", (call_id,))
            self._conn.commit()

    def list_calls(self) -> list[str]:
        """Return distinct call_ids (useful for debugging)."""
        rows = self._conn.execute(
            "SELECT DISTINCT call_id FROM messages ORDER BY MIN(id)"
        ).fetchall()
        return [r[0] for r in rows]
