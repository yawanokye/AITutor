from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class AuthError(ValueError):
    pass


class AuthManager:
    """Password hashing and signed bearer tokens using Python's standard library."""

    def __init__(self, *, secret: str, access_token_minutes: int) -> None:
        self.secret = secret.encode("utf-8")
        self.access_token_minutes = max(15, access_token_minutes)

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @staticmethod
    def hash_password(password: str) -> str:
        if len(password) < 8:
            raise AuthError("Password must contain at least 8 characters.")
        salt = secrets.token_bytes(16)
        iterations = 390_000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return f"pbkdf2_sha256${iterations}${AuthManager._b64(salt)}${AuthManager._b64(digest)}"

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            algorithm, iterations, salt, expected = password_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), AuthManager._unb64(salt), int(iterations))
            return hmac.compare_digest(AuthManager._b64(digest), expected)
        except (ValueError, TypeError):
            return False

    def issue_token(self, user: dict[str, Any]) -> str:
        now = _utcnow()
        payload = {
            "sub": str(user["id"]),
            "role": str(user["role"]),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.access_token_minutes)).timestamp()),
        }
        encoded = self._b64(_json(payload).encode("utf-8"))
        signature = self._b64(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            encoded, signature = token.split(".", 1)
            expected = self._b64(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise AuthError("Invalid sign-in token.")
            payload = json.loads(self._unb64(encoded).decode("utf-8"))
            if int(payload.get("exp", 0)) < int(_utcnow().timestamp()):
                raise AuthError("Your sign-in has expired. Please sign in again.")
            return payload
        except AuthError:
            raise
        except Exception as exc:
            raise AuthError("Invalid sign-in token.") from exc


class AccountStore:
    """Persistent accounts, classes, progress, chat and video jobs.

    PostgreSQL is used on Render. SQLite is used locally so the full app can be tested
    without provisioning external infrastructure.
    """

    def __init__(self, *, database_url: str, storage_dir: Path) -> None:
        self.database_url = database_url
        self._use_postgres = bool(database_url and psycopg is not None)
        self.sqlite_path = storage_dir / "ai_tutor_accounts.sqlite3"
        self._lock = threading.RLock()
        self.initialise()

    def _pg(self):
        if not self._use_postgres:
            raise RuntimeError("PostgreSQL is not configured")
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=20, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialise(self) -> None:
        if self._use_postgres:
            statements = [
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('student','teacher','admin')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_login TIMESTAMPTZ
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_classes (
                    id TEXT PRIMARY KEY,
                    teacher_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    subject TEXT NOT NULL DEFAULT '',
                    join_code TEXT UNIQUE NOT NULL,
                    knowledge_mode TEXT NOT NULL DEFAULT 'course_only',
                    learning_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
                    weekly_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
                    tutor_instructions TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_class_members (
                    class_id TEXT NOT NULL REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
                    student_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (class_id, student_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_chat_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL DEFAULT 'Learning session',
                    course TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES ai_tutor_chat_sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_learning_events (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    class_id TEXT REFERENCES ai_tutor_classes(id) ON DELETE SET NULL,
                    event_type TEXT NOT NULL,
                    topic TEXT NOT NULL DEFAULT '',
                    score DOUBLE PRECISION,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_usage_events (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT REFERENCES ai_tutor_users(id) ON DELETE SET NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    task TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_video_jobs (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    class_id TEXT REFERENCES ai_tutor_classes(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL DEFAULT '',
                    script TEXT NOT NULL DEFAULT '',
                    visual_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    public_token TEXT UNIQUE NOT NULL,
                    provider_job_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'script_ready',
                    hosted_url TEXT NOT NULL DEFAULT '',
                    download_url TEXT NOT NULL DEFAULT '',
                    stream_url TEXT NOT NULL DEFAULT '',
                    estimated_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS knowledge_mode TEXT NOT NULL DEFAULT 'course_only'",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS learning_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS weekly_topics JSONB NOT NULL DEFAULT '[]'::jsonb",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS tutor_instructions TEXT NOT NULL DEFAULT ''",
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_events_user_created ON ai_tutor_learning_events(user_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_members_student ON ai_tutor_class_members(student_id)",
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_usage_user_created ON ai_tutor_usage_events(user_id, created_at DESC)",
            ]
            with self._pg() as conn:
                with conn.cursor() as cur:
                    for statement in statements:
                        cur.execute(statement)
                conn.commit()
            return

        schema = """
        CREATE TABLE IF NOT EXISTS ai_tutor_users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL, last_login TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_classes (
            id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL, name TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
            join_code TEXT UNIQUE NOT NULL, knowledge_mode TEXT NOT NULL DEFAULT 'course_only',
            learning_outcomes TEXT NOT NULL DEFAULT '[]', weekly_topics TEXT NOT NULL DEFAULT '[]',
            tutor_instructions TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY(teacher_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_class_members (
            class_id TEXT NOT NULL, student_id TEXT NOT NULL, joined_at TEXT NOT NULL,
            PRIMARY KEY(class_id, student_id),
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_chat_sessions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'Learning session',
            course TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]', provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES ai_tutor_chat_sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_learning_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, class_id TEXT,
            event_type TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '', score REAL, metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, provider TEXT NOT NULL, model TEXT NOT NULL,
            task TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES ai_tutor_users(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_video_jobs (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, class_id TEXT, title TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
            script TEXT NOT NULL DEFAULT '', visual_json TEXT NOT NULL DEFAULT '{}', public_token TEXT UNIQUE NOT NULL,
            provider_job_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'script_ready', hosted_url TEXT NOT NULL DEFAULT '',
            download_url TEXT NOT NULL DEFAULT '', stream_url TEXT NOT NULL DEFAULT '', estimated_minutes REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_events_user_created ON ai_tutor_learning_events(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_members_student ON ai_tutor_class_members(student_id);
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_usage_user_created ON ai_tutor_usage_events(user_id, created_at DESC);
        """
        with self._lock, self._sqlite() as conn:
            conn.executescript(schema)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(ai_tutor_classes)").fetchall()}
            migrations = {
                "knowledge_mode": "TEXT NOT NULL DEFAULT 'course_only'",
                "learning_outcomes": "TEXT NOT NULL DEFAULT '[]'",
                "weekly_topics": "TEXT NOT NULL DEFAULT '[]'",
                "tutor_instructions": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in migrations.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE ai_tutor_classes ADD COLUMN {column} {definition}")
            conn.commit()

    @staticmethod
    def public_user(row: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "email": str(row["email"]),
            "display_name": str(row["display_name"]),
            "role": str(row["role"]),
            "created_at": _iso(row["created_at"]),
        }

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_users WHERE id=%s", (user_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        with self._lock, self._sqlite() as conn:
            row = conn.execute("SELECT * FROM ai_tutor_users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        email = email.strip().lower()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_users WHERE email=%s", (email,))
                row = cur.fetchone()
                return dict(row) if row else None
        with self._lock, self._sqlite() as conn:
            row = conn.execute("SELECT * FROM ai_tutor_users WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None

    def create_user(self, *, email: str, password_hash: str, display_name: str, role: str) -> dict[str, Any]:
        user_id = str(uuid.uuid4())
        email = email.strip().lower()
        display_name = " ".join(display_name.split())[:100]
        now = _utcnow()
        try:
            if self._use_postgres:
                with self._pg() as conn, conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO ai_tutor_users(id,email,password_hash,display_name,role,created_at) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                        (user_id, email, password_hash, display_name, role, now),
                    )
                    row = dict(cur.fetchone())
                    conn.commit()
                    return row
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    "INSERT INTO ai_tutor_users(id,email,password_hash,display_name,role,created_at) VALUES(?,?,?,?,?,?)",
                    (user_id, email, password_hash, display_name, role, now.isoformat()),
                )
                conn.commit()
            return self.get_user(user_id) or {}
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise AuthError("An account already exists for this email address.") from exc
            raise

    def touch_login(self, user_id: str) -> None:
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("UPDATE ai_tutor_users SET last_login=%s WHERE id=%s", (now, user_id))
                conn.commit()
            return
        with self._lock, self._sqlite() as conn:
            conn.execute("UPDATE ai_tutor_users SET last_login=? WHERE id=?", (now.isoformat(), user_id))
            conn.commit()

    def _new_join_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(7))

    def create_class(
        self, *, teacher_id: str, name: str, subject: str, knowledge_mode: str = "course_only",
        learning_outcomes: list[str] | None = None, weekly_topics: list[str] | None = None,
        tutor_instructions: str = ""
    ) -> dict[str, Any]:
        class_id = str(uuid.uuid4())
        now = _utcnow()
        knowledge_mode = knowledge_mode if knowledge_mode in {"course_only", "course_plus_approved", "general"} else "course_only"
        outcomes = [str(item).strip()[:300] for item in (learning_outcomes or []) if str(item).strip()][:20]
        weeks = [str(item).strip()[:300] for item in (weekly_topics or []) if str(item).strip()][:24]
        tutor_instructions = tutor_instructions.strip()[:3000]
        for _ in range(6):
            join_code = self._new_join_code()
            try:
                if self._use_postgres:
                    with self._pg() as conn, conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO ai_tutor_classes(
                                id,teacher_id,name,subject,join_code,knowledge_mode,learning_outcomes,weekly_topics,tutor_instructions,created_at
                            ) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                            (class_id, teacher_id, name.strip()[:140], subject.strip()[:160], join_code, knowledge_mode, _json(outcomes), _json(weeks), tutor_instructions, now),
                        )
                        conn.commit()
                else:
                    with self._lock, self._sqlite() as conn:
                        conn.execute(
                            """INSERT INTO ai_tutor_classes(
                                id,teacher_id,name,subject,join_code,knowledge_mode,learning_outcomes,weekly_topics,tutor_instructions,created_at
                            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (class_id, teacher_id, name.strip()[:140], subject.strip()[:160], join_code, knowledge_mode, _json(outcomes), _json(weeks), tutor_instructions, now.isoformat()),
                        )
                        conn.commit()
                return self.get_class(class_id) or {}
            except Exception as exc:
                if "join_code" not in str(exc).lower() and "unique" not in str(exc).lower():
                    raise
        raise RuntimeError("A unique class code could not be created.")

    def get_class(self, class_id: str) -> dict[str, Any] | None:
        sql = """
        SELECT c.*, u.display_name AS teacher_name,
               (SELECT COUNT(*) FROM ai_tutor_class_members m WHERE m.class_id=c.id) AS student_count
        FROM ai_tutor_classes c JOIN ai_tutor_users u ON u.id=c.teacher_id WHERE c.id={placeholder}
        """
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql.format(placeholder="%s"), (class_id,))
                row = cur.fetchone()
                return self._class_public(dict(row)) if row else None
        with self._lock, self._sqlite() as conn:
            row = conn.execute(sql.format(placeholder="?"), (class_id,)).fetchone()
            return self._class_public(dict(row)) if row else None

    @staticmethod
    def _class_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id", "")),
            "name": str(row.get("name", "")),
            "subject": str(row.get("subject", "")),
            "join_code": str(row.get("join_code", "")),
            "student_count": int(row.get("student_count", 0) or 0),
            "teacher_name": str(row.get("teacher_name", "")),
            "knowledge_mode": str(row.get("knowledge_mode", "course_only") or "course_only"),
            "learning_outcomes": _safe_json(row.get("learning_outcomes"), []),
            "weekly_topics": _safe_json(row.get("weekly_topics"), []),
            "tutor_instructions": str(row.get("tutor_instructions", "") or ""),
            "created_at": _iso(row.get("created_at")),
        }

    def class_for_user(self, *, class_id: str, user_id: str, role: str) -> dict[str, Any] | None:
        classroom = self.get_class(class_id)
        if not classroom:
            return None
        if role in {"teacher", "admin"}:
            if role == "admin":
                return classroom
            if self._use_postgres:
                with self._pg() as conn, conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM ai_tutor_classes WHERE id=%s AND teacher_id=%s", (class_id, user_id))
                    return classroom if cur.fetchone() else None
            with self._lock, self._sqlite() as conn:
                row = conn.execute("SELECT 1 FROM ai_tutor_classes WHERE id=? AND teacher_id=?", (class_id, user_id)).fetchone()
                return classroom if row else None
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM ai_tutor_class_members WHERE class_id=%s AND student_id=%s", (class_id, user_id))
                return classroom if cur.fetchone() else None
        with self._lock, self._sqlite() as conn:
            row = conn.execute("SELECT 1 FROM ai_tutor_class_members WHERE class_id=? AND student_id=?", (class_id, user_id)).fetchone()
            return classroom if row else None

    def update_class_profile(
        self, *, class_id: str, teacher_id: str, name: str, subject: str, knowledge_mode: str,
        learning_outcomes: list[str], weekly_topics: list[str], tutor_instructions: str
    ) -> dict[str, Any]:
        knowledge_mode = knowledge_mode if knowledge_mode in {"course_only", "course_plus_approved", "general"} else "course_only"
        outcomes = [str(item).strip()[:300] for item in learning_outcomes if str(item).strip()][:20]
        weeks = [str(item).strip()[:300] for item in weekly_topics if str(item).strip()][:24]
        values = (name.strip()[:140], subject.strip()[:160], knowledge_mode, _json(outcomes), _json(weeks), tutor_instructions.strip()[:3000])
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE ai_tutor_classes SET name=%s,subject=%s,knowledge_mode=%s,learning_outcomes=%s::jsonb,weekly_topics=%s::jsonb,tutor_instructions=%s
                       WHERE id=%s AND teacher_id=%s""",
                    (*values, class_id, teacher_id),
                )
                if cur.rowcount == 0:
                    raise ValueError("Class not found or you do not manage it.")
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                cur = conn.execute(
                    """UPDATE ai_tutor_classes SET name=?,subject=?,knowledge_mode=?,learning_outcomes=?,weekly_topics=?,tutor_instructions=?
                       WHERE id=? AND teacher_id=?""",
                    (*values, class_id, teacher_id),
                )
                if cur.rowcount == 0:
                    raise ValueError("Class not found or you do not manage it.")
                conn.commit()
        return self.get_class(class_id) or {}

    def join_class(self, *, student_id: str, join_code: str) -> dict[str, Any]:
        code = join_code.strip().upper()
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT id FROM ai_tutor_classes WHERE join_code=%s", (code,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Class code not found.")
                class_id = row["id"]
                cur.execute(
                    "INSERT INTO ai_tutor_class_members(class_id,student_id,joined_at) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (class_id, student_id, now),
                )
                conn.commit()
            return self.get_class(str(class_id)) or {}
        with self._lock, self._sqlite() as conn:
            row = conn.execute("SELECT id FROM ai_tutor_classes WHERE join_code=?", (code,)).fetchone()
            if not row:
                raise ValueError("Class code not found.")
            class_id = row["id"]
            conn.execute(
                "INSERT OR IGNORE INTO ai_tutor_class_members(class_id,student_id,joined_at) VALUES(?,?,?)",
                (class_id, student_id, now.isoformat()),
            )
            conn.commit()
        return self.get_class(str(class_id)) or {}

    def classes_for_user(self, user_id: str, role: str) -> list[dict[str, Any]]:
        if role in {"teacher", "admin"}:
            sql = """
            SELECT c.*, u.display_name AS teacher_name,
                   (SELECT COUNT(*) FROM ai_tutor_class_members m WHERE m.class_id=c.id) AS student_count
            FROM ai_tutor_classes c JOIN ai_tutor_users u ON u.id=c.teacher_id
            WHERE c.teacher_id={placeholder} ORDER BY c.created_at DESC
            """
        else:
            sql = """
            SELECT c.*, u.display_name AS teacher_name,
                   (SELECT COUNT(*) FROM ai_tutor_class_members m2 WHERE m2.class_id=c.id) AS student_count
            FROM ai_tutor_classes c
            JOIN ai_tutor_class_members m ON m.class_id=c.id
            JOIN ai_tutor_users u ON u.id=c.teacher_id
            WHERE m.student_id={placeholder} ORDER BY m.joined_at DESC
            """
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql.format(placeholder="%s"), (user_id,))
                return [self._class_public(dict(row)) for row in cur.fetchall()]
        with self._lock, self._sqlite() as conn:
            rows = conn.execute(sql.format(placeholder="?"), (user_id,)).fetchall()
            return [self._class_public(dict(row)) for row in rows]

    def ensure_chat_session(self, *, session_id: str, user_id: str, title: str, course: str) -> None:
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_tutor_chat_sessions(id,user_id,title,course,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title, course=EXCLUDED.course, updated_at=EXCLUDED.updated_at
                    """,
                    (session_id, user_id, title[:180], course[:160], now, now),
                )
                conn.commit()
            return
        with self._lock, self._sqlite() as conn:
            conn.execute(
                """
                INSERT INTO ai_tutor_chat_sessions(id,user_id,title,course,created_at,updated_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title, course=excluded.course, updated_at=excluded.updated_at
                """,
                (session_id, user_id, title[:180], course[:160], now.isoformat(), now.isoformat()),
            )
            conn.commit()

    def add_chat_message(
        self, *, session_id: str, role: str, content: str, sources: list[str] | None = None,
        provider: str = "", model: str = ""
    ) -> None:
        now = _utcnow()
        sources = sources or []
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_tutor_chat_messages(session_id,role,content,sources,provider,model,created_at) VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s)",
                    (session_id, role, content[:30000], _json(sources), provider, model, now),
                )
                cur.execute("UPDATE ai_tutor_chat_sessions SET updated_at=%s WHERE id=%s", (now, session_id))
                conn.commit()
            return
        with self._lock, self._sqlite() as conn:
            conn.execute(
                "INSERT INTO ai_tutor_chat_messages(session_id,role,content,sources,provider,model,created_at) VALUES(?,?,?,?,?,?,?)",
                (session_id, role, content[:30000], _json(sources), provider, model, now.isoformat()),
            )
            conn.execute("UPDATE ai_tutor_chat_sessions SET updated_at=? WHERE id=?", (now.isoformat(), session_id))
            conn.commit()

    def record_learning_event(
        self, *, user_id: str, event_type: str, topic: str = "", score: float | None = None,
        metadata: dict[str, Any] | None = None, class_id: str | None = None
    ) -> None:
        now = _utcnow()
        metadata = metadata or {}
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_tutor_learning_events(user_id,class_id,event_type,topic,score,metadata,created_at) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s)",
                    (user_id, class_id or None, event_type[:80], topic[:220], score, _json(metadata), now),
                )
                conn.commit()
            return
        with self._lock, self._sqlite() as conn:
            conn.execute(
                "INSERT INTO ai_tutor_learning_events(user_id,class_id,event_type,topic,score,metadata,created_at) VALUES(?,?,?,?,?,?,?)",
                (user_id, class_id or None, event_type[:80], topic[:220], score, _json(metadata), now.isoformat()),
            )
            conn.commit()

    def record_usage(
        self, *, user_id: str | None, provider: str, model: str, task: str,
        input_tokens: int, output_tokens: int, estimated_cost_usd: float
    ) -> None:
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ai_tutor_usage_events(user_id,provider,model,task,input_tokens,output_tokens,estimated_cost_usd,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (user_id, provider, model, task, input_tokens, output_tokens, estimated_cost_usd, now),
                )
                conn.commit()
            return
        with self._lock, self._sqlite() as conn:
            conn.execute(
                "INSERT INTO ai_tutor_usage_events(user_id,provider,model,task,input_tokens,output_tokens,estimated_cost_usd,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (user_id, provider, model, task, input_tokens, output_tokens, estimated_cost_usd, now.isoformat()),
            )
            conn.commit()

    def create_video_job(
        self, *, user_id: str, title: str, topic: str, script: str, visual: dict[str, Any],
        estimated_minutes: float, class_id: str | None = None
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        public_token = secrets.token_urlsafe(24)
        now = _utcnow()
        values = (job_id, user_id, class_id or None, title[:180], topic[:300], script, _json(visual), public_token, estimated_minutes, now)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_tutor_video_jobs(id,user_id,class_id,title,topic,script,visual_json,public_token,estimated_minutes,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
                    """,
                    (*values, now),
                )
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    """
                    INSERT INTO ai_tutor_video_jobs(id,user_id,class_id,title,topic,script,visual_json,public_token,estimated_minutes,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (*values[:-1], now.isoformat(), now.isoformat()),
                )
                conn.commit()
        return self.get_video_job(job_id, user_id=user_id) or {}

    def update_video_job(self, job_id: str, **updates: Any) -> None:
        allowed = {"provider_job_id", "status", "hosted_url", "download_url", "stream_url"}
        clean = {key: str(value or "") for key, value in updates.items() if key in allowed}
        if not clean:
            return
        clean["updated_at"] = _utcnow()
        if self._use_postgres:
            parts = [f"{key}=%s" for key in clean]
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(f"UPDATE ai_tutor_video_jobs SET {', '.join(parts)} WHERE id=%s", (*clean.values(), job_id))
                conn.commit()
            return
        parts = [f"{key}=?" for key in clean]
        values = [value.isoformat() if isinstance(value, datetime) else value for value in clean.values()]
        with self._lock, self._sqlite() as conn:
            conn.execute(f"UPDATE ai_tutor_video_jobs SET {', '.join(parts)} WHERE id=?", (*values, job_id))
            conn.commit()

    def get_video_job(self, job_id: str, *, user_id: str | None = None, public_token: str | None = None) -> dict[str, Any] | None:
        where = ["id={idph}"]
        params: list[Any] = [job_id]
        if user_id is not None:
            where.append("user_id={userph}")
            params.append(user_id)
        if public_token is not None:
            where.append("public_token={tokenph}")
            params.append(public_token)
        if self._use_postgres:
            clause = " AND ".join(where).format(idph="%s", userph="%s", tokenph="%s")
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(f"SELECT * FROM ai_tutor_video_jobs WHERE {clause}", tuple(params))
                row = cur.fetchone()
                return self._video_public(dict(row), include_private=True) if row else None
        clause = " AND ".join(where).format(idph="?", userph="?", tokenph="?")
        with self._lock, self._sqlite() as conn:
            row = conn.execute(f"SELECT * FROM ai_tutor_video_jobs WHERE {clause}", tuple(params)).fetchone()
            return self._video_public(dict(row), include_private=True) if row else None

    @staticmethod
    def _video_public(row: dict[str, Any], *, include_private: bool = False) -> dict[str, Any]:
        result = {
            "id": str(row.get("id", "")),
            "title": str(row.get("title", "")),
            "topic": str(row.get("topic", "")),
            "script": str(row.get("script", "")),
            "visual": _safe_json(row.get("visual_json"), {}),
            "video_id": str(row.get("provider_job_id", "")),
            "status": str(row.get("status", "")),
            "hosted_url": str(row.get("hosted_url", "")),
            "download_url": str(row.get("download_url", "")),
            "stream_url": str(row.get("stream_url", "")),
            "estimated_minutes": float(row.get("estimated_minutes", 0) or 0),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
        }
        if include_private:
            result["public_token"] = str(row.get("public_token", ""))
            result["user_id"] = str(row.get("user_id", ""))
            result["class_id"] = str(row.get("class_id", "") or "")
        return result

    def list_videos(self, user_id: str, limit: int = 12) -> list[dict[str, Any]]:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_video_jobs WHERE user_id=%s ORDER BY created_at DESC LIMIT %s", (user_id, limit))
                return [self._video_public(dict(row)) for row in cur.fetchall()]
        with self._lock, self._sqlite() as conn:
            rows = conn.execute("SELECT * FROM ai_tutor_video_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
            return [self._video_public(dict(row)) for row in rows]

    def list_available_videos(self, user_id: str, role: str, limit: int = 30) -> list[dict[str, Any]]:
        if role in {"teacher", "admin"}:
            return self.list_videos(user_id, limit=limit)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT DISTINCT v.* FROM ai_tutor_video_jobs v
                       JOIN ai_tutor_class_members m ON m.class_id=v.class_id
                       WHERE m.student_id=%s ORDER BY v.created_at DESC LIMIT %s""",
                    (user_id, limit),
                )
                return [self._video_public(dict(row)) for row in cur.fetchall()]
        with self._lock, self._sqlite() as conn:
            rows = conn.execute(
                """SELECT DISTINCT v.* FROM ai_tutor_video_jobs v
                   JOIN ai_tutor_class_members m ON m.class_id=v.class_id
                   WHERE m.student_id=? ORDER BY v.created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [self._video_public(dict(row)) for row in rows]

    def get_available_video(self, job_id: str, user_id: str, role: str) -> dict[str, Any] | None:
        if role in {"teacher", "admin"}:
            return self.get_video_job(job_id, user_id=user_id)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT v.* FROM ai_tutor_video_jobs v
                       JOIN ai_tutor_class_members m ON m.class_id=v.class_id
                       WHERE v.id=%s AND m.student_id=%s""",
                    (job_id, user_id),
                )
                row = cur.fetchone()
                return self._video_public(dict(row), include_private=True) if row else None
        with self._lock, self._sqlite() as conn:
            row = conn.execute(
                """SELECT v.* FROM ai_tutor_video_jobs v
                   JOIN ai_tutor_class_members m ON m.class_id=v.class_id
                   WHERE v.id=? AND m.student_id=?""",
                (job_id, user_id),
            ).fetchone()
            return self._video_public(dict(row), include_private=True) if row else None

    def dashboard(self, user_id: str, role: str) -> dict[str, Any]:
        return self._teacher_dashboard(user_id) if role in {"teacher", "admin"} else self._student_dashboard(user_id)

    def _event_rows(self, *, user_id: str | None = None, teacher_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        if teacher_id:
            sql = """
            SELECT e.*, u.display_name, u.email, c.name AS class_name
            FROM ai_tutor_learning_events e
            JOIN ai_tutor_users u ON u.id=e.user_id
            JOIN ai_tutor_class_members m ON m.student_id=e.user_id
            JOIN ai_tutor_classes c ON c.id=m.class_id AND c.teacher_id={placeholder}
            ORDER BY e.created_at DESC LIMIT {limit_placeholder}
            """
            params = (teacher_id, limit)
        else:
            sql = """
            SELECT e.*, '' AS display_name, '' AS email, '' AS class_name
            FROM ai_tutor_learning_events e WHERE e.user_id={placeholder}
            ORDER BY e.created_at DESC LIMIT {limit_placeholder}
            """
            params = (user_id, limit)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql.format(placeholder="%s", limit_placeholder="%s"), params)
                return [dict(row) for row in cur.fetchall()]
        with self._lock, self._sqlite() as conn:
            rows = conn.execute(sql.format(placeholder="?", limit_placeholder="?"), params).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _activity_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_type": str(row.get("event_type", "")),
            "topic": str(row.get("topic", "")),
            "score": None if row.get("score") is None else round(float(row.get("score")), 1),
            "metadata": _safe_json(row.get("metadata"), {}),
            "created_at": _iso(row.get("created_at")),
            "student_name": str(row.get("display_name", "")),
            "class_name": str(row.get("class_name", "")),
            "class_id": str(row.get("class_id", "") or ""),
        }

    def _usage_summary(self, user_id: str | None = None, teacher_id: str | None = None) -> list[dict[str, Any]]:
        if teacher_id:
            sql = """
            SELECT ue.provider, ue.model, SUM(ue.input_tokens) AS input_tokens,
                   SUM(ue.output_tokens) AS output_tokens, SUM(ue.estimated_cost_usd) AS cost
            FROM ai_tutor_usage_events ue
            JOIN ai_tutor_class_members m ON m.student_id=ue.user_id
            JOIN ai_tutor_classes c ON c.id=m.class_id AND c.teacher_id={placeholder}
            GROUP BY ue.provider, ue.model ORDER BY cost DESC
            """
            params = (teacher_id,)
        else:
            sql = """
            SELECT provider, model, SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens, SUM(estimated_cost_usd) AS cost
            FROM ai_tutor_usage_events WHERE user_id={placeholder}
            GROUP BY provider, model ORDER BY cost DESC
            """
            params = (user_id,)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql.format(placeholder="%s"), params)
                rows = [dict(row) for row in cur.fetchall()]
        else:
            with self._lock, self._sqlite() as conn:
                rows = [dict(row) for row in conn.execute(sql.format(placeholder="?"), params).fetchall()]
        return [
            {
                "provider": str(row.get("provider", "")),
                "model": str(row.get("model", "")),
                "input_tokens": int(row.get("input_tokens", 0) or 0),
                "output_tokens": int(row.get("output_tokens", 0) or 0),
                "estimated_cost_usd": round(float(row.get("cost", 0) or 0), 6),
            }
            for row in rows
        ]

    @staticmethod
    def _insights(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        outcome_scores: dict[str, list[float]] = defaultdict(list)
        misconceptions: Counter[str] = Counter()
        unanswered: list[dict[str, Any]] = []
        popular: Counter[str] = Counter()
        for row in rows:
            metadata = _safe_json(row.get("metadata"), {})
            outcome = str(metadata.get("learning_outcome") or metadata.get("outcome") or "").strip()
            if outcome and row.get("score") is not None:
                outcome_scores[outcome].append(float(row["score"]))
            misconception = str(metadata.get("misconception") or "").strip()
            if misconception:
                misconceptions[misconception[:220]] += 1
            for correction in metadata.get("corrections", []) if isinstance(metadata.get("corrections"), list) else []:
                correction = str(correction).strip()
                if correction:
                    misconceptions[correction[:220]] += 1
            if metadata.get("insufficient_context"):
                unanswered.append({
                    "topic": str(row.get("topic", "")),
                    "question": str(metadata.get("question", row.get("topic", "")))[:300],
                    "student_name": str(row.get("display_name", "")),
                    "class_name": str(row.get("class_name", "")),
                    "created_at": _iso(row.get("created_at")),
                })
            if row.get("event_type") == "tutor_question" and row.get("topic"):
                popular[str(row.get("topic"))[:220]] += 1
        mastery = [
            {
                "outcome": outcome,
                "average_score": round(sum(values) / len(values), 1),
                "evidence_count": len(values),
                "status": "mastered" if sum(values) / len(values) >= 70 else "developing",
            }
            for outcome, values in outcome_scores.items() if values
        ]
        mastery.sort(key=lambda item: item["average_score"])
        common = [{"misconception": text, "count": count} for text, count in misconceptions.most_common(10)]
        popular_questions = [{"topic": text, "count": count} for text, count in popular.most_common(10)]
        return {
            "outcome_mastery": mastery,
            "common_misconceptions": common,
            "unanswered_questions": unanswered[:20],
            "popular_questions": popular_questions,
        }

    def _student_dashboard(self, user_id: str) -> dict[str, Any]:
        rows = self._event_rows(user_id=user_id, limit=600)
        scored = [float(row["score"]) for row in rows if row.get("score") is not None]
        topics: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.get("score") is not None and row.get("topic"):
                topics[str(row["topic"])].append(float(row["score"]))
        weak = [
            {"topic": topic, "average_score": round(sum(values) / len(values), 1), "attempts": len(values)}
            for topic, values in topics.items() if sum(values) / len(values) < 70
        ]
        weak.sort(key=lambda item: item["average_score"])
        insights = self._insights(rows)
        return {
            "role": "student",
            "summary": {
                "activities": len(rows),
                "practice_completed": sum(row.get("event_type") == "practice_completed" for row in rows),
                "average_score": round(sum(scored) / len(scored), 1) if scored else None,
                "classes": len(self.classes_for_user(user_id, "student")),
            },
            "classes": self.classes_for_user(user_id, "student"),
            "recent_activity": [self._activity_public(row) for row in rows[:15]],
            "weak_topics": weak[:8],
            "students": [],
            "videos": self.list_available_videos(user_id, "student"),
            "usage": self._usage_summary(user_id=user_id),
            "interventions": [],
            **insights,
        }

    def _teacher_dashboard(self, teacher_id: str) -> dict[str, Any]:
        rows = self._event_rows(teacher_id=teacher_id, limit=2000)
        student_stats: dict[str, dict[str, Any]] = {}
        topic_scores: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            uid = str(row.get("user_id", ""))
            if uid not in student_stats:
                student_stats[uid] = {
                    "id": uid,
                    "display_name": str(row.get("display_name", "")),
                    "email": str(row.get("email", "")),
                    "activities": 0,
                    "scores": [],
                    "last_active": _iso(row.get("created_at")),
                }
            stats = student_stats[uid]
            stats["activities"] += 1
            if row.get("score") is not None:
                score = float(row["score"])
                stats["scores"].append(score)
                if row.get("topic"):
                    topic_scores[str(row["topic"])].append(score)
        students = []
        interventions = []
        for stats in student_stats.values():
            scores = stats.pop("scores")
            stats["average_score"] = round(sum(scores) / len(scores), 1) if scores else None
            students.append(stats)
            reasons = []
            if stats["average_score"] is not None and stats["average_score"] < 70:
                reasons.append("Average score below 70%")
            if stats["activities"] <= 1:
                reasons.append("Very limited learning activity")
            if reasons:
                interventions.append({**stats, "reasons": reasons})
        students.sort(key=lambda item: (item["average_score"] is None, item["average_score"] or 0))
        weak = [
            {"topic": topic, "average_score": round(sum(values) / len(values), 1), "attempts": len(values)}
            for topic, values in topic_scores.items() if values
        ]
        weak.sort(key=lambda item: item["average_score"])
        classes = self.classes_for_user(teacher_id, "teacher")
        insights = self._insights(rows)
        return {
            "role": "teacher",
            "summary": {
                "classes": len(classes),
                "students": sum(item["student_count"] for item in classes),
                "activities": len(rows),
                "average_score": round(sum(v for vals in topic_scores.values() for v in vals) / sum(len(vals) for vals in topic_scores.values()), 1) if topic_scores else None,
                "unanswered": len(insights["unanswered_questions"]),
                "interventions": len(interventions),
            },
            "classes": classes,
            "recent_activity": [self._activity_public(row) for row in rows[:20]],
            "weak_topics": weak[:10],
            "students": students[:200],
            "videos": self.list_available_videos(teacher_id, "teacher"),
            "usage": self._usage_summary(teacher_id=teacher_id),
            "interventions": interventions[:50],
            **insights,
        }


    def monthly_usage_cost(self, user_id: str) -> float:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd),0) AS cost FROM ai_tutor_usage_events WHERE user_id=%s AND created_at >= date_trunc('month', NOW())",
                    (user_id,),
                )
                row = cur.fetchone()
                return float(row["cost"] or 0)
        month = _utcnow().strftime("%Y-%m-01")
        with self._lock, self._sqlite() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd),0) AS cost FROM ai_tutor_usage_events WHERE user_id=? AND created_at>=?",
                (user_id, month),
            ).fetchone()
            return float(row["cost"] or 0)

    def monthly_video_count(self, user_id: str) -> int:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS total FROM ai_tutor_video_jobs WHERE user_id=%s AND created_at >= date_trunc('month', NOW())",
                    (user_id,),
                )
                row = cur.fetchone()
                return int(row["total"] or 0)
        month = _utcnow().strftime("%Y-%m-01")
        with self._lock, self._sqlite() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM ai_tutor_video_jobs WHERE user_id=? AND created_at>=?",
                (user_id, month),
            ).fetchone()
            return int(row["total"] or 0)

