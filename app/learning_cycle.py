from __future__ import annotations

import json
import sqlite3
import threading
import uuid
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


def mastery_status(score: float, evidence_count: int = 1) -> str:
    if evidence_count <= 0:
        return "not_started"
    if score < 40:
        return "needs_foundation"
    if score < 60:
        return "developing"
    if score < 80:
        return "competent"
    return "mastered"


class LearningCycleStore:
    """Persistent diagnostic, assessment, mastery, revision and study-note records.

    This is intentionally separate from AccountStore so it can upgrade an existing v5
    database without changing account or course ownership semantics.
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
                CREATE TABLE IF NOT EXISTS ai_tutor_course_policies (
                    class_id TEXT PRIMARY KEY REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
                    diagnostics_required BOOLEAN NOT NULL DEFAULT TRUE,
                    spaced_revision_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    mastery_pass_mark INTEGER NOT NULL DEFAULT 70,
                    direct_answers_allowed BOOLEAN NOT NULL DEFAULT TRUE,
                    hints_allowed BOOLEAN NOT NULL DEFAULT TRUE,
                    assignment_help_mode TEXT NOT NULL DEFAULT 'guided',
                    integrity_mode TEXT NOT NULL DEFAULT 'learning',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_assessments (
                    id TEXT PRIMARY KEY,
                    class_id TEXT NOT NULL REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
                    teacher_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    assessment_type TEXT NOT NULL,
                    topic TEXT NOT NULL DEFAULT '',
                    learning_outcome TEXT NOT NULL DEFAULT '',
                    instructions TEXT NOT NULL DEFAULT '',
                    questions JSONB NOT NULL DEFAULT '[]'::jsonb,
                    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status TEXT NOT NULL DEFAULT 'draft',
                    due_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_assessment_attempts (
                    id TEXT PRIMARY KEY,
                    assessment_id TEXT NOT NULL REFERENCES ai_tutor_assessments(id) ON DELETE CASCADE,
                    student_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    responses JSONB NOT NULL DEFAULT '[]'::jsonb,
                    score DOUBLE PRECISION,
                    feedback JSONB NOT NULL DEFAULT '{}'::jsonb,
                    completed BOOLEAN NOT NULL DEFAULT FALSE,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    submitted_at TIMESTAMPTZ
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_mastery_records (
                    student_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    class_id TEXT NOT NULL REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
                    mastery_key TEXT NOT NULL,
                    learning_outcome TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    mastery_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'not_started',
                    last_evidence_at TIMESTAMPTZ,
                    next_review_at TIMESTAMPTZ,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    PRIMARY KEY(student_id, class_id, mastery_key)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_revision_items (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    class_id TEXT NOT NULL REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
                    mastery_key TEXT NOT NULL,
                    learning_outcome TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    due_at TIMESTAMPTZ NOT NULL,
                    interval_days INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'due',
                    source_event TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS ai_tutor_student_notes (
                    id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
                    class_id TEXT REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL DEFAULT '',
                    note_type TEXT NOT NULL DEFAULT 'note',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_assessments_class_status ON ai_tutor_assessments(class_id,status,created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_attempts_student ON ai_tutor_assessment_attempts(student_id,submitted_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_revision_due ON ai_tutor_revision_items(student_id,status,due_at)",
                "CREATE INDEX IF NOT EXISTS idx_ai_tutor_notes_student ON ai_tutor_student_notes(student_id,class_id,updated_at DESC)",
            ]
            with self._pg() as conn, conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
                conn.commit()
            return

        schema = """
        CREATE TABLE IF NOT EXISTS ai_tutor_course_policies (
            class_id TEXT PRIMARY KEY, diagnostics_required INTEGER NOT NULL DEFAULT 1,
            spaced_revision_enabled INTEGER NOT NULL DEFAULT 1, mastery_pass_mark INTEGER NOT NULL DEFAULT 70,
            direct_answers_allowed INTEGER NOT NULL DEFAULT 1, hints_allowed INTEGER NOT NULL DEFAULT 1,
            assignment_help_mode TEXT NOT NULL DEFAULT 'guided', integrity_mode TEXT NOT NULL DEFAULT 'learning',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_assessments (
            id TEXT PRIMARY KEY, class_id TEXT NOT NULL, teacher_id TEXT NOT NULL, title TEXT NOT NULL,
            assessment_type TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '', learning_outcome TEXT NOT NULL DEFAULT '',
            instructions TEXT NOT NULL DEFAULT '', questions TEXT NOT NULL DEFAULT '[]', settings TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'draft', due_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE CASCADE,
            FOREIGN KEY(teacher_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_assessment_attempts (
            id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL, student_id TEXT NOT NULL,
            responses TEXT NOT NULL DEFAULT '[]', score REAL, feedback TEXT NOT NULL DEFAULT '{}',
            completed INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL, submitted_at TEXT,
            FOREIGN KEY(assessment_id) REFERENCES ai_tutor_assessments(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_mastery_records (
            student_id TEXT NOT NULL, class_id TEXT NOT NULL, mastery_key TEXT NOT NULL,
            learning_outcome TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT '', mastery_score REAL NOT NULL DEFAULT 0,
            evidence_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'not_started',
            last_evidence_at TEXT, next_review_at TEXT, metadata TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(student_id,class_id,mastery_key),
            FOREIGN KEY(student_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_revision_items (
            id TEXT PRIMARY KEY, student_id TEXT NOT NULL, class_id TEXT NOT NULL, mastery_key TEXT NOT NULL,
            learning_outcome TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT '', due_at TEXT NOT NULL,
            interval_days INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'due', source_event TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, completed_at TEXT,
            FOREIGN KEY(student_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS ai_tutor_student_notes (
            id TEXT PRIMARY KEY, student_id TEXT NOT NULL, class_id TEXT, section_id TEXT NOT NULL DEFAULT '',
            note_type TEXT NOT NULL DEFAULT 'note', title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES ai_tutor_users(id) ON DELETE CASCADE,
            FOREIGN KEY(class_id) REFERENCES ai_tutor_classes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_assessments_class_status ON ai_tutor_assessments(class_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_attempts_student ON ai_tutor_assessment_attempts(student_id,submitted_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_revision_due ON ai_tutor_revision_items(student_id,status,due_at);
        CREATE INDEX IF NOT EXISTS idx_ai_tutor_notes_student ON ai_tutor_student_notes(student_id,class_id,updated_at DESC);
        """
        with self._lock, self._sqlite() as conn:
            conn.executescript(schema)
            conn.commit()

    def ensure_policy(self, class_id: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        values = values or {}
        now = _utcnow()
        policy = {
            "diagnostics_required": bool(values.get("diagnostics_required", True)),
            "spaced_revision_enabled": bool(values.get("spaced_revision_enabled", True)),
            "mastery_pass_mark": max(40, min(95, int(values.get("mastery_pass_mark", 70) or 70))),
            "direct_answers_allowed": bool(values.get("direct_answers_allowed", True)),
            "hints_allowed": bool(values.get("hints_allowed", True)),
            "assignment_help_mode": str(values.get("assignment_help_mode", "guided")) if str(values.get("assignment_help_mode", "guided")) in {"teach_only", "guided", "allowed"} else "guided",
            "integrity_mode": str(values.get("integrity_mode", "learning")) if str(values.get("integrity_mode", "learning")) in {"learning", "hint_only", "assessment_restricted"} else "learning",
        }
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ai_tutor_course_policies(class_id,diagnostics_required,spaced_revision_enabled,mastery_pass_mark,direct_answers_allowed,hints_allowed,assignment_help_mode,integrity_mode,updated_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(class_id) DO UPDATE SET diagnostics_required=EXCLUDED.diagnostics_required,spaced_revision_enabled=EXCLUDED.spaced_revision_enabled,mastery_pass_mark=EXCLUDED.mastery_pass_mark,direct_answers_allowed=EXCLUDED.direct_answers_allowed,hints_allowed=EXCLUDED.hints_allowed,assignment_help_mode=EXCLUDED.assignment_help_mode,integrity_mode=EXCLUDED.integrity_mode,updated_at=EXCLUDED.updated_at""",
                    (class_id, policy["diagnostics_required"], policy["spaced_revision_enabled"], policy["mastery_pass_mark"], policy["direct_answers_allowed"], policy["hints_allowed"], policy["assignment_help_mode"], policy["integrity_mode"], now),
                )
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    """INSERT INTO ai_tutor_course_policies(class_id,diagnostics_required,spaced_revision_enabled,mastery_pass_mark,direct_answers_allowed,hints_allowed,assignment_help_mode,integrity_mode,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(class_id) DO UPDATE SET diagnostics_required=excluded.diagnostics_required,spaced_revision_enabled=excluded.spaced_revision_enabled,mastery_pass_mark=excluded.mastery_pass_mark,direct_answers_allowed=excluded.direct_answers_allowed,hints_allowed=excluded.hints_allowed,assignment_help_mode=excluded.assignment_help_mode,integrity_mode=excluded.integrity_mode,updated_at=excluded.updated_at""",
                    (class_id, int(policy["diagnostics_required"]), int(policy["spaced_revision_enabled"]), policy["mastery_pass_mark"], int(policy["direct_answers_allowed"]), int(policy["hints_allowed"]), policy["assignment_help_mode"], policy["integrity_mode"], now.isoformat()),
                )
                conn.commit()
        return self.policy(class_id)

    def policy(self, class_id: str) -> dict[str, Any]:
        row = None
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_course_policies WHERE class_id=%s", (class_id,))
                row = cur.fetchone()
        else:
            with self._lock, self._sqlite() as conn:
                row = conn.execute("SELECT * FROM ai_tutor_course_policies WHERE class_id=?", (class_id,)).fetchone()
        if not row:
            return self.ensure_policy(class_id, {})
        data = dict(row)
        return {
            "diagnostics_required": bool(data.get("diagnostics_required", True)),
            "spaced_revision_enabled": bool(data.get("spaced_revision_enabled", True)),
            "mastery_pass_mark": int(data.get("mastery_pass_mark", 70) or 70),
            "direct_answers_allowed": bool(data.get("direct_answers_allowed", True)),
            "hints_allowed": bool(data.get("hints_allowed", True)),
            "assignment_help_mode": str(data.get("assignment_help_mode", "guided")),
            "integrity_mode": str(data.get("integrity_mode", "learning")),
        }

    @staticmethod
    def assessment_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row.get("id", "")),
            "class_id": str(row.get("class_id", "")),
            "teacher_id": str(row.get("teacher_id", "")),
            "title": str(row.get("title", "")),
            "assessment_type": str(row.get("assessment_type", "practice")),
            "topic": str(row.get("topic", "")),
            "learning_outcome": str(row.get("learning_outcome", "")),
            "instructions": str(row.get("instructions", "")),
            "questions": _safe_json(row.get("questions"), []),
            "settings": _safe_json(row.get("settings"), {}),
            "status": str(row.get("status", "draft")),
            "due_at": _iso(row.get("due_at")),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
        }

    def create_assessment(self, *, class_id: str, teacher_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        assessment_id = str(uuid.uuid4())
        now = _utcnow()
        assessment_type = str(payload.get("assessment_type", "practice"))
        if assessment_type not in {"diagnostic", "practice", "quiz", "assignment", "mastery_check"}:
            assessment_type = "practice"
        status = str(payload.get("status", "draft"))
        if status not in {"draft", "published", "closed"}:
            status = "draft"
        questions = list(payload.get("questions") or [])[:40]
        settings = dict(payload.get("settings") or {})
        values = (
            assessment_id, class_id, teacher_id, str(payload.get("title") or "Assessment")[:180], assessment_type,
            str(payload.get("topic") or "")[:220], str(payload.get("learning_outcome") or "")[:500],
            str(payload.get("instructions") or "")[:4000], _json(questions), _json(settings), status,
            payload.get("due_at") or None, now,
        )
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ai_tutor_assessments(id,class_id,teacher_id,title,assessment_type,topic,learning_outcome,instructions,questions,settings,status,due_at,created_at,updated_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)""",
                    (*values, now),
                )
                conn.commit()
        else:
            sqlite_values = list(values)
            sqlite_values[-1] = now.isoformat()
            due_index = 11
            if sqlite_values[due_index] and isinstance(sqlite_values[due_index], datetime):
                sqlite_values[due_index] = sqlite_values[due_index].isoformat()
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    """INSERT INTO ai_tutor_assessments(id,class_id,teacher_id,title,assessment_type,topic,learning_outcome,instructions,questions,settings,status,due_at,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*sqlite_values, now.isoformat()),
                )
                conn.commit()
        return self.get_assessment(assessment_id) or {}

    def get_assessment(self, assessment_id: str) -> dict[str, Any] | None:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_assessments WHERE id=%s", (assessment_id,))
                row = cur.fetchone()
        else:
            with self._lock, self._sqlite() as conn:
                row = conn.execute("SELECT * FROM ai_tutor_assessments WHERE id=?", (assessment_id,)).fetchone()
        return self.assessment_public(dict(row)) if row else None

    def list_assessments(self, class_id: str, *, include_drafts: bool = False) -> list[dict[str, Any]]:
        clause = "class_id=%s" if self._use_postgres else "class_id=?"
        params: list[Any] = [class_id]
        if not include_drafts:
            clause += " AND status='published'"
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(f"SELECT * FROM ai_tutor_assessments WHERE {clause} ORDER BY created_at DESC", tuple(params))
                rows = cur.fetchall()
        else:
            with self._lock, self._sqlite() as conn:
                rows = conn.execute(f"SELECT * FROM ai_tutor_assessments WHERE {clause} ORDER BY created_at DESC", tuple(params)).fetchall()
        return [self.assessment_public(dict(row)) for row in rows]

    def update_assessment(self, assessment_id: str, teacher_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_assessment(assessment_id)
        if not existing or existing["teacher_id"] != teacher_id:
            raise ValueError("Assessment not found.")
        merged = {**existing, **payload}
        now = _utcnow()
        status = str(merged.get("status", "draft"))
        if status not in {"draft", "published", "closed"}:
            status = "draft"
        values = (
            str(merged.get("title") or "Assessment")[:180], str(merged.get("assessment_type") or "practice"),
            str(merged.get("topic") or "")[:220], str(merged.get("learning_outcome") or "")[:500],
            str(merged.get("instructions") or "")[:4000], _json(list(merged.get("questions") or [])[:40]),
            _json(dict(merged.get("settings") or {})), status, merged.get("due_at") or None, now,
        )
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE ai_tutor_assessments SET title=%s,assessment_type=%s,topic=%s,learning_outcome=%s,instructions=%s,questions=%s::jsonb,settings=%s::jsonb,status=%s,due_at=%s,updated_at=%s WHERE id=%s AND teacher_id=%s""",
                    (*values, assessment_id, teacher_id),
                )
                conn.commit()
        else:
            sqlite_values = [v.isoformat() if isinstance(v, datetime) else v for v in values]
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    """UPDATE ai_tutor_assessments SET title=?,assessment_type=?,topic=?,learning_outcome=?,instructions=?,questions=?,settings=?,status=?,due_at=?,updated_at=? WHERE id=? AND teacher_id=?""",
                    (*sqlite_values, assessment_id, teacher_id),
                )
                conn.commit()
        return self.get_assessment(assessment_id) or {}

    def delete_assessment(self, assessment_id: str, teacher_id: str) -> bool:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM ai_tutor_assessments WHERE id=%s AND teacher_id=%s", (assessment_id, teacher_id))
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
        with self._lock, self._sqlite() as conn:
            cur = conn.execute("DELETE FROM ai_tutor_assessments WHERE id=? AND teacher_id=?", (assessment_id, teacher_id))
            conn.commit()
            return cur.rowcount > 0

    def start_attempt(self, assessment_id: str, student_id: str) -> dict[str, Any]:
        assessment = self.get_assessment(assessment_id)
        if not assessment or assessment["status"] != "published":
            raise ValueError("Assessment is not available.")
        settings = assessment.get("settings") or {}
        if bool(settings.get("deadline_enforced", False)) and assessment.get("due_at"):
            try:
                due_at = datetime.fromisoformat(str(assessment["due_at"]).replace("Z", "+00:00"))
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)
                if _utcnow() > due_at.astimezone(timezone.utc):
                    raise ValueError("The assessment deadline has passed.")
            except ValueError as exc:
                if str(exc) == "The assessment deadline has passed.":
                    raise
        attempts_allowed = max(1, int(settings.get("attempts_allowed", 1) or 1))
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM ai_tutor_assessment_attempts WHERE assessment_id=%s AND student_id=%s AND completed=TRUE", (assessment_id, student_id))
                used = int(cur.fetchone()["n"] or 0)
        else:
            with self._lock, self._sqlite() as conn:
                used = int(conn.execute("SELECT COUNT(*) FROM ai_tutor_assessment_attempts WHERE assessment_id=? AND student_id=? AND completed=1", (assessment_id, student_id)).fetchone()[0])
        if used >= attempts_allowed:
            raise ValueError("No assessment attempts remain.")
        attempt_id = str(uuid.uuid4())
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO ai_tutor_assessment_attempts(id,assessment_id,student_id,started_at) VALUES(%s,%s,%s,%s)", (attempt_id, assessment_id, student_id, now))
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute("INSERT INTO ai_tutor_assessment_attempts(id,assessment_id,student_id,started_at) VALUES(?,?,?,?)", (attempt_id, assessment_id, student_id, now.isoformat()))
                conn.commit()
        return {"attempt_id": attempt_id, "assessment": assessment, "attempt_number": used + 1, "attempts_allowed": attempts_allowed}

    def complete_attempt(self, *, attempt_id: str, student_id: str, responses: list[dict[str, Any]], score: float, feedback: dict[str, Any]) -> dict[str, Any]:
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """UPDATE ai_tutor_assessment_attempts SET responses=%s::jsonb,score=%s,feedback=%s::jsonb,completed=TRUE,submitted_at=%s WHERE id=%s AND student_id=%s RETURNING *""",
                    (_json(responses), score, _json(feedback), now, attempt_id, student_id),
                )
                row = cur.fetchone()
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    "UPDATE ai_tutor_assessment_attempts SET responses=?,score=?,feedback=?,completed=1,submitted_at=? WHERE id=? AND student_id=?",
                    (_json(responses), score, _json(feedback), now.isoformat(), attempt_id, student_id),
                )
                row = conn.execute("SELECT * FROM ai_tutor_assessment_attempts WHERE id=? AND student_id=?", (attempt_id, student_id)).fetchone()
                conn.commit()
        if not row:
            raise ValueError("Assessment attempt not found.")
        data = dict(row)
        return {
            "id": str(data.get("id", "")), "assessment_id": str(data.get("assessment_id", "")),
            "student_id": str(data.get("student_id", "")), "responses": _safe_json(data.get("responses"), []),
            "score": float(data.get("score", 0) or 0), "feedback": _safe_json(data.get("feedback"), {}),
            "completed": bool(data.get("completed", False)), "started_at": _iso(data.get("started_at")),
            "submitted_at": _iso(data.get("submitted_at")),
        }

    def assessment_attempts(self, *, assessment_id: str | None = None, student_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        placeholder = "%s" if self._use_postgres else "?"
        if assessment_id:
            clauses.append(f"assessment_id={placeholder}")
            params.append(assessment_id)
        if student_id:
            clauses.append(f"student_id={placeholder}")
            params.append(student_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM ai_tutor_assessment_attempts{where} ORDER BY started_at DESC"
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        else:
            with self._lock, self._sqlite() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            result.append({
                "id": str(data.get("id", "")), "assessment_id": str(data.get("assessment_id", "")),
                "student_id": str(data.get("student_id", "")), "responses": _safe_json(data.get("responses"), []),
                "score": None if data.get("score") is None else float(data.get("score")),
                "feedback": _safe_json(data.get("feedback"), {}), "completed": bool(data.get("completed", False)),
                "started_at": _iso(data.get("started_at")), "submitted_at": _iso(data.get("submitted_at")),
            })
        return result

    @staticmethod
    def _key(outcome: str, topic: str) -> str:
        return (outcome.strip() or topic.strip() or "general")[:500]

    def update_mastery(
        self, *, student_id: str, class_id: str, score: float, outcome: str = "", topic: str = "",
        difficulty: str = "standard", attempts: int = 1, hints_used: int = 0, source: str = "",
        misconception: str = "", spaced_revision_enabled: bool = True,
    ) -> dict[str, Any]:
        key = self._key(outcome, topic)
        raw = max(0.0, min(100.0, float(score)))
        factor = {"foundation": 0.95, "standard": 1.0, "challenge": 1.05}.get(difficulty, 1.0)
        evidence = max(0.0, min(100.0, raw * factor - max(0, attempts - 1) * 3 - max(0, hints_used) * 4))
        existing = self.get_mastery(student_id, class_id, key)
        old_score = float(existing.get("mastery_score", 0) if existing else 0)
        old_count = int(existing.get("evidence_count", 0) if existing else 0)
        weight = min(old_count, 4)
        new_score = round((old_score * weight + evidence) / (weight + 1), 1)
        new_count = old_count + 1
        status = mastery_status(new_score, new_count)
        now = _utcnow()
        interval = 1 if new_score < 40 else 3 if new_score < 60 else 7 if new_score < 80 else 21
        next_review = now + timedelta(days=interval)
        metadata = dict(existing.get("metadata", {}) if existing else {})
        history = list(metadata.get("recent_evidence", []))[-5:]
        history.append({"score": raw, "adjusted_score": round(evidence, 1), "source": source, "at": now.isoformat(), "misconception": misconception[:500]})
        metadata.update({"recent_evidence": history, "last_source": source, "last_misconception": misconception[:500]})
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ai_tutor_mastery_records(student_id,class_id,mastery_key,learning_outcome,topic,mastery_score,evidence_count,status,last_evidence_at,next_review_at,metadata)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                       ON CONFLICT(student_id,class_id,mastery_key) DO UPDATE SET learning_outcome=EXCLUDED.learning_outcome,topic=EXCLUDED.topic,mastery_score=EXCLUDED.mastery_score,evidence_count=EXCLUDED.evidence_count,status=EXCLUDED.status,last_evidence_at=EXCLUDED.last_evidence_at,next_review_at=EXCLUDED.next_review_at,metadata=EXCLUDED.metadata""",
                    (student_id, class_id, key, outcome[:500], topic[:500], new_score, new_count, status, now, next_review, _json(metadata)),
                )
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute(
                    """INSERT INTO ai_tutor_mastery_records(student_id,class_id,mastery_key,learning_outcome,topic,mastery_score,evidence_count,status,last_evidence_at,next_review_at,metadata)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(student_id,class_id,mastery_key) DO UPDATE SET learning_outcome=excluded.learning_outcome,topic=excluded.topic,mastery_score=excluded.mastery_score,evidence_count=excluded.evidence_count,status=excluded.status,last_evidence_at=excluded.last_evidence_at,next_review_at=excluded.next_review_at,metadata=excluded.metadata""",
                    (student_id, class_id, key, outcome[:500], topic[:500], new_score, new_count, status, now.isoformat(), next_review.isoformat(), _json(metadata)),
                )
                conn.commit()
        if spaced_revision_enabled:
            self.schedule_revision(student_id=student_id, class_id=class_id, outcome=outcome, topic=topic, due_at=next_review, interval_days=interval, source_event=source)
        return self.get_mastery(student_id, class_id, key) or {}

    def get_mastery(self, student_id: str, class_id: str, mastery_key: str) -> dict[str, Any] | None:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_mastery_records WHERE student_id=%s AND class_id=%s AND mastery_key=%s", (student_id, class_id, mastery_key))
                row = cur.fetchone()
        else:
            with self._lock, self._sqlite() as conn:
                row = conn.execute("SELECT * FROM ai_tutor_mastery_records WHERE student_id=? AND class_id=? AND mastery_key=?", (student_id, class_id, mastery_key)).fetchone()
        return self._mastery_public(dict(row)) if row else None

    @staticmethod
    def _mastery_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "student_id": str(row.get("student_id", "")), "class_id": str(row.get("class_id", "")),
            "mastery_key": str(row.get("mastery_key", "")), "learning_outcome": str(row.get("learning_outcome", "")),
            "topic": str(row.get("topic", "")), "mastery_score": round(float(row.get("mastery_score", 0) or 0), 1),
            "evidence_count": int(row.get("evidence_count", 0) or 0), "status": str(row.get("status", "not_started")),
            "last_evidence_at": _iso(row.get("last_evidence_at")), "next_review_at": _iso(row.get("next_review_at")),
            "metadata": _safe_json(row.get("metadata"), {}),
        }

    def mastery_for_student(self, student_id: str, class_id: str | None = None) -> list[dict[str, Any]]:
        placeholder = "%s" if self._use_postgres else "?"
        sql = f"SELECT * FROM ai_tutor_mastery_records WHERE student_id={placeholder}"
        params: list[Any] = [student_id]
        if class_id:
            sql += f" AND class_id={placeholder}"
            params.append(class_id)
        sql += " ORDER BY mastery_score ASC,last_evidence_at DESC"
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql, tuple(params)); rows = cur.fetchall()
        else:
            with self._lock, self._sqlite() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._mastery_public(dict(row)) for row in rows]

    def schedule_revision(self, *, student_id: str, class_id: str, outcome: str, topic: str, due_at: datetime, interval_days: int, source_event: str) -> dict[str, Any]:
        key = self._key(outcome, topic)
        revision_id = str(uuid.uuid4())
        now = _utcnow()
        # Keep only one pending item per mastery key.
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM ai_tutor_revision_items WHERE student_id=%s AND class_id=%s AND mastery_key=%s AND status='due'", (student_id, class_id, key))
                cur.execute(
                    "INSERT INTO ai_tutor_revision_items(id,student_id,class_id,mastery_key,learning_outcome,topic,due_at,interval_days,status,source_event,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'due',%s,%s)",
                    (revision_id, student_id, class_id, key, outcome[:500], topic[:500], due_at, interval_days, source_event[:100], now),
                )
                conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute("DELETE FROM ai_tutor_revision_items WHERE student_id=? AND class_id=? AND mastery_key=? AND status='due'", (student_id, class_id, key))
                conn.execute(
                    "INSERT INTO ai_tutor_revision_items(id,student_id,class_id,mastery_key,learning_outcome,topic,due_at,interval_days,status,source_event,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (revision_id, student_id, class_id, key, outcome[:500], topic[:500], due_at.isoformat(), interval_days, "due", source_event[:100], now.isoformat()),
                )
                conn.commit()
        return {"id": revision_id, "due_at": due_at.isoformat(), "topic": topic, "learning_outcome": outcome}

    def due_revisions(self, student_id: str, *, include_upcoming: bool = True, limit: int = 20, class_id: str | None = None) -> list[dict[str, Any]]:
        now = _utcnow()
        horizon = now + timedelta(days=7) if include_upcoming else now
        placeholder = "%s" if self._use_postgres else "?"
        sql = f"SELECT * FROM ai_tutor_revision_items WHERE student_id={placeholder} AND status='due' AND due_at<={placeholder}"
        params_list: list[Any] = [student_id, horizon if self._use_postgres else horizon.isoformat()]
        if class_id:
            sql += f" AND class_id={placeholder}"
            params_list.append(class_id)
        sql += f" ORDER BY due_at ASC LIMIT {placeholder}"
        params_list.append(limit)
        params = tuple(params_list)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(sql, params); rows = cur.fetchall()
        else:
            with self._lock, self._sqlite() as conn:
                rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            due_text = _iso(data.get("due_at"))
            try:
                due_dt = datetime.fromisoformat(due_text.replace("Z", "+00:00"))
                overdue = due_dt <= now
            except ValueError:
                overdue = True
            result.append({
                "id": str(data.get("id", "")), "class_id": str(data.get("class_id", "")),
                "learning_outcome": str(data.get("learning_outcome", "")), "topic": str(data.get("topic", "")),
                "due_at": due_text, "interval_days": int(data.get("interval_days", 1) or 1),
                "overdue": overdue, "source_event": str(data.get("source_event", "")),
            })
        return result

    def complete_revision(self, revision_id: str, student_id: str) -> bool:
        now = _utcnow()
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("UPDATE ai_tutor_revision_items SET status='completed',completed_at=%s WHERE id=%s AND student_id=%s", (now, revision_id, student_id))
                ok = cur.rowcount > 0; conn.commit(); return ok
        with self._lock, self._sqlite() as conn:
            cur = conn.execute("UPDATE ai_tutor_revision_items SET status='completed',completed_at=? WHERE id=? AND student_id=?", (now.isoformat(), revision_id, student_id))
            conn.commit(); return cur.rowcount > 0

    def add_note(self, *, student_id: str, class_id: str = "", section_id: str = "", note_type: str = "note", title: str = "", content: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if note_type not in {"note", "bookmark", "worked_example", "revision_flag"}:
            note_type = "note"
        note_id = str(uuid.uuid4())
        now = _utcnow()
        values = (note_id, student_id, class_id or None, section_id[:80], note_type, title[:220], content[:12000], _json(metadata or {}), now)
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO ai_tutor_student_notes(id,student_id,class_id,section_id,note_type,title,content,metadata,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)", (*values, now)); conn.commit()
        else:
            with self._lock, self._sqlite() as conn:
                conn.execute("INSERT INTO ai_tutor_student_notes(id,student_id,class_id,section_id,note_type,title,content,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (*values[:-1], now.isoformat(), now.isoformat())); conn.commit()
        return self.get_note(note_id, student_id) or {}

    def get_note(self, note_id: str, student_id: str) -> dict[str, Any] | None:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM ai_tutor_student_notes WHERE id=%s AND student_id=%s", (note_id, student_id)); row = cur.fetchone()
        else:
            with self._lock, self._sqlite() as conn:
                row = conn.execute("SELECT * FROM ai_tutor_student_notes WHERE id=? AND student_id=?", (note_id, student_id)).fetchone()
        if not row: return None
        data = dict(row)
        return {"id": str(data.get("id", "")), "class_id": str(data.get("class_id", "") or ""), "section_id": str(data.get("section_id", "")), "note_type": str(data.get("note_type", "note")), "title": str(data.get("title", "")), "content": str(data.get("content", "")), "metadata": _safe_json(data.get("metadata"), {}), "created_at": _iso(data.get("created_at")), "updated_at": _iso(data.get("updated_at"))}

    def list_notes(self, student_id: str, class_id: str | None = None) -> list[dict[str, Any]]:
        placeholder = "%s" if self._use_postgres else "?"
        sql = f"SELECT * FROM ai_tutor_student_notes WHERE student_id={placeholder}"
        params: list[Any] = [student_id]
        if class_id:
            sql += f" AND class_id={placeholder}"; params.append(class_id)
        sql += " ORDER BY updated_at DESC"
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur: cur.execute(sql, tuple(params)); rows = cur.fetchall()
        else:
            with self._lock, self._sqlite() as conn: rows = conn.execute(sql, tuple(params)).fetchall()
        return [self.get_note(str(dict(row).get("id", "")), student_id) for row in rows if dict(row).get("id")]

    def delete_note(self, note_id: str, student_id: str) -> bool:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur: cur.execute("DELETE FROM ai_tutor_student_notes WHERE id=%s AND student_id=%s", (note_id, student_id)); ok=cur.rowcount>0; conn.commit(); return ok
        with self._lock, self._sqlite() as conn: cur=conn.execute("DELETE FROM ai_tutor_student_notes WHERE id=? AND student_id=?", (note_id, student_id)); conn.commit(); return cur.rowcount>0

    def diagnostic_completed(self, student_id: str, class_id: str) -> bool:
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute("""SELECT 1 FROM ai_tutor_assessment_attempts at JOIN ai_tutor_assessments a ON a.id=at.assessment_id WHERE at.student_id=%s AND a.class_id=%s AND a.assessment_type='diagnostic' AND at.completed=TRUE LIMIT 1""", (student_id, class_id)); return cur.fetchone() is not None
        with self._lock, self._sqlite() as conn:
            row=conn.execute("""SELECT 1 FROM ai_tutor_assessment_attempts at JOIN ai_tutor_assessments a ON a.id=at.assessment_id WHERE at.student_id=? AND a.class_id=? AND a.assessment_type='diagnostic' AND at.completed=1 LIMIT 1""", (student_id, class_id)).fetchone(); return row is not None

    def learning_path(self, *, student_id: str, classroom: dict[str, Any]) -> dict[str, Any]:
        class_id = str(classroom.get("id", ""))
        mastery = self.mastery_for_student(student_id, class_id)
        by_key = {str(item.get("mastery_key", "")): item for item in mastery}
        topics = [str(item).strip() for item in classroom.get("weekly_topics", []) if str(item).strip()]
        outcomes = [str(item).strip() for item in classroom.get("learning_outcomes", []) if str(item).strip()]
        items: list[dict[str, Any]] = []
        sequence = topics or outcomes
        for index, title in enumerate(sequence):
            record = by_key.get(title) or next((m for m in mastery if title.lower() in (str(m.get("topic", "")) + str(m.get("learning_outcome", ""))).lower()), None)
            score = float(record.get("mastery_score", 0) if record else 0)
            status = str(record.get("status", "not_started") if record else "not_started")
            items.append({"position": index + 1, "title": title, "mastery_score": round(score, 1), "status": status, "recommended": False})
        diagnostic_required = self.policy(class_id)["diagnostics_required"] and not self.diagnostic_completed(student_id, class_id)
        due = self.due_revisions(student_id, include_upcoming=False, limit=5, class_id=class_id)
        next_action: dict[str, Any]
        if diagnostic_required:
            diagnostics = [a for a in self.list_assessments(class_id) if a["assessment_type"] == "diagnostic"]
            next_action = {"type": "diagnostic", "label": "Complete your entry diagnostic", "assessment_id": diagnostics[0]["id"] if diagnostics else "", "class_id": class_id}
        elif due:
            next_action = {"type": "revision", "label": f"Review: {due[0].get('topic') or due[0].get('learning_outcome')}", **due[0]}
        else:
            target = next((item for item in items if item["mastery_score"] < self.policy(class_id)["mastery_pass_mark"]), items[0] if items else None)
            if target:
                target["recommended"] = True
                next_action = {"type": "lesson", "label": f"Continue with: {target['title']}", "topic": target["title"], "class_id": class_id}
            else:
                next_action = {"type": "course_complete", "label": "All configured outcomes are currently mastered", "class_id": class_id}
        milestones = {
            "mastered_outcomes": sum(item["status"] == "mastered" for item in items),
            "competent_or_better": sum(item["status"] in {"competent", "mastered"} for item in items),
            "total_items": len(items),
            "diagnostic_completed": not diagnostic_required,
        }
        return {"class_id": class_id, "items": items, "next_action": next_action, "diagnostic_required": diagnostic_required, "reviews_due": due, "milestones": milestones}

    def teacher_insights(self, teacher_class_ids: list[str]) -> dict[str, Any]:
        if not teacher_class_ids:
            return {"mastery": [], "diagnostic_gaps": [], "revision_backlog": 0}
        placeholders = ",".join(["%s" if self._use_postgres else "?"] * len(teacher_class_ids))
        if self._use_postgres:
            with self._pg() as conn, conn.cursor() as cur:
                cur.execute(f"SELECT * FROM ai_tutor_mastery_records WHERE class_id IN ({placeholders})", tuple(teacher_class_ids)); mastery_rows=cur.fetchall()
                cur.execute(f"SELECT COUNT(*) AS n FROM ai_tutor_revision_items WHERE class_id IN ({placeholders}) AND status='due' AND due_at<=NOW()", tuple(teacher_class_ids)); backlog=int(cur.fetchone()["n"] or 0)
        else:
            with self._lock, self._sqlite() as conn:
                mastery_rows=conn.execute(f"SELECT * FROM ai_tutor_mastery_records WHERE class_id IN ({placeholders})", tuple(teacher_class_ids)).fetchall()
                backlog=int(conn.execute(f"SELECT COUNT(*) FROM ai_tutor_revision_items WHERE class_id IN ({placeholders}) AND status='due' AND due_at<=?", (*teacher_class_ids, _utcnow().isoformat())).fetchone()[0])
        mastery = [self._mastery_public(dict(row)) for row in mastery_rows]
        weak = [item for item in mastery if item["mastery_score"] < 60]
        weak.sort(key=lambda item: item["mastery_score"])
        return {"mastery": mastery, "weak_mastery": weak[:100], "revision_backlog": backlog}
