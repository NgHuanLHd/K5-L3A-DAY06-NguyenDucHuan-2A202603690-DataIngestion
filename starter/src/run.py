"""Day 06 pipeline: ingest -> chunk -> embed -> store -> retrieve -> evaluate.

Usage (from starter/ with .venv active):
    python -m src.run --dump-pages        # read + normalize only -> results/pages.jsonl
    python -m src.run --check-benchmark   # validate benchmark/questions.jsonl
    python -m src.run --ingest-only       # build indexes A and B in pgvector
    python -m src.run --split dev         # ingest + retrieve dev questions for A/B/C
    python -m src.run --split test --skip-ingest
"""
import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .evaluation import evaluate_query, summarize, verify_benchmark
from .ingestion import load_pdf

STARTER = Path(__file__).resolve().parents[1]
REPO = STARTER.parent
RESULTS = REPO / "results"
BENCHMARK = REPO / "benchmark" / "questions.jsonl"

# Physical indexes: A and B. C reuses index B; the only difference is the metadata filter.
CHUNKERS = {
    "A": partial(fixed_size, size=500, overlap=50),
    "B": partial(by_paragraph, max_size=800),
}
STRATEGIES = {
    "A": {"index": "A", "use_filter": False},
    "B": {"index": "B", "use_filter": False},
    "C": {"index": "B", "use_filter": True},
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
                    encoding="utf-8")


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def parse_pages(spec: str) -> set[int]:
    pages = set()
    for part in str(spec).split(","):
        a, _, b = part.strip().partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return pages


def load_corpus():
    manifest = json.loads((REPO / "data" / "manifest.json").read_text(encoding="utf-8"))
    pages, errors = [], []
    for doc in manifest:
        meta = {**doc.get("metadata", {}), "title": doc["title"]}
        pages += load_pdf(REPO / doc["source_path_or_url"], doc["source_id"],
                          Path(doc["source_path_or_url"]).name,
                          parse_pages(doc["content_pages"]), meta, errors)
    write_jsonl(RESULTS / "pages.jsonl", [{**asdict(p), "chars": len(p.text)} for p in pages])
    write_jsonl(RESULTS / "ingest_errors.jsonl", errors)
    print(f"content pages: {len(pages)} | errors/empty: {len(errors)} "
          f"| chars: {sum(len(p.text) for p in pages)}")
    if len(pages) < 30:
        sys.exit(f"Only {len(pages)} usable content pages; need >= 30.")
    return pages


def check_benchmark(pages):
    if not BENCHMARK.exists():
        sys.exit(f"Missing {BENCHMARK}. Write the benchmark first (see BENCHMARK.md).")
    questions = read_jsonl(BENCHMARK)
    problems = verify_benchmark(questions, {(p.document_id, p.page): p.text for p in pages})
    if problems:
        print("\n".join(problems))
        sys.exit("Benchmark check FAILED.")
    print(f"Benchmark OK: {len(questions)} questions")
    return questions


def ingest(pages, embedder, store):
    stats = {}
    for index, chunker in CHUNKERS.items():
        t0 = time.perf_counter()
        chunks = [c for p in pages for c in chunker(p)]
        t1 = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in chunks])
        t2 = time.perf_counter()
        store.upsert(index, chunks, vectors)
        t3 = time.perf_counter()
        before = store.count(index)
        store.upsert(index, chunks, vectors)  # re-ingest the same version: count must not change
        after = store.count(index)
        if before != after or after != len(chunks):
            sys.exit(f"Re-ingest check failed for {index}: {len(chunks)} chunks, "
                     f"count before={before} after={after}")
        lengths = [len(c.text) for c in chunks]
        stats[index] = {
            "chunk_count": len(chunks), "total_chars": sum(lengths),
            "len_min": min(lengths), "len_mean": round(statistics.mean(lengths), 1),
            "len_median": statistics.median(lengths), "len_max": max(lengths),
            "chunk_s": round(t1 - t0, 2), "embed_s": round(t2 - t1, 2),
            "store_s": round(t3 - t2, 2), "reingest_count_before_after": [before, after],
            "chunks_over_token_limit": embedder.count_truncated([c.text for c in chunks]),
            "cost_usd": 0,
        }
        write_jsonl(RESULTS / f"chunks_{index}.jsonl", [asdict(c) for c in chunks])
        print(index, stats[index])
    stats["_model"] = {"name": embedder.model_name, "dimensions": embedder.dimensions,
                       "max_tokens": embedder.max_tokens,
                       "query_prefix": embedder.query_prefix, "doc_prefix": embedder.doc_prefix,
                       "normalize_embeddings": True, "metric": "cosine (pgvector <=>), exact"}
    stats["_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(RESULTS / "ingest_stats.json", stats)


def retrieve(questions, split, embedder, store):
    traces = []
    for name, cfg in STRATEGIES.items():
        for q in (q for q in questions if q["split"] == split):
            filters = q.get("filter") if cfg["use_filter"] else None
            t0 = time.perf_counter()
            hits = store.search(cfg["index"], embedder.embed_query(q["question"]), 3, filters)
            trace = evaluate_query(q, hits)
            trace.update(strategy=name, index=cfg["index"], filter_applied=filters,
                         latency_ms=round((time.perf_counter() - t0) * 1000, 1))
            traces.append(trace)
    write_jsonl(RESULTS / f"traces_{split}.jsonl", traces)
    summary = summarize(traces)
    write_json(RESULTS / f"summary_{split}.json", summary)
    print("| Strategy | Split | Hit@1 | Evidence Hit@3 | Filter tuân thủ |")
    print("|---|---|---|---|---|")
    for key, s in summary.items():
        st, sp = key.split("/")
        f = f"{s['filter_compliant']}/{s['filter_questions']}" if s["filter_questions"] else "N/A"
        print(f"| {st} | {sp} | {s['hit_at_1']}/{s['N']} | {s['hit_at_3']}/{s['N']} | {f} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-pages", action="store_true", help="only read + normalize pages")
    ap.add_argument("--check-benchmark", action="store_true", help="only validate the benchmark")
    ap.add_argument("--ingest-only", action="store_true", help="build indexes, skip retrieval")
    ap.add_argument("--skip-ingest", action="store_true", help="reuse indexes already in the DB")
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    args = ap.parse_args()

    load_dotenv(STARTER / ".env")
    RESULTS.mkdir(exist_ok=True)
    pages = load_corpus()
    if args.dump_pages:
        return
    questions = None if args.ingest_only else check_benchmark(pages)
    if args.check_benchmark:
        return

    from .embeddings import MyEmbedder  # late import: dump/check do not need the model
    from .store import PgVectorStore
    embedder = MyEmbedder(os.getenv("EMBEDDING_MODEL", ""))
    store = PgVectorStore(os.getenv("DATABASE_URL", ""), embedder.dimensions)
    store.create_schema()
    if not args.skip_ingest:
        ingest(pages, embedder, store)
    if questions is not None:
        retrieve(questions, args.split, embedder, store)


if __name__ == "__main__":
    main()
