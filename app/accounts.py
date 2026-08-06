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
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
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
                    recommended_readings JSONB NOT NULL DEFAULT '[]'::jsonb,
                    tutor_instructions TEXT NOT NULL DEFAULT '',
                    practice_whiteboard_required BOOLEAN NOT NULL DEFAULT FALSE,
                    practice_response_mode TEXT NOT NULL DEFAULT 'student_choice',
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
                "ALTER TABLE ai_tutor_users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
                "ALTER TABLE ai_tutor_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS recommended_readings JSONB NOT NULL DEFAULT '[]'::jsonb",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS tutor_instructions TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS practice_whiteboard_required BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE ai_tutor_classes ADD COLUMN IF NOT EXISTS practice_response_mode TEXT NOT NULL DEFAULT 'student_choice'",
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
            display_name TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_login TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_classes (
            id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL, name TEXT NOT NULL, subject TEXT NOT NULL DEFAULT '',
            join_code TEXT UNIQUE NOT NULL, knowledge_mode TEXT NOT NULL DEFAULT 'course_only',
            learning_outcomes TEXT NOT NULL DEFAULT '[]', weekly_topics TEXT NOT NULL DEFAULT '[]',
            recommended_readings TEXT NOT NULL DEFAULT '[]', tutor_instructions TEXT NOT NULL DEFAULT '',
            practice_whiteboard_required INTEGER NOT NULL DEFAULT 0, practice_response_mode TEXT NOT NULL DEFAULT 'student_choice', created_at TEXT NOT NULL,
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
                "recommended_readings": "TEXT NOT NULL DEFAULT '[]'",
                "tutor_instructions": "TEXT NOT NULL DEFAULT ''",
                "practice_whiteboard_required": "INTEGER NOT NULL DEFAULT 0",
                "practice_response_mode": "TEXT NOT NULL DEFAULT 'student_choice'",
            }
            for column, definition in migrations.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE ai_tutor_classes ADD COLUMN {column} {definition}")
            user_existing = {row[1] for row in conn.execute("PRAGMA table_info(ai_tutor_users)").fetchall()}
            if "active" not in user_existing:
                conn.execute("ALTER TABLE ai_tutor_users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
            if "must_change_password" not in user_existing:
                conn.execute("ALTER TABLE ai_tutor_users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    @staticmethod
    def public_user(row: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "email": str(row["email"]),
            "display_name": str(row["display_name"]),
            "role": str(row["role"]),
            "active": bool(row.get("active", True) if isinstance(row, dict) else row["active"]),
            "must_change_password": bool(row.get("must_change_password", False) if isinstance(row, dict) else row["must_change_password"]),
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

    def create_user(
        self, *, email: str, password_hash: str, display_name: str, role: str,
        active: bool = True, must_change_password: bool = False
    ) -> dict[str, Any]:
        user_id = str(uuid.uuid4())
        email = email.strip().lower()
        display_name = " ".join(display_name.split())[:100]
        now = _utcnow()
        try:
            if self._use_postgres:
                with self._pg() as conn, conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO ai_tutor_users(id,email,password_hash,display_name,role,active,must_change_password,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (user_id, email, password_hash, display_name, role, active, must_change_password, now),
                    )
                    row = dict(cur.fetchone())
                    conn.commit()
                    return row
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    "INSERT INTO ai_tutor_users(id,email,password_hash,display_name,role,active,must_change_password,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (user_id, email, password_hash, display_name, role, int(active), int(must_change_password), now.isoformat()),
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

    def list_users(self, *, role: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if role:
            where = " WHERE role={placeholder}"
            params = (role,)
        sql = f"SELECT * FROM ai_tutor_users{{where}} ORDER BY created_at DESC LIMIT {{limit_placeholder}}"
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql.format(where=where.format(placeholder="%s") if where else "", limit_placeholder="%s"), (*params, limit))
                return [self.public_user(dict(row)) for row in cur.fetchall()]
        with self._lock, self._sqlite() as conn:
            rows = conn.execute(sql.format(where=where.format(placeholder="?") if where else "", limit_placeholder="?"), (*params, limit)).fetchall()
            return [self.public_user(row) for row in rows]

    def set_user_active(self, *, user_id: str, active: bool) -> dict[str, Any]:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("UPDATE ai_tutor_users SET active=%s WHERE id=%s RETURNING *", (active, user_id))
                row = cur.fetchone()
                conn.commit()
                if not row:
                    raise ValueError("Account not found.")
                return dict(row)
        with self._lock, self._sqlite() as conn:
            cur = conn.execute("UPDATE ai_tutor_users SET active=? WHERE id=?", (int(active), user_id))
            if cur.rowcount == 0:
                raise ValueError("Account not found.")
            conn.commit()
        return self.get_user(user_id) or {}

    def update_password(self, *, user_id: str, password_hash: str, must_change_password: bool = False) -> None:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_tutor_users SET password_hash=%s,must_change_password=%s WHERE id=%s",
                    (password_hash, must_change_password, user_id),
                )
                if cur.rowcount == 0:
                    raise ValueError("Account not found.")
                conn.commit()
            return
        with self._lock, self._sqlite() as conn:
            cur = conn.execute(
                "UPDATE ai_tutor_users SET password_hash=?,must_change_password=? WHERE id=?",
                (password_hash, int(must_change_password), user_id),
            )
            if cur.rowcount == 0:
                raise ValueError("Account not found.")
            conn.commit()

    def regenerate_join_code(self, *, class_id: str, teacher_id: str) -> dict[str, Any]:
        for _ in range(8):
            join_code = self._new_join_code()
            try:
                if self._use_postgres:
                    with self._pg() as conn, conn.cursor() as cur:
                        cur.execute(
                            "UPDATE ai_tutor_classes SET join_code=%s WHERE id=%s AND teacher_id=%s",
                            (join_code, class_id, teacher_id),
                        )
                        if cur.rowcount == 0:
                            raise ValueError("Class not found or you do not manage it.")
                        conn.commit()
                else:
                    with self._lock, self._sqlite() as conn:
                        cur = conn.execute(
                            "UPDATE ai_tutor_classes SET join_code=? WHERE id=? AND teacher_id=?",
                            (join_code, class_id, teacher_id),
                        )
                        if cur.rowcount == 0:
                            raise ValueError("Class not found or you do not manage it.")
                        conn.commit()
                return self.get_class(class_id) or {}
            except ValueError:
                raise
            except Exception as exc:
                if "unique" not in str(exc).lower() and "join_code" not in str(exc).lower():
                    raise
        raise RuntimeError("A new enrolment code could not be generated.")

    def merge_course_outline(
        self, *, class_id: str, teacher_id: str, objectives: list[str], recommended_readings: list[str],
        weekly_topics: list[str] | None = None
    ) -> dict[str, Any]:
        classroom = self.class_for_user(class_id=class_id, user_id=teacher_id, role="teacher")
        if not classroom:
            raise ValueError("Class not found or you do not manage it.")
        merged_objectives = list(dict.fromkeys([
            *[str(item).strip() for item in classroom.get("learning_outcomes", []) if str(item).strip()],
            *[str(item).strip() for item in objectives if str(item).strip()],
        ]))[:30]
        merged_readings = list(dict.fromkeys([
            *[str(item).strip() for item in classroom.get("recommended_readings", []) if str(item).strip()],
            *[str(item).strip() for item in recommended_readings if str(item).strip()],
        ]))[:60]
        merged_weeks = list(dict.fromkeys([
            *[str(item).strip() for item in classroom.get("weekly_topics", []) if str(item).strip()],
            *[str(item).strip() for item in (weekly_topics or []) if str(item).strip()],
        ]))[:40]
        return self.update_class_profile(
            class_id=class_id,
            teacher_id=teacher_id,
            name=str(classroom.get("name", "")),
            subject=str(classroom.get("subject", "")),
            knowledge_mode=str(classroom.get("knowledge_mode", "course_only")),
            learning_outcomes=merged_objectives,
            weekly_topics=merged_weeks,
            recommended_readings=merged_readings,
            tutor_instructions=str(classroom.get("tutor_instructions", "")),
            practice_whiteboard_required=bool(classroom.get("practice_whiteboard_required", False)),
            practice_response_mode=str(classroom.get("practice_response_mode", "student_choice")),
        )

    def _new_join_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(7))

    def create_class(
        self, *, teacher_id: str, name: str, subject: str, knowledge_mode: str = "course_only",
        learning_outcomes: list[str] | None = None, weekly_topics: list[str] | None = None,
        recommended_readings: list[str] | None = None, tutor_instructions: str = "",
        practice_whiteboard_required: bool = False, practice_response_mode: str = "student_choice"
    ) -> dict[str, Any]:
        class_id = str(uuid.uuid4())
        now = _utcnow()
        knowledge_mode = knowledge_mode if knowledge_mode in {"course_only", "course_plus_approved", "general"} else "course_only"
        outcomes = [str(item).strip()[:300] for item in (learning_outcomes or []) if str(item).strip()][:30]
        weeks = [str(item).strip()[:300] for item in (weekly_topics or []) if str(item).strip()][:40]
        readings = [str(item).strip()[:500] for item in (recommended_readings or []) if str(item).strip()][:60]
        tutor_instructions = tutor_instructions.strip()[:5000]
        practice_response_mode = practice_response_mode if practice_response_mode in {"student_choice", "typed", "voice", "whiteboard"} else "student_choice"
        if practice_whiteboard_required:
            practice_response_mode = "whiteboard"
        practice_whiteboard_required = practice_response_mode == "whiteboard"
        for _ in range(6):
            join_code = self._new_join_code()
            try:
                if self._use_postgres:
                    with self._pg() as conn, conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO ai_tutor_classes(
                                id,teacher_id,name,subject,join_code,knowledge_mode,learning_outcomes,weekly_topics,recommended_readings,tutor_instructions,practice_whiteboard_required,practice_response_mode,created_at
                            ) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s)""",
                            (class_id, teacher_id, name.strip()[:140], subject.strip()[:160], join_code, knowledge_mode, _json(outcomes), _json(weeks), _json(readings), tutor_instructions, practice_whiteboard_required, practice_response_mode, now),
                        )
                        conn.commit()
                else:
                    with self._lock, self._sqlite() as conn:
                        conn.execute(
                            """INSERT INTO ai_tutor_classes(
                                id,teacher_id,name,subject,join_code,knowledge_mode,learning_outcomes,weekly_topics,recommended_readings,tutor_instructions,practice_whiteboard_required,practice_response_mode,created_at
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (class_id, teacher_id, name.strip()[:140], subject.strip()[:160], join_code, knowledge_mode, _json(outcomes), _json(weeks), _json(readings), tutor_instructions, int(practice_whiteboard_required), practice_response_mode, now.isoformat()),
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
            "teacher_id": str(row.get("teacher_id", "")),
            "knowledge_mode": str(row.get("knowledge_mode", "course_only") or "course_only"),
            "learning_outcomes": _safe_json(row.get("learning_outcomes"), []),
            "weekly_topics": _safe_json(row.get("weekly_topics"), []),
            "recommended_readings": _safe_json(row.get("recommended_readings"), []),
            "tutor_instructions": str(row.get("tutor_instructions", "") or ""),
            "practice_whiteboard_required": bool(row.get("practice_whiteboard_required", False)),
            "practice_response_mode": str(row.get("practice_response_mode", "student_choice") or "student_choice"),
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
        learning_outcomes: list[str], weekly_topics: list[str], recommended_readings: list[str],
        tutor_instructions: str, practice_whiteboard_required: bool, practice_response_mode: str = "student_choice"
    ) -> dict[str, Any]:
        knowledge_mode = knowledge_mode if knowledge_mode in {"course_only", "course_plus_approved", "general"} else "course_only"
        outcomes = [str(item).strip()[:300] for item in learning_outcomes if str(item).strip()][:30]
        weeks = [str(item).strip()[:300] for item in weekly_topics if str(item).strip()][:40]
        readings = [str(item).strip()[:500] for item in recommended_readings if str(item).strip()][:60]
        practice_response_mode = practice_response_mode if practice_response_mode in {"student_choice", "typed", "voice", "whiteboard"} else "student_choice"
        if practice_whiteboard_required:
            practice_response_mode = "whiteboard"
        practice_whiteboard_required = practice_response_mode == "whiteboard"
        values = (name.strip()[:140], subject.strip()[:160], knowledge_mode, _json(outcomes), _json(weeks), _json(readings), tutor_instructions.strip()[:5000], practice_whiteboard_required, practice_response_mode)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE ai_tutor_classes SET name=%s,subject=%s,knowledge_mode=%s,learning_outcomes=%s::jsonb,weekly_topics=%s::jsonb,recommended_readings=%s::jsonb,tutor_instructions=%s,practice_whiteboard_required=%s,practice_response_mode=%s
                       WHERE id=%s AND teacher_id=%s""",
                    (*values, class_id, teacher_id),
                )
                if cur.rowcount == 0:
                    raise ValueError("Class not found or you do not manage it.")
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                cur = conn.execute(
                    """UPDATE ai_tutor_classes SET name=?,subject=?,knowledge_mode=?,learning_outcomes=?,weekly_topics=?,recommended_readings=?,tutor_instructions=?,practice_whiteboard_required=?,practice_response_mode=?
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
        if role == "admin":
            sql = """
            SELECT c.*, u.display_name AS teacher_name,
                   (SELECT COUNT(*) FROM ai_tutor_class_members m WHERE m.class_id=c.id) AS student_count
            FROM ai_tutor_classes c JOIN ai_tutor_users u ON u.id=c.teacher_id
            ORDER BY c.created_at DESC
            """
        elif role == "teacher":
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
                if role == "admin":
                    cur.execute(sql)
                else:
                    cur.execute(sql.format(placeholder="%s"), (user_id,))
                return [self._class_public(dict(row)) for row in cur.fetchall()]
        with self._lock, self._sqlite() as conn:
            rows = conn.execute(sql if role == "admin" else sql.format(placeholder="?"), () if role == "admin" else (user_id,)).fetchall()
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

    def chat_history(self, *, session_id: str, user_id: str, limit: int = 24) -> list[dict[str, str]]:
        """Return a learner's recent messages for one course-scoped conversation."""
        limit = max(2, min(int(limit), 100))
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT m.role,m.content FROM ai_tutor_chat_messages m
                    JOIN ai_tutor_chat_sessions s ON s.id=m.session_id
                    WHERE m.session_id=%s AND s.user_id=%s
                    ORDER BY m.created_at DESC LIMIT %s
                    """,
                    (session_id, user_id, limit),
                )
                rows = [dict(row) for row in cur.fetchall()]
        else:
            with self._lock, self._sqlite() as conn:
                rows = [dict(row) for row in conn.execute(
                    """
                    SELECT m.role,m.content FROM ai_tutor_chat_messages m
                    JOIN ai_tutor_chat_sessions s ON s.id=m.session_id
                    WHERE m.session_id=? AND s.user_id=?
                    ORDER BY m.created_at DESC LIMIT ?
                    """,
                    (session_id, user_id, limit),
                ).fetchall()]
        rows.reverse()
        return [
            {"role": str(row.get("role", "")), "content": str(row.get("content", ""))}
            for row in rows if str(row.get("role", "")) in {"user", "assistant"}
        ]

    def delete_chat_session(self, *, session_id: str, user_id: str) -> bool:
        """Delete one authenticated learner's persisted course conversation and its messages."""
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_tutor_chat_sessions WHERE id=%s AND user_id=%s",
                    (session_id, user_id),
                )
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
        with self._lock, self._sqlite() as conn:
            cur = conn.execute(
                "DELETE FROM ai_tutor_chat_sessions WHERE id=? AND user_id=?",
                (session_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0

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
        if role == "admin":
            return self._admin_dashboard(user_id)
        return self._teacher_dashboard(user_id) if role == "teacher" else self._student_dashboard(user_id)

    def _event_rows(self, *, user_id: str | None = None, teacher_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        if teacher_id:
            sql = """
            SELECT e.*, u.display_name, u.email, c.name AS class_name
            FROM ai_tutor_learning_events e
            JOIN ai_tutor_users u ON u.id=e.user_id
            JOIN ai_tutor_class_members m ON m.student_id=e.user_id AND m.class_id=e.class_id
            JOIN ai_tutor_classes c ON c.id=e.class_id AND c.teacher_id={placeholder}
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

    def _teacher_roster(self, teacher_id: str) -> list[dict[str, Any]]:
        sql = """
        SELECT u.id, u.display_name, u.email, c.id AS class_id, c.name AS class_name,
               MAX(e.created_at) AS last_active, COUNT(e.id) AS activities
        FROM ai_tutor_classes c
        JOIN ai_tutor_class_members m ON m.class_id=c.id
        JOIN ai_tutor_users u ON u.id=m.student_id
        LEFT JOIN ai_tutor_learning_events e ON e.user_id=u.id AND e.class_id=c.id
        WHERE c.teacher_id={placeholder}
        GROUP BY u.id,u.display_name,u.email,c.id,c.name
        ORDER BY u.display_name,c.name
        """
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql.format(placeholder="%s"), (teacher_id,))
                rows = [dict(row) for row in cur.fetchall()]
        else:
            with self._lock, self._sqlite() as conn:
                rows = [dict(row) for row in conn.execute(sql.format(placeholder="?"), (teacher_id,)).fetchall()]
        return [{
            "id": str(row.get("id", "")), "display_name": str(row.get("display_name", "")),
            "email": str(row.get("email", "")), "class_id": str(row.get("class_id", "")),
            "class_name": str(row.get("class_name", "")), "last_active": _iso(row.get("last_active")),
            "activities": int(row.get("activities", 0) or 0),
        } for row in rows]

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
        today = _utcnow().date()
        activity_dates: set[Any] = set()
        for row in rows:
            value = row.get("created_at")
            try:
                stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                activity_dates.add(stamp.astimezone(timezone.utc).date())
            except (TypeError, ValueError):
                continue
        weekly_activities = sum(1 for row in rows if _iso(row.get("created_at"))[:10] >= (today - timedelta(days=6)).isoformat())
        streak = 0
        cursor = today if today in activity_dates else today - timedelta(days=1)
        while cursor in activity_dates:
            streak += 1
            cursor -= timedelta(days=1)
        return {
            "role": "student",
            "summary": {
                "activities": len(rows),
                "practice_completed": sum(row.get("event_type") == "practice_completed" for row in rows),
                "average_score": round(sum(scored) / len(scored), 1) if scored else None,
                "classes": len(self.classes_for_user(user_id, "student")),
                "weekly_activities": weekly_activities,
                "learning_streak_days": streak,
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
        roster = self._teacher_roster(teacher_id)
        for member in roster:
            uid = str(member.get("id", ""))
            current = student_stats.setdefault(uid, {
                "id": uid, "display_name": str(member.get("display_name", "")),
                "email": str(member.get("email", "")), "activities": 0, "scores": [],
                "last_active": str(member.get("last_active", "")), "classes": [],
            })
            current["classes"].append({"id": member.get("class_id", ""), "name": member.get("class_name", "")})
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
            if stats["activities"] == 0:
                reasons.append("No learning activity recorded")
            elif stats["activities"] <= 1:
                reasons.append("Very limited learning activity")
            last_active_text = str(stats.get("last_active") or "")
            if last_active_text:
                try:
                    last_active = datetime.fromisoformat(last_active_text.replace("Z", "+00:00"))
                    if (_utcnow() - last_active.astimezone(timezone.utc)).days >= 14:
                        reasons.append("No activity during the past 14 days")
                except ValueError:
                    pass
            if reasons:
                action = "Contact the student and assign a short diagnostic or remedial activity." if any("No " in reason for reason in reasons) else "Review weak outcomes and assign a remedial mini-lesson followed by reassessment."
                interventions.append({**stats, "reasons": reasons, "recommended_action": action})
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


    def _admin_dashboard(self, admin_id: str) -> dict[str, Any]:
        lecturers = self.list_users(role="teacher", limit=2000)
        students = self.list_users(role="student", limit=5000)
        classes = self.classes_for_user(admin_id, "admin")
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT provider, model, SUM(input_tokens) AS input_tokens,
                              SUM(output_tokens) AS output_tokens, SUM(estimated_cost_usd) AS cost
                       FROM ai_tutor_usage_events GROUP BY provider, model ORDER BY cost DESC"""
                )
                rows = [dict(row) for row in cur.fetchall()]
        else:
            with self._lock, self._sqlite() as conn:
                rows = [dict(row) for row in conn.execute(
                    """SELECT provider, model, SUM(input_tokens) AS input_tokens,
                              SUM(output_tokens) AS output_tokens, SUM(estimated_cost_usd) AS cost
                       FROM ai_tutor_usage_events GROUP BY provider, model ORDER BY cost DESC"""
                ).fetchall()]
        usage = [{
            "provider": str(row.get("provider", "")),
            "model": str(row.get("model", "")),
            "input_tokens": int(row.get("input_tokens", 0) or 0),
            "output_tokens": int(row.get("output_tokens", 0) or 0),
            "estimated_cost_usd": round(float(row.get("cost", 0) or 0), 6),
        } for row in rows]
        return {
            "role": "admin",
            "summary": {
                "lecturers": len(lecturers),
                "active_lecturers": sum(bool(item.get("active")) for item in lecturers),
                "students": len(students),
                "courses": len(classes),
                "enrolments": sum(int(item.get("student_count", 0) or 0) for item in classes),
            },
            "classes": classes,
            "recent_activity": [],
            "weak_topics": [],
            "students": students[:500],
            "lecturers": lecturers,
            "videos": [],
            "usage": usage,
            "outcome_mastery": [],
            "common_misconceptions": [],
            "unanswered_questions": [],
            "interventions": [],
            "popular_questions": [],
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

