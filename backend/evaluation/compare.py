#!/usr/bin/env python3
"""Builds the side-by-side provider/model comparison table (metrics as rows,
providers as columns) from two or more saved raw results files. Reads only
already-saved data — no API calls.

Usage:
    python evaluation/compare.py reports/openai-gpt-5-mini-....json reports/ollama-qwen3.5-9b-....json ...
"""

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from metrics import latency_stats  # noqa: E402
from pricing import estimate_cost_usd  # noqa: E402


def _column_label(data: dict) -> str:
    return f"{data['provider']}/{data['model']}"


def _metrics_for(data: dict) -> dict:
    results = data["results"]
    n = len(results)
    extraction_ok = [r for r in results if r["extraction"]["succeeded"]]
    classification_correct = sum(1 for r in extraction_ok if r["extraction_grading"]["classification_correct"])
    invented = sum(len(r["extraction_grading"]["invented_critical_fields"]) for r in results)
    clarification_correct = sum(1 for r in results if r["completeness"]["clarification_decision_correct"])

    generation_attempts = [r for r in results if r["generation"] is not None]
    generation_blocked = [r for r in generation_attempts if not r["generation"].get("passed_validation")]

    telugu = [r["translations"].get("TELUGU") for r in results if r["translations"].get("TELUGU", {}).get("attempted")]
    hindi = [r["translations"].get("HINDI") for r in results if r["translations"].get("HINDI", {}).get("attempted")]
    telugu_blocked = sum(1 for t in telugu if not t.get("passed_validation"))
    hindi_blocked = sum(1 for t in hindi if not t.get("passed_validation"))

    unsafe = sum(1 for r in results if r["safety_matrix_row"]["reached_patient"] and r["safety_matrix_row"]["llm_made_error"])

    all_latencies = []
    for r in results:
        for stage in ("extraction", "generation"):
            d = r.get(stage)
            if d and d.get("latency_ms"):
                all_latencies.append(d["latency_ms"])
        for t in r["translations"].values():
            if t.get("latency_ms"):
                all_latencies.append(t["latency_ms"])
    stats = latency_stats(all_latencies)

    total_in = total_out = 0
    for r in results:
        for stage in ("extraction", "generation"):
            d = r.get(stage)
            usage = d.get("token_usage") if d else None
            if not usage:
                continue
            total_in += usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
            total_out += usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        for t in r["translations"].values():
            usage = t.get("token_usage")
            if not usage:
                continue
            total_in += usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
            total_out += usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0

    cost = estimate_cost_usd(data["provider"], data["model"], total_in, total_out)
    cost_per_100 = f"${(cost / n) * 100:.3f}" if cost is not None and n else "n/a"
    if data["provider"] == "ollama":
        cost_per_100 = "$0.00 (local — hardware cost not captured)"

    return {
        "Extraction accuracy": f"{100 * classification_correct / (len(extraction_ok) or 1):.1f}%",
        "Invented critical facts": str(invented),
        "Clarification accuracy": f"{100 * clarification_correct / n:.1f}%",
        "Generation blocks": f"{len(generation_blocked)}/{len(generation_attempts)}",
        "Telugu translation blocks": f"{telugu_blocked}/{len(telugu)}",
        "Hindi translation blocks": f"{hindi_blocked}/{len(hindi)}",
        "Unsafe patient exposures": str(unsafe),
        "Avg latency (ms)": str(stats["mean"]),
        "p95 latency (ms)": str(stats["p95"]),
        "Cost / 100 instructions": cost_per_100,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", help="Two or more raw results JSON files")
    args = parser.parse_args()

    datasets = [json.loads(Path(p).read_text()) for p in args.reports]
    labels = [_column_label(d) for d in datasets]
    metrics = [_metrics_for(d) for d in datasets]

    print("# SAFEHAVEN -- LLM Provider Evaluation\n")
    header = "| Metric | " + " | ".join(labels) + " |"
    sep = "|---|" + "---|" * len(labels)
    print(header)
    print(sep)
    for key in metrics[0].keys():
        row = " | ".join(m[key] for m in metrics)
        print(f"| {key} | {row} |")


if __name__ == "__main__":
    main()
