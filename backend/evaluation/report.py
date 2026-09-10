"""Turns a raw results dict (as produced by runner.py, or loaded back from a
saved evaluation/reports/<provider>-<timestamp>.json) into the human-readable
Markdown report — including the full Case | LLM error? | Caught? | Reached
patient? matrix, and every failed case listed individually. Kept separate from
runner.py so a report can be regenerated (e.g. after tweaking formatting)
without re-running any API calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from metrics import latency_stats  # noqa: E402
from pricing import estimate_cost_usd  # noqa: E402


def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{100 * numerator / denominator:.1f}%"


def _collect_token_totals(results: list[dict], provider: str) -> tuple[int, int]:
    total_in = total_out = 0
    for r in results:
        for stage in ("extraction", "generation"):
            data = r.get(stage)
            if not data:
                continue
            usage = data.get("token_usage")
            if not usage:
                continue
            if provider == "openai":
                total_in += usage.get("prompt_tokens", 0)
                total_out += usage.get("completion_tokens", 0)
            else:
                total_in += usage.get("input_tokens", 0)
                total_out += usage.get("output_tokens", 0)
        for t in r.get("translations", {}).values():
            usage = t.get("token_usage")
            if not usage:
                continue
            if provider == "openai":
                total_in += usage.get("prompt_tokens", 0)
                total_out += usage.get("completion_tokens", 0)
            else:
                total_in += usage.get("input_tokens", 0)
                total_out += usage.get("output_tokens", 0)
    return total_in, total_out


def generate_report(output: dict) -> str:
    provider = output["provider"]
    model = output["model"]
    results = output["results"]
    n = len(results)

    extraction_ok = [r for r in results if r["extraction"]["succeeded"]]
    classification_correct = sum(1 for r in extraction_ok if r["extraction_grading"]["classification_correct"])
    invented_critical_total = sum(len(r["extraction_grading"]["invented_critical_fields"]) for r in results)
    incorrect_critical_total = sum(len(r["extraction_grading"]["incorrect_critical_fields"]) for r in results)
    missing_critical_total = sum(len(r["extraction_grading"]["missing_critical_fields"]) for r in results)
    critical_fact_clean_cases = sum(
        1
        for r in results
        if not r["extraction_grading"]["invented_critical_fields"]
        and not r["extraction_grading"]["incorrect_critical_fields"]
        and not r["extraction_grading"]["missing_critical_fields"]
    )
    clarification_correct = sum(1 for r in results if r["completeness"]["clarification_decision_correct"])

    generation_attempts = [r for r in results if r["generation"] is not None]
    generation_passed = [r for r in generation_attempts if r["generation"].get("passed_validation")]
    generation_blocked = [r for r in generation_attempts if not r["generation"].get("passed_validation")]

    translation_attempts = [
        (r["id"], lang, t) for r in results for lang, t in r["translations"].items() if t.get("attempted")
    ]
    translation_blocked = [(cid, lang, t) for cid, lang, t in translation_attempts if not t.get("passed_validation")]

    unsafe_reaching_patient = [r for r in results if r["safety_matrix_row"]["reached_patient"] and r["safety_matrix_row"]["llm_made_error"]]

    extraction_latencies = [r["extraction"]["latency_ms"] for r in results if r["extraction"].get("latency_ms")]
    generation_latencies = [r["generation"]["latency_ms"] for r in generation_attempts if r["generation"].get("latency_ms")]
    translation_latencies = [t["latency_ms"] for _, _, t in translation_attempts if t.get("latency_ms")]

    total_in, total_out = _collect_token_totals(results, provider)
    cost_per_instruction = None
    total_cost = estimate_cost_usd(provider, model, total_in, total_out)
    if total_cost is not None and n:
        cost_per_instruction = total_cost / n

    lines: list[str] = []
    lines.append("# SAFEHAVEN AI -- Module 1 Evaluation\n")
    lines.append(f"- Provider: {provider}")
    lines.append(f"- Model: {model}")
    lines.append("- Prompt versions: health-literacy-extraction-v2, health-literacy-generation-v1, health-literacy-translation-v1")
    params = output.get("generation_params") or {}
    if params:
        lines.append(
            f"- Generation params: temperature={params.get('temperature')}, "
            f"reasoning_effort={params.get('reasoning_effort')}"
        )
    lines.append(f"- Date: {output['run_at']}")
    lines.append(f"- Test cases: {n}")
    lines.append(f"- Wall-clock time: {output['elapsed_seconds']}s\n")

    lines.append("## Headline safety result\n")
    lines.append(f"**Unsafe outputs reaching the patient layer: {len(unsafe_reaching_patient)}**\n")
    if unsafe_reaching_patient:
        lines.append("⚠️ At least one case where the model erred AND it was not caught before the patient layer. See matrix below.\n")
    else:
        lines.append("Every case where the model made a clinically significant error was intercepted before the patient layer (or the model made no error).\n")

    lines.append("## Extraction accuracy\n")
    lines.append(f"- Extraction succeeded: {len(extraction_ok)}/{n} ({_pct(len(extraction_ok), n)})")
    lines.append(f"- Instruction-type classification accuracy: {_pct(classification_correct, len(extraction_ok) or 1)} ({classification_correct}/{len(extraction_ok)})")
    lines.append(f"- Clarification decision accuracy (vs ground truth): {_pct(clarification_correct, n)} ({clarification_correct}/{n})")
    lines.append(f"- Cases with zero invented/incorrect/missing CRITICAL facts: {_pct(critical_fact_clean_cases, n)} ({critical_fact_clean_cases}/{n})")
    lines.append(f"- **Invented critical facts (total occurrences): {invented_critical_total}**")
    lines.append(f"- Incorrect critical facts (total occurrences): {incorrect_critical_total}")
    lines.append(f"- Missing critical facts (total occurrences, should have been extracted): {missing_critical_total}\n")

    lines.append("## Generation (patient-friendly simplification)\n")
    lines.append(f"- Generation attempted: {len(generation_attempts)}")
    lines.append(f"- Safety validation passed: {len(generation_passed)}")
    lines.append(f"- Safety validation BLOCKED: {len(generation_blocked)}\n")

    lines.append("## Translation\n")
    lines.append(f"- Translation attempts: {len(translation_attempts)}")
    lines.append(f"- Translation validation BLOCKED: {len(translation_blocked)}\n")

    lines.append("## Latency (prototype measurement, not a production benchmark)\n")
    for label, values in (("extraction", extraction_latencies), ("generation", generation_latencies), ("translation", translation_latencies)):
        stats = latency_stats(values)
        lines.append(
            f"- {label}: mean={stats['mean']}ms median={stats['median']}ms p95={stats['p95']}ms max={stats['max']}ms (n={stats['count']})"
        )
    lines.append("")

    lines.append("## Token usage / estimated cost\n")
    lines.append(f"- Total input tokens: {total_in}")
    lines.append(f"- Total output tokens: {total_out}")
    lines.append(f"- Average tokens/instruction: {round((total_in + total_out) / n, 1) if n else 'n/a'}")
    if provider == "ollama":
        lines.append("- Estimated API cost/instruction: $0.00 (local inference)")
        lines.append(
            "- NOTE: $0 API cost does not mean $0 cost — local compute/hardware "
            "(RAM, disk, power, and the machine's time) is a real cost this figure does not capture."
        )
    elif total_cost is not None:
        lines.append(f"- Estimated cost/instruction: ${cost_per_instruction:.5f}")
        lines.append(f"- Estimated cost/100 instructions: ${cost_per_instruction * 100:.3f}")
    else:
        lines.append("- Estimated cost: unavailable (model not in evaluation/pricing.py -- add it there, not here)")
    lines.append("")

    lines.append("## Safety matrix\n")
    lines.append("| Case | LLM made error? | SAFEHAVEN caught it? | Reached patient? | Stage |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        row = r["safety_matrix_row"]
        error = "Yes" if row["llm_made_error"] else "No"
        caught = "—" if row["safehaven_caught_it"] is None else ("✅" if row["safehaven_caught_it"] else "❌ NOT CAUGHT")
        reached = "❌ unsafe" if (row["reached_patient"] and row["llm_made_error"]) else ("✅ safe" if not row["llm_made_error"] else "🚫 blocked")
        lines.append(f"| {r['id']} | {error} | {caught} | {reached} | {row['stage_of_error'] or '—'} |")
    lines.append("")

    lines.append("## Repeated-run stability (highest-risk cases)\n")
    for rep in output.get("repeat_results", []):
        lines.append(f"- {rep['case_id']}: **{rep['classification']}** (stable facts: {rep['stable_facts']}, stable safety outcome: {rep['stable_safety_outcome']})")
    lines.append("")

    lines.append("## Every failed case, individually\n")
    failed = [r for r in results if r["failure_types"]]
    if not failed:
        lines.append("No failures.\n")
    else:
        for r in failed:
            lines.append(f"### {r['id']} — {r['category']}")
            lines.append(f"- Instruction: {r['instruction']!r}")
            lines.append(f"- Failure types: {', '.join(r['failure_types'])}")
            if r.get("notes"):
                lines.append(f"- Ground-truth note (authored before this run): {r['notes']}")
            if r["extraction_grading"]["invented_critical_fields"]:
                lines.append(f"- Invented critical fields: {r['extraction_grading']['invented_critical_fields']}")
            if r["extraction_grading"]["incorrect_critical_fields"]:
                lines.append(f"- Incorrect critical fields: {r['extraction_grading']['incorrect_critical_fields']}")
            if r["extraction_grading"]["missing_critical_fields"]:
                lines.append(f"- Missing critical fields: {r['extraction_grading']['missing_critical_fields']}")
            if not r["completeness"]["clarification_decision_correct"]:
                lines.append(
                    f"- Clarification decision mismatch: expected {r['completeness']['expected_clarification_required_fields']}, "
                    f"got {r['completeness']['actual_clarification_required_fields']}"
                )
            if r["generation"] and not r["generation"].get("passed_validation"):
                lines.append(f"- Generation blocked: {r['generation'].get('messages')}")
            for lang, t in r["translations"].items():
                if t.get("attempted") and not t.get("passed_validation"):
                    lines.append(f"- Translation blocked ({lang}): {t.get('messages')}")
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate a Markdown report from a saved raw results JSON file.")
    parser.add_argument("results_json", help="Path to evaluation/reports/<provider>-<timestamp>.json")
    args = parser.parse_args()

    raw = json.loads(Path(args.results_json).read_text())
    print(generate_report(raw))
