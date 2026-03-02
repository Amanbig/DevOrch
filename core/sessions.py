import sqlite3
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

from schemas.message import Message

DATA_DIR = Path.home() / ".devpilot"
DB_PATH = DATA_DIR / "sessions.db"

# Default limits
DEFAULT_MESSAGE_LIMIT = 50  # Max messages before summarization
DEFAULT_TOKEN_ESTIMATE_LIMIT = 100000  # Rough token estimate


class SessionManager:
    """Manages chat session persistence using SQLite."""

    def __init__(self, message_limit: int = DEFAULT_MESSAGE_LIMIT):
        self._ensure_db()
        self.current_session_id: Optional[str] = None
        self.message_limit = message_limit
        self._message_count = 0

    def _ensure_db(self):
        """Create database and tables if they don't exist."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                parent_session_id TEXT,
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_session_id) REFERENCES sessions(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                name TEXT,
                tool_call_id TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)

        # Add parent_session_id and summary columns if they don't exist (migration)
        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN parent_session_id TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        conn.commit()
        conn.close()

    def create_session(
        self,
        provider: str,
        model: str,
        name: Optional[str] = None,
        parent_session_id: Optional[str] = None,
        summary: Optional[str] = None
    ) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())[:8]
        if not name:
            name = f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """INSERT INTO sessions (id, name, provider, model, parent_session_id, summary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, name, provider, model, parent_session_id, summary)
        )

        conn.commit()
        conn.close()

        self.current_session_id = session_id
        self._message_count = 0
        return session_id

    def save_message(self, message: Message, session_id: Optional[str] = None):
        """Save a message to the current or specified session."""
        sid = session_id or self.current_session_id
        if not sid:
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        metadata_json = json.dumps(message.metadata) if message.metadata else None

        cursor.execute(
            """INSERT INTO messages (session_id, role, content, name, tool_call_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sid, message.role, message.content, message.name, message.tool_call_id, metadata_json)
        )

        # Update session timestamp
        cursor.execute(
            "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (sid,)
        )

        conn.commit()
        conn.close()

        if sid == self.current_session_id:
            self._message_count += 1

    def get_message_count(self, session_id: Optional[str] = None) -> int:
        """Get the number of messages in a session."""
        sid = session_id or self.current_session_id
        if not sid:
            return 0

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (sid,))
        count = cursor.fetchone()[0]

        conn.close()
        return count

    def should_summarize(self) -> bool:
        """Check if the current session should be summarized."""
        return self._message_count >= self.message_limit

    def load_session(self, session_id: str) -> Tuple[dict, List[Message]]:
        """Load a session and its messages. Returns (session_info, messages)."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get session info
        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        session_row = cursor.fetchone()

        if not session_row:
            conn.close()
            raise ValueError(f"Session '{session_id}' not found")

        session_info = dict(session_row)

        # Get messages
        cursor.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        )
        message_rows = cursor.fetchall()

        messages = []
        for row in message_rows:
            metadata = json.loads(row["metadata"]) if row["metadata"] else None
            msg = Message(
                role=row["role"],
                content=row["content"],
                name=row["name"],
                tool_call_id=row["tool_call_id"],
                metadata=metadata
            )
            messages.append(msg)

        conn.close()

        self.current_session_id = session_id
        self._message_count = len(messages)
        return session_info, messages

    def create_continuation_session(
        self,
        provider: str,
        model: str,
        summary: str
    ) -> str:
        """Create a new session that continues from the current one with a summary."""
        parent_id = self.current_session_id

        # Get parent session name for naming continuation
        name = f"Continuation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        new_session_id = self.create_session(
            provider=provider,
            model=model,
            name=name,
            parent_session_id=parent_id,
            summary=summary
        )

        return new_session_id

    def get_session_chain(self, session_id: str) -> List[dict]:
        """Get the chain of sessions (parent -> child) for context."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        chain = []
        current_id = session_id

        # Walk up the parent chain
        while current_id:
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (current_id,))
            row = cursor.fetchone()
            if row:
                chain.insert(0, dict(row))
                current_id = row["parent_session_id"]
            else:
                break

        conn.close()
        return chain

    def list_sessions(self, limit: int = 20) -> List[dict]:
        """List recent sessions."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """SELECT s.*, COUNT(m.id) as message_count
               FROM sessions s
               LEFT JOIN messages m ON s.id = m.session_id
               GROUP BY s.id
               ORDER BY s.updated_at DESC
               LIMIT ?""",
            (limit,)
        )

        sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Enable foreign keys for cascade delete
        cursor.execute("PRAGMA foreign_keys = ON")

        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return deleted

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        exists = cursor.fetchone() is not None

        conn.close()
        return exists
