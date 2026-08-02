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


@dataclass
class Chunk:
    source: str
    chunk_index: int
    content: str


@dataclass
class RetrievedChunk:
    source: str
    content: str
    score: float


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


def make_chunks(text: str, source: str, target_words: int = 420, overlap_words: int = 60) -> list[Chunk]:
    clean = _normalise_space(text)
    if not clean:
        return []
    words = clean.split()
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(words):
        end = min(start + target_words, len(words))
        content = " ".join(words[start:end]).strip()
        if content:
            chunks.append(Chunk(source=source, chunk_index=index, content=content))
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
                        CREATE TABLE IF NOT EXISTS knowledge_chunks (
                            id BIGSERIAL PRIMARY KEY,
                            source TEXT NOT NULL,
                            chunk_index INTEGER NOT NULL,
                            content TEXT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            UNIQUE(source, chunk_index)
                        )
                        """
                    )
                conn.commit()
            return

        if self.storage_file.exists():
            try:
                raw = json.loads(self.storage_file.read_text(encoding="utf-8"))
                self._memory = [Chunk(**item) for item in raw]
            except (json.JSONDecodeError, TypeError, OSError):
                self._memory = []

    def _save_local(self) -> None:
        payload = [chunk.__dict__ for chunk in self._memory]
        self.storage_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def replace_source(self, source: str, chunks: Iterable[Chunk]) -> int:
        new_chunks = list(chunks)
        if self._use_postgres:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM knowledge_chunks WHERE source = %s", (source,))
                    cur.executemany(
                        "INSERT INTO knowledge_chunks (source, chunk_index, content) VALUES (%s, %s, %s)",
                        [(c.source, c.chunk_index, c.content) for c in new_chunks],
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
                    cur.execute("SELECT source, chunk_index, content FROM knowledge_chunks ORDER BY source, chunk_index")
                    rows = cur.fetchall()
            return [Chunk(source=row[0], chunk_index=row[1], content=row[2]) for row in rows]
        with self._lock:
            return list(self._memory)

    def list_sources(self) -> list[dict[str, int]]:
        counts = Counter(chunk.source for chunk in self.all_chunks())
        return [{"source": source, "chunks": count} for source, count in sorted(counts.items())]

    def retrieve(self, query: str, limit: int = 5) -> list[RetrievedChunk]:
        chunks = self.all_chunks()
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
            if score > 0:
                scored.append(RetrievedChunk(source=chunk.source, content=chunk.content, score=score))

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]
