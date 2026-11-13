"""Manual-audit sheets and their summary.

    python -m src.audit make     -> create empty CSV sheets in results/ to label by hand
    python -m src.audit summary  -> aggregate the labels once every score cell is filled
"""
import csv
import json
import re
import sys
from collections import defaultdict

from .models import DocumentPage
from .run import CHUNKERS, RESULTS, read_jsonl


def flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel reads it correctly
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")


def make():
    pages = [DocumentPage(**{k: v for k, v in p.items() if k != "chars"})
             for p in read_jsonl(RESULTS / "pages.jsonl")]
    pages.sort(key=lambda p: (p.document_id, p.page))
    # Coherence: 10 fixed positions = middle of the first 10 sorted pages (chosen before scoring).
    rows = []
    for i, page in enumerate(pages[:10], start=1):
        text = flat(page.text)
        mid = text.find(" ", len(text) // 2) + 1
        probe = text[mid:mid + 40]
        for index, chunker in CHUNKERS.items():
            chunks = chunker(page)
            hit = next((c for c in chunks if probe in flat(c.text)), None) \
                or next((c for c in chunks if probe[:20] in flat(c.text)), None)
            rows.append({"position": f"pos{i:02d}", "document_id": page.document_id,
                         "page": page.page, "probe": probe, "strategy": index,
                         "chunk_id": hit.chunk_id if hit else "SPLIT/NOT_FOUND",
                         "chunk_text": hit.text if hit else "", "score_0_2": "", "reason": ""})
    write_csv(RESULTS / "audit_coherence.csv", rows)

    traces_path = RESULTS / "traces_test.jsonl"
    if not traces_path.exists():
        print("results/traces_test.jsonl not found: run the test split first for metadata/grounding.")
        return
    traces = read_jsonl(traces_path)
    meta_rows, ground_rows = [], []
    for t in traces:
        for h in t["hits"]:
            meta_rows.append({"strategy": t["strategy"], "qid": t["id"], "rank": h["rank"],
                              "chunk_id": h["chunk_id"], "source": h["source"], "page": h["page"],
                              "metadata": json.dumps(h["metadata"], ensure_ascii=False),
                              "text_head": h["text"][:150], "ok_1_0": "", "error_note": ""})
        ground_rows.append({"strategy": t["strategy"], "qid": t["id"], "question": t["question"],
                            "expected_answer": t["expected_answer"],
                            "top3": "\n---\n".join(f"[{h['source']} p{h['page']}] {h['text']}"
                                                   for h in t["hits"]),
                            "score_0_2": "", "reason": ""})
    write_csv(RESULTS / "audit_metadata.csv", meta_rows)
    write_csv(RESULTS / "audit_grounding.csv", ground_rows)


def summary():
    for name, col in [("coherence", "score_0_2"), ("metadata", "ok_1_0"), ("grounding", "score_0_2")]:
        path = RESULTS / f"audit_{name}.csv"
        if not path.exists():
            print(f"{path.name}: missing")
            continue
        with path.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        by = defaultdict(list)
        for r in rows:
            if r[col].strip() == "":
                sys.exit(f"{path.name}: column {col} still has empty cells")
            by[r["strategy"]].append(int(r[col]))
        for s, v in sorted(by.items()):
            dist = {k: v.count(k) for k in sorted(set(v))}
            print(f"{name:10s} {s}: n={len(v)} sum={sum(v)} mean={sum(v) / len(v):.2f} dist={dist}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("make", "summary"):
        sys.exit("usage: python -m src.audit make|summary")
    {"make": make, "summary": summary}[sys.argv[1]]()
