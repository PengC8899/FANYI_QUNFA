import sqlite3
import threading
from typing import List, Tuple, Optional
from datetime import datetime, timedelta

class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._groups_cache = None
        self._init_db()
        self._load_groups_cache()

    def _load_groups_cache(self):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT chat_id, title, activated_at FROM groups WHERE active=1")
            rows = cur.fetchall()
            conn.close()
            self._groups_cache = [(int(r[0]), str(r[1]), str(r[2])) for r in rows]

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    activated_by INTEGER,
                    activated_at TEXT,
                    target_lang TEXT DEFAULT 'auto',
                    active INTEGER DEFAULT 1,
                    translation_enabled INTEGER DEFAULT 1
                )
                """
            )
            # Migration: Add translation_enabled column if not exists
            try:
                cur.execute("ALTER TABLE groups ADD COLUMN translation_enabled INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass # Already exists

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS broadcasters (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS controllers (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    by_user_id INTEGER,
                    content_type TEXT,
                    created_at TEXT,
                    total INTEGER,
                    success INTEGER,
                    failure INTEGER,
                    errors_sample TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trans_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    message_id INTEGER,
                    user_id INTEGER,
                    src_lang TEXT,
                    dst_lang TEXT,
                    success INTEGER,
                    created_at TEXT
                )
                """
            )
            conn.commit()
            conn.close()

    def add_group(self, chat_id: int, title: str, activated_by: int, activated_at: datetime):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "REPLACE INTO groups(chat_id, title, activated_by, activated_at, active) VALUES(?,?,?,?,1)",
                (chat_id, title, activated_by, activated_at.isoformat()),
            )
            conn.commit()
            conn.close()
            # Update cache
            if self._groups_cache is not None:
                # Remove if exists then add to ensure latest info
                self._groups_cache = [g for g in self._groups_cache if g[0] != chat_id]
                self._groups_cache.append((chat_id, title, activated_at.isoformat()))

    def remove_group(self, chat_id: int):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("DELETE FROM groups WHERE chat_id=?", (chat_id,))
            conn.commit()
            conn.close()
            if self._groups_cache is not None:
                self._groups_cache = [g for g in self._groups_cache if g[0] != chat_id]

    def deactivate_group(self, chat_id: int):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("UPDATE groups SET active=0 WHERE chat_id=?", (chat_id,))
            conn.commit()
            conn.close()
            if self._groups_cache is not None:
                self._groups_cache = [g for g in self._groups_cache if g[0] != chat_id]

    def migrate_group(self, old_chat_id: int, new_chat_id: int):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("UPDATE groups SET chat_id=? WHERE chat_id=?", (new_chat_id, old_chat_id))
            conn.commit()
            conn.close()
            self._load_groups_cache()

    def list_groups(self, page: int = 1, page_size: int = 20) -> List[Tuple[int, str, str]]:
        with self._lock:
            if self._groups_cache is None:
                self._load_groups_cache()
            
            start = (page - 1) * page_size
            end = start + page_size
            return self._groups_cache[start:end]

    def get_all_active_groups(self) -> List[Tuple[int, str, str]]:
        with self._lock:
            # Always reload to ensure fresh data from DB (cross-process sync)
            self._load_groups_cache()
            return list(self._groups_cache)

    def is_group_active(self, chat_id: int) -> bool:
        with self._lock:
            if self._groups_cache is not None:
                for g in self._groups_cache:
                    if g[0] == chat_id:
                        return True
                return False
            
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT active FROM groups WHERE chat_id=?", (chat_id,))
            row = cur.fetchone()
            conn.close()
            return bool(row and int(row[0]) == 1)

    def set_translation_enabled(self, chat_id: int, enabled: bool):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            val = 1 if enabled else 0
            cur.execute("UPDATE groups SET translation_enabled=? WHERE chat_id=?", (val, chat_id))
            conn.commit()
            conn.close()

    def is_translation_enabled(self, chat_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT translation_enabled FROM groups WHERE chat_id=?", (chat_id,))
            row = cur.fetchone()
            conn.close()
            # Default to True if column is NULL or missing (though migration sets default 1)
            if row:
                return bool(row[0])
            return True

    def set_group_lang(self, chat_id: int, target_lang: str):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("UPDATE groups SET target_lang=? WHERE chat_id=?", (target_lang, chat_id))
            conn.commit()
            conn.close()

    def get_group_lang(self, chat_id: int) -> str:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT target_lang FROM groups WHERE chat_id=?", (chat_id,))
            row = cur.fetchone()
            conn.close()
            return row[0] if row else "auto"

    def add_broadcaster(self, user_id: int, username: Optional[str]):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("REPLACE INTO broadcasters(user_id, username) VALUES(?,?)", (user_id, username))
            conn.commit()
            conn.close()

    def remove_broadcaster(self, user_id: int):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("DELETE FROM broadcasters WHERE user_id=?", (user_id,))
            conn.commit()
            conn.close()

    def list_broadcasters(self) -> List[Tuple[int, Optional[str]]]:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT user_id, username FROM broadcasters")
            rows = cur.fetchall()
            conn.close()
            return [(int(r[0]), r[1]) for r in rows]

    def is_broadcaster(self, user_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM broadcasters WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            conn.close()
            return bool(row)

    def add_controller(self, user_id: int, username: Optional[str]):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("REPLACE INTO controllers(user_id, username) VALUES(?,?)", (user_id, username))
            conn.commit()
            conn.close()

    def remove_controller(self, user_id: int):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("DELETE FROM controllers WHERE user_id=?", (user_id,))
            conn.commit()
            conn.close()

    def list_controllers(self) -> List[Tuple[int, Optional[str]]]:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT user_id, username FROM controllers")
            rows = cur.fetchall()
            conn.close()
            return [(int(r[0]), r[1]) for r in rows]

    def is_controller(self, user_id: int) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM controllers WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            conn.close()
            return bool(row)

    def record_broadcast(self, by_user_id: int, content_type: str, total: int, success: int, failure: int, errors_sample: str):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO broadcasts(by_user_id, content_type, created_at, total, success, failure, errors_sample) VALUES(?,?,?,?,?,?,?)",
                (by_user_id, content_type, datetime.utcnow().isoformat(), total, success, failure, errors_sample),
            )
            conn.commit()
            conn.close()

    def count_recent_broadcasts(self, hours: int = 1) -> int:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            cur.execute("SELECT COUNT(1) FROM broadcasts WHERE created_at>=?", (since,))
            cnt = cur.fetchone()[0]
            conn.close()
            return int(cnt)

    def record_trans_log(self, chat_id: int, message_id: int, user_id: int, src_lang: str, dst_lang: str, success: bool):
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO trans_logs(chat_id, message_id, user_id, src_lang, dst_lang, success, created_at) VALUES(?,?,?,?,?,?,?)",
                (chat_id, message_id, user_id, src_lang, dst_lang, int(success), datetime.utcnow().isoformat()),
            )
            conn.commit()
            conn.close()
