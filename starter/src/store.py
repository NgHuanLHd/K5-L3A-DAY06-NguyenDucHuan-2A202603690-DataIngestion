"""Store and search vectors using PostgreSQL + pgvector (cosine distance, exact search)."""
import hashlib
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

# Only these metadata keys may be used as filters (keys are bound as SQL parameters too).
ALLOWED_FILTERS = {"year", "document_type", "language"}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty; set it in starter/.env")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("invalid dimensions")
        self.url, self.dimensions = database_url, dimensions

    def create_schema(self) -> None:
        with psycopg.connect(self.url) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    strategy     text NOT NULL,
                    chunk_id     text NOT NULL,
                    document_id  text NOT NULL,
                    source       text NOT NULL,
                    page         int  NOT NULL,
                    text         text NOT NULL,
                    content_hash text NOT NULL,
                    metadata     jsonb NOT NULL DEFAULT '{{}}',
                    embedding    vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            row = conn.execute("""
                SELECT format_type(atttypid, atttypmod) FROM pg_attribute
                WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'""").fetchone()
            if row and row[0] != f"vector({self.dimensions})":
                raise RuntimeError(f"Existing table has {row[0]} but model gives {self.dimensions} "
                                   "dimensions. Drop the table before switching models.")

    def count(self, strategy: str) -> int:
        with psycopg.connect(self.url) as conn:
            return conn.execute("SELECT count(*) FROM chunks WHERE strategy = %s",
                                (strategy,)).fetchone()[0]

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Idempotent write: stable IDs + ON CONFLICT; obsolete chunks of re-ingested docs are deleted."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        if any(len(v) != self.dimensions for v in vectors):
            raise ValueError("vector dimension mismatch")
        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page, c.text,
                 hashlib.sha256(c.text.encode("utf-8")).hexdigest(),
                 Jsonb(c.metadata), _vec(v)) for c, v in zip(chunks, vectors)]
        doc_ids = sorted({c.document_id for c in chunks})
        ids = [c.chunk_id for c in chunks]
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("""DELETE FROM chunks WHERE strategy = %s
                           AND document_id = ANY(%s) AND NOT (chunk_id = ANY(%s))""",
                        (strategy, doc_ids, ids))
            cur.executemany("""
                INSERT INTO chunks (strategy, chunk_id, document_id, source, page, text,
                                    content_hash, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                    metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding,
                    document_id = EXCLUDED.document_id,
                    source = EXCLUDED.source, page = EXCLUDED.page""", rows)

    def delete_strategy(self, strategy: str) -> int:
        with psycopg.connect(self.url) as conn:
            return conn.execute("DELETE FROM chunks WHERE strategy = %s", (strategy,)).rowcount

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Filter in SQL, rank by cosine distance; score = 1 - distance."""
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector dimension mismatch")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in ALLOWED_FILTERS:
                raise ValueError(f"filter field not allowed: {key}")
            where.append("metadata ->> %s = %s")
            params += [key, str(value)]
        qv = _vec(query_vector)
        sql = f"""
            SELECT chunk_id, document_id, source, page, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM chunks WHERE {' AND '.join(where)}
            ORDER BY embedding <=> %s::vector LIMIT %s"""
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute(sql, [qv, *params, qv, top_k])
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
