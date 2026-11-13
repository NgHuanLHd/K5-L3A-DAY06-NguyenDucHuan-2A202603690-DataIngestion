"""Evaluate retrieved evidence and preserve per-query traces.

Only automatic metrics (Hit@1, Evidence Hit@3, filter compliance) are computed here.
Chunk coherence and grounding are labelled by hand (see src/audit.py).
"""
import re
import unicodedata
from collections import defaultdict
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().lower()


def gold_list(q: dict[str, Any]) -> list[dict[str, Any]]:
    main = {"source_id": q["gold_source_id"], "page": q["gold_page"],
            "evidence_quote": q["evidence_quote"]}
    return [main, *q.get("alt_gold", [])]


def is_hit(q: dict[str, Any], hit: dict[str, Any]) -> bool:
    """Hit = same source + same page + chunk contains the FULL evidence (any valid gold)."""
    return any(hit["document_id"] == g["source_id"] and int(hit["page"]) == int(g["page"])
               and _norm(g["evidence_quote"]) in _norm(hit["text"])
               for g in gold_list(q))


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    flags = [is_hit(question, h) for h in hits]
    filt = question.get("filter")
    compliant = None
    if filt:
        compliant = all(str(h["metadata"].get(k)) == str(v) for h in hits for k, v in filt.items())
    return {
        "id": question["id"], "split": question["split"], "type": question.get("type"),
        "question": question["question"], "expected_answer": question["expected_answer"],
        "filter": filt, "gold": gold_list(question),
        "hit_at_1": bool(flags[:1] and flags[0]), "hit_at_3": any(flags[:3]),
        "first_hit_rank": flags.index(True) + 1 if True in flags else None,
        "filter_compliant": compliant,
        "hits": [{"rank": i + 1, "is_hit": f, "chunk_id": h["chunk_id"],
                  "document_id": h["document_id"], "source": h["source"], "page": h["page"],
                  "score": round(float(h["score"]), 4), "metadata": h["metadata"],
                  "text": h["text"]} for i, (h, f) in enumerate(zip(hits, flags))],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    groups = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
    out = {}
    for (strategy, split), ts in sorted(groups.items()):
        with_filter = [t for t in ts if t["filter"]]
        out[f"{strategy}/{split}"] = {
            "N": len(ts),
            "hit_at_1": sum(t["hit_at_1"] for t in ts),
            "hit_at_3": sum(t["hit_at_3"] for t in ts),
            "filter_questions": len(with_filter),
            "filter_compliant": sum(bool(t["filter_compliant"]) for t in with_filter),
        }
    return out


def verify_benchmark(questions: list[dict], pages: dict[tuple[str, int], str]) -> list[str]:
    """Pre-run checks: counts, splits, filter questions, evidence present on the gold page."""
    problems, ids = [], set()
    required = ("id", "split", "question", "expected_answer",
                "gold_source_id", "gold_page", "evidence_quote")
    for n, q in enumerate(questions, start=1):
        missing = [k for k in required if not q.get(k)]
        if missing:
            problems.append(f"line {n}: missing fields {missing}")
            continue
        if q["id"] in ids:
            problems.append(f"{q['id']}: duplicate id")
        ids.add(q["id"])
        if q["split"] not in ("dev", "test"):
            problems.append(f"{q['id']}: split must be dev/test")
        for g in gold_list(q):
            page_text = pages.get((g["source_id"], int(g["page"])))
            if page_text is None:
                problems.append(f"{q['id']}: page {g['source_id']}#{g['page']} not in corpus")
            elif _norm(g["evidence_quote"]) not in _norm(page_text):
                problems.append(f"{q['id']}: evidence not found on {g['source_id']}#{g['page']}")
    dev = sum(q.get("split") == "dev" for q in questions)
    test = sum(q.get("split") == "test" for q in questions)
    filt = [q for q in questions if q.get("filter")]
    if len(questions) < 20 or dev < 15 or test < 5:
        problems.append(f"need >=20 questions (>=15 dev, >=5 test); have dev={dev} test={test}")
    if len(filt) < 3 or not any(q.get("split") == "test" for q in filt):
        problems.append("need >=3 filter questions with >=1 in test")
    return problems
