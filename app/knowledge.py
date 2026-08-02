from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from docx import Document
from pypdf import PdfReader

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'-]{1,}")
MATERIAL_TYPES = {"course", "approved_external"}


@dataclass
class Chunk:
    source: str
    chunk_index: int
    content: str
    class_id: str = ""
    material_type: str = "course"
    display_source: str = ""


@dataclass
class RetrievedChunk:
    source: str
    content: str
    score: float
    class_id: str = ""
    material_type: str = "course"


def _normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv"}:
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        from io import BytesIO

        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        from io import BytesIO

        doc = Document(BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                paragraphs.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(paragraphs)
    raise ValueError("Unsupported file type. Use PDF, DOCX, TXT, MD or CSV.")


def make_chunks(
    text: str,
    source: str,
    target_words: int = 420,
    overlap_words: int = 60,
    *,
    class_id: str = "",
    material_type: str = "course",
    display_source: str = "",
) -> list[Chunk]:
    clean = _normalise_space(text)
    if not clean:
        return []
    material_type = material_type if material_type in MATERIAL_TYPES else "course"
    words = clean.split()
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(words):
        end = min(start + target_words, len(words))
        content = " ".join(words[start:end]).strip()
        if content:
            chunks.append(
                Chunk(
                    source=source,
                    chunk_index=index,
                    content=content,
                    class_id=class_id,
                    material_type=material_type,
                    display_source=display_source or source,
                )
            )
            index += 1
        if end >= len(words):
            break
        start = max(end - overlap_words, start + 1)
    return chunks


class KnowledgeStore:
    def __init__(self, *, database_url: str, storage_dir: Path) -> None:
        self.database_url = database_url
        self.storage_file = storage_dir / "knowledge.json"
        self._lock = threading.RLock()
        self._memory: list[Chunk] = []
        self._use_postgres = bool(database_url and psycopg is not None)
        self.initialise()

    def _connect(self):
        if not self._use_postgres:
            raise RuntimeError("PostgreSQL is not configured")
        return psycopg.connect(self.database_url)

    def initialise(self) -> None:
        if self._use_postgres:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS ai_tutor_knowledge_chunks (
                            id BIGSERIAL PRIMARY KEY,
                            source TEXT NOT NULL,
                            chunk_index INTEGER NOT NULL,
                            content TEXT NOT NULL,
                            class_id TEXT NOT NULL DEFAULT '',
                            material_type TEXT NOT NULL DEFAULT 'course',
                            display_source TEXT NOT NULL DEFAULT '',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            UNIQUE(source, chunk_index)
                        )
                        """
                    )
                    cur.execute("ALTER TABLE ai_tutor_knowledge_chunks ADD COLUMN IF NOT EXISTS class_id TEXT NOT NULL DEFAULT ''")
                    cur.execute("ALTER TABLE ai_tutor_knowledge_chunks ADD COLUMN IF NOT EXISTS material_type TEXT NOT NULL DEFAULT 'course'")
                    cur.execute("ALTER TABLE ai_tutor_knowledge_chunks ADD COLUMN IF NOT EXISTS display_source TEXT NOT NULL DEFAULT ''")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_tutor_knowledge_scope ON ai_tutor_knowledge_chunks(class_id, material_type)")
                conn.commit()
            return

        if self.storage_file.exists():
            try:
                raw = json.loads(self.storage_file.read_text(encoding="utf-8"))
                self._memory = [
                    Chunk(
                        source=str(item.get("source", "")),
                        chunk_index=int(item.get("chunk_index", 0)),
                        content=str(item.get("content", "")),
                        class_id=str(item.get("class_id", "")),
                        material_type=str(item.get("material_type", "course")),
                        display_source=str(item.get("display_source", item.get("source", ""))),
                    )
                    for item in raw
                ]
            except (json.JSONDecodeError, TypeError, OSError, ValueError):
                self._memory = []

    def _save_local(self) -> None:
        payload = [chunk.__dict__ for chunk in self._memory]
        self.storage_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def replace_source(self, source: str, chunks: Iterable[Chunk]) -> int:
        new_chunks = list(chunks)
        if self._use_postgres:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM ai_tutor_knowledge_chunks WHERE source = %s", (source,))
                    cur.executemany(
                        """INSERT INTO ai_tutor_knowledge_chunks
                           (source, chunk_index, content, class_id, material_type, display_source)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        [
                            (
                                c.source,
                                c.chunk_index,
                                c.content,
                                c.class_id,
                                c.material_type if c.material_type in MATERIAL_TYPES else "course",
                                c.display_source or c.source,
                            )
                            for c in new_chunks
                        ],
                    )
                conn.commit()
            return len(new_chunks)

        with self._lock:
            self._memory = [c for c in self._memory if c.source != source]
            self._memory.extend(new_chunks)
            self._save_local()
        return len(new_chunks)

    def all_chunks(self) -> list[Chunk]:
        if self._use_postgres:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT source, chunk_index, content, class_id, material_type, display_source
                           FROM ai_tutor_knowledge_chunks ORDER BY source, chunk_index"""
                    )
                    rows = cur.fetchall()
            return [
                Chunk(
                    source=row[0],
                    chunk_index=row[1],
                    content=row[2],
                    class_id=row[3] or "",
                    material_type=row[4] or "course",
                    display_source=row[5] or row[0],
                )
                for row in rows
            ]
        with self._lock:
            return list(self._memory)

    def list_sources(self, *, class_id: str | None = None, include_global: bool = True) -> list[dict[str, object]]:
        chunks = self.all_chunks()
        if class_id is not None:
            chunks = [c for c in chunks if c.class_id == class_id or (include_global and not c.class_id)]
        counts: Counter[tuple[str, str, str]] = Counter(
            (chunk.display_source or chunk.source, chunk.class_id, chunk.material_type) for chunk in chunks
        )
        return [
            {"source": source, "chunks": count, "class_id": scope, "material_type": material_type}
            for (source, scope, material_type), count in sorted(counts.items())
        ]

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        *,
        class_id: str = "",
        allowed_types: set[str] | None = None,
        include_global: bool = True,
    ) -> list[RetrievedChunk]:
        chunks = self.all_chunks()
        allowed_types = allowed_types or {"course", "approved_external"}
        chunks = [
            chunk
            for chunk in chunks
            if chunk.material_type in allowed_types
            and (
                (class_id and chunk.class_id == class_id)
                or (include_global and not chunk.class_id)
                or (not class_id and not chunk.class_id)
            )
        ]
        if not chunks or not query.strip():
            return []

        query_tokens = [t.lower() for t in TOKEN_RE.findall(query)]
        if not query_tokens:
            return []
        query_counts = Counter(query_tokens)

        doc_tokens: list[Counter[str]] = []
        document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            counts = Counter(t.lower() for t in TOKEN_RE.findall(chunk.content))
            doc_tokens.append(counts)
            for token in counts:
                if token in query_counts:
                    document_frequency[token] += 1

        total_docs = len(chunks)
        scored: list[RetrievedChunk] = []
        query_lower = query.lower().strip()
        for chunk, counts in zip(chunks, doc_tokens):
            length_norm = max(sum(counts.values()), 1)
            score = 0.0
            for token, q_count in query_counts.items():
                tf = counts[token] / length_norm
                idf = math.log((total_docs + 1) / (document_frequency[token] + 1)) + 1.0
                score += tf * idf * (1 + math.log(q_count))
            if len(query_lower) >= 12 and query_lower in chunk.content.lower():
                score += 2.0
            if chunk.class_id == class_id and class_id:
                score *= 1.12
            if score > 0:
                scored.append(
                    RetrievedChunk(
                        source=chunk.display_source or chunk.source,
                        content=chunk.content,
                        score=score,
                        class_id=chunk.class_id,
                        material_type=chunk.material_type,
                    )
                )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]
