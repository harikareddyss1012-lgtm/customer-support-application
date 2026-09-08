"""Week 4 Retrieval Evaluation Script.

Evaluates hit-rate@3 and p50 latency over golden_set.jsonl for:
  - baseline (dense vector search)
  - hybrid (BM25 + RRF)
  - crossencoder / rerank (Dense + Cross-Encoder reranking)

Usage:
    python scripts/evaluate_week4.py                       # runs all strategies and prints comparison
    python scripts/evaluate_week4.py --strategy dense      # runs baseline (dense)
    python scripts/evaluate_week4.py --strategy hybrid     # runs hybrid
    python scripts/evaluate_week4.py --strategy rerank     # runs crossencoder (rerank)
    python scripts/evaluate_week4.py --strategy all        # runs all three strategies
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress verbose loggers during CLI evaluation output
logging.getLogger("app.retrieval.retriever").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.config import get_settings
from app.retrieval.retriever import Retriever
from app.retrieval.vector_store import VectorStore


def load_golden_set(filepath: Path) -> list[dict]:
    items = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_evaluation(retriever: Retriever, golden_set: list[dict], top_k: int = 3, strategy: str = "hybrid") -> dict:
    results = []
    latencies = []

    for item in golden_set:
        qid = item.get("id")
        q = item.get("question") or item.get("query")
        expected_chunk = item.get("expected_chunk_id")
        expected_article = item.get("expected_article_id") or (expected_chunk.split("::")[0] if expected_chunk else "")
        token_match = item.get("token_match")

        t0 = time.perf_counter()
        retrieved_chunks = retriever.retrieve(q, top_k=top_k, strategy=strategy)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)

        retrieved_ids = [c.chunk_id for c in retrieved_chunks]
        
        # Check exact chunk hit vs article hit
        chunk_hit = any(rid == expected_chunk or rid.startswith(f"{expected_article}::") for rid in retrieved_ids)
        article_hit = any(expected_article in rid for rid in retrieved_ids) if expected_article else chunk_hit
        hit = chunk_hit or article_hit

        results.append({
            "id": qid,
            "question": q,
            "expected_chunk_id": expected_chunk,
            "expected_article_id": expected_article,
            "token_match": token_match,
            "retrieved_chunk_ids": retrieved_ids,
            "hit": hit,
            "chunk_hit": chunk_hit,
            "article_hit": article_hit,
            "latency_ms": latency_ms,
            "retrieved_chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "score": c.score,
                    "text_snippet": c.text[:120].replace("\n", " ")
                }
                for c in retrieved_chunks
            ]
        })

    hits = sum(1 for r in results if r["hit"])
    chunk_hits = sum(1 for r in results if r["chunk_hit"])
    article_hits = sum(1 for r in results if r["article_hit"])
    total = len(results)
    hit_rate = hits / total if total > 0 else 0.0
    p50_latency = statistics.median(latencies) if latencies else 0.0

    return {
        "strategy": strategy,
        "hit_rate": hit_rate,
        "hits": hits,
        "chunk_hits": chunk_hits,
        "article_hits": article_hits,
        "total": total,
        "p50_latency_ms": p50_latency,
        "results": results,
    }


def print_single_strategy(eval_res: dict, strategy_label: str):
    print("\n" + "=" * 75)
    print(f" Strategy: {strategy_label.upper()}")
    print(f" Hit-rate@3: {eval_res['hit_rate'] * 100:.1f}% ({eval_res['hits']}/{eval_res['total']}) | Article Hits: {eval_res['article_hits']}/{eval_res['total']} | p50 Latency: {eval_res['p50_latency_ms']:.2f} ms")
    print("=" * 75)

    for r in eval_res["results"]:
        status = "HIT " if r["hit"] else "MISS"
        print(f"[{status}] Q{r['id']:2d}: {r['question']}")
        print(f"       Expected Chunk  : {r['expected_chunk_id']} (Article: {r['expected_article_id']})")
        print(f"       Retrieved Chunks: {r['retrieved_chunk_ids']}")
        if not r["hit"]:
            print("       Top Chunks Details:")
            for c in r["retrieved_chunks"]:
                print(f"         - {c['chunk_id']} (score: {c['score']:.4f}) -> {c['text_snippet']}...")
        print("-" * 75)


def print_comparison_table(all_results: dict[str, dict]):
    print("\n" + "=" * 80)
    print(f"{'STRATEGY COMPARISON SUMMARY':^80}")
    print("=" * 80)
    print(f"{'Strategy':<20} | {'Hit-Rate@3':<15} | {'Article Hits':<15} | {'p50 Latency':<15}")
    print("-" * 80)
    
    label_map = {
        "dense": "Baseline (Dense)",
        "hybrid": "Hybrid (BM25+RRF)",
        "rerank": "Cross-Encoder"
    }

    for strat, eval_res in all_results.items():
        name = label_map.get(strat, strat.capitalize())
        hit_str = f"{eval_res['hit_rate'] * 100:.1f}% ({eval_res['hits']}/{eval_res['total']})"
        art_str = f"{eval_res['article_hits']}/{eval_res['total']}"
        lat_str = f"{eval_res['p50_latency_ms']:.2f} ms"
        print(f"{name:<20} | {hit_str:<15} | {art_str:<15} | {lat_str:<15}")

    print("=" * 80)

    # Per question matrix
    print("\nPER-QUESTION HIT MATRIX:")
    header = f"{'Q#':<4} | {'Question Snippet':<45} | {'Baseline':<10} | {'Hybrid':<10} | {'CrossEncoder':<10}"
    print("-" * len(header))
    print(header)
    print("-" * len(header))

    q_ids = [r["id"] for r in next(iter(all_results.values()))["results"]]
    for qid in q_ids:
        q_text = next(r["question"] for r in next(iter(all_results.values()))["results"] if r["id"] == qid)
        q_snip = q_text[:43] + ".." if len(q_text) > 43 else q_text
        
        statuses = []
        for strat in ["dense", "hybrid", "rerank"]:
            if strat in all_results:
                r_item = next(r for r in all_results[strat]["results"] if r["id"] == qid)
                statuses.append("HIT " if r_item["hit"] else "MISS")
            else:
                statuses.append(" N/A")
        
        print(f"Q{qid:<3} | {q_snip:<45} | {statuses[0]:<10} | {statuses[1]:<10} | {statuses[2]:<10}")

    print("-" * len(header) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate Golden Set Retrieval across strategies.")
    parser.add_argument(
        "--strategy",
        type=str,
        default="all",
        choices=["dense", "baseline", "hybrid", "rerank", "crossencoder", "all"],
        help="Retrieval strategy to evaluate (dense/baseline, hybrid, rerank/crossencoder, or all)."
    )
    args = parser.parse_args()

    # Map aliases
    strat_input = args.strategy.lower()
    if strat_input == "baseline":
        strat_input = "dense"
    elif strat_input == "crossencoder":
        strat_input = "rerank"

    settings = get_settings()
    golden_set_path = PROJECT_ROOT / "golden_set.jsonl"
    if not golden_set_path.exists():
        print(f"Error: Golden set file not found at {golden_set_path}")
        sys.exit(1)

    golden_set = load_golden_set(golden_set_path)
    store = VectorStore(settings.chroma_path, settings.collection_name)
    retriever = Retriever(store, top_k=3, min_relevance=0.0)

    if strat_input == "all":
        strategies_to_run = ["dense", "hybrid", "rerank"]
    else:
        strategies_to_run = [strat_input]

    all_results = {}
    label_map = {
        "dense": "Baseline (Dense Vector)",
        "hybrid": "Hybrid (BM25 + RRF)",
        "rerank": "Cross-Encoder Reranker"
    }

    for strat in strategies_to_run:
        print(f"\n[Running evaluation for strategy: {label_map.get(strat, strat)}...]")
        eval_res = run_evaluation(retriever, golden_set, top_k=3, strategy=strat)
        all_results[strat] = eval_res
        print_single_strategy(eval_res, label_map.get(strat, strat))

    if len(all_results) > 1:
        print_comparison_table(all_results)

    # Save detailed evaluation log
    out_path = PROJECT_ROOT / "scripts" / "baseline_eval.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"Saved detailed evaluation comparison to {out_path}")


if __name__ == "__main__":
    main()

