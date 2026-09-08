"""Week 4 Retrieval Evaluation Script.

Evaluates hit-rate@3 and p50 latency over golden_set.jsonl.
"""

from __future__ import annotations

import json
import time
import statistics
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.retrieval.vector_store import VectorStore
from app.retrieval.retriever import Retriever


def load_golden_set(filepath: Path) -> list[dict]:
    items = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_evaluation(retriever: Retriever, golden_set: list[dict], top_k: int = 3):
    results = []
    latencies = []

    for item in golden_set:
        qid = item.get("id")
        q = item.get("question") or item.get("query")
        expected = item.get("expected_chunk_id")
        token_match = item.get("token_match")

        t0 = time.perf_counter()
        retrieved_chunks = retriever.retrieve(q, top_k=top_k)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)

        retrieved_ids = [c.chunk_id for c in retrieved_chunks]
        hit = expected in retrieved_ids

        results.append({
            "id": qid,
            "question": q,
            "expected_chunk_id": expected,
            "token_match": token_match,
            "retrieved_chunk_ids": retrieved_ids,
            "hit": hit,
            "latency_ms": latency_ms,
            "retrieved_chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "score": c.score,
                    "text_snippet": c.text[:150]
                }
                for c in retrieved_chunks
            ]
        })

    hits = sum(1 for r in results if r["hit"])
    total = len(results)
    hit_rate = hits / total if total > 0 else 0.0
    p50_latency = statistics.median(latencies) if latencies else 0.0

    return {
        "hit_rate": hit_rate,
        "hits": hits,
        "total": total,
        "p50_latency_ms": p50_latency,
        "results": results,
    }


def main():
    settings = get_settings()
    golden_set_path = PROJECT_ROOT / "golden_set.jsonl"
    golden_set = load_golden_set(golden_set_path)

    store = VectorStore(settings.chroma_path, settings.collection_name)
    retriever = Retriever(store, top_k=3, min_relevance=0.0)

    eval_res = run_evaluation(retriever, golden_set, top_k=3)

    print("=" * 60)
    print(f"Collection: {settings.collection_name}")
    print(f"Baseline Hit-rate@3: {eval_res['hit_rate'] * 100:.1f}% ({eval_res['hits']}/{eval_res['total']})")
    print(f"Baseline p50 Latency: {eval_res['p50_latency_ms']:.2f} ms")
    print("=" * 60)

    for r in eval_res["results"]:
        status = "HIT " if r["hit"] else "MISS"
        print(f"[{status}] Q{r['id']}: {r['question']}")
        print(f"       Expected: {r['expected_chunk_id']}")
        print(f"       Got     : {r['retrieved_chunk_ids']}")
        if not r["hit"]:
            print("       Top Chunks:")
            for c in r["retrieved_chunks"]:
                print(f"         - {c['chunk_id']} (score: {c['score']:.4f})")
        print("-" * 60)

    # Save detailed evaluation log
    out_path = PROJECT_ROOT / "scripts" / "baseline_eval.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(eval_res, f, indent=2)
    print(f"Saved detailed results to {out_path}")


if __name__ == "__main__":
    main()
