#!/usr/bin/env python3
"""Step 10 evaluation runner: exercises a REAL LLM provider (OpenAI or
Anthropic) against the synthetic case set in evaluation/cases.json, running
the exact same extraction/generation/translation service functions and
deterministic validators the application itself uses (never a separate
evaluation-only reimplementation of that logic).

Usage:
    python evaluation/runner.py --provider openai --model gpt-4o-mini
    python evaluation/runner.py --provider anthropic --model claude-sonnet-5
    python evaluation/runner.py --provider both
    python evaluation/runner.py --provider openai --limit 5          # smoke test
    python evaluation/runner.py --provider openai --skip-translation # cheaper/faster

The API key is read from the OPENAI_API_KEY / ANTHROPIC_API_KEY environment
variable (never from this repo's app .env, never printed, never written to
the output report). This script does not touch the application's own
database or settings, and does not use any real patient data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ai.extraction_service import run_extraction  # noqa: E402
from app.ai.generation_service import run_generation  # noqa: E402
from app.ai.provider import ExtractionProviderError, LLMProvider  # noqa: E402
from app.ai.translation_service import run_translation  # noqa: E402
from app.instructions.models import InstructionType  # noqa: E402
from app.patients.models import Language  # noqa: E402
from app.validation.completeness import evaluate_completeness  # noqa: E402
from app.validation.fact_preservation import validate_fact_preservation  # noqa: E402
from app.validation.normalization import normalize_facts  # noqa: E402
from app.validation.translation_preservation import validate_translation_preservation  # noqa: E402

from metrics import (  # noqa: E402
    FailureType,
    compare_case_facts,
    critical_fields_for_category,
    VERDICT_INCORRECT,
    VERDICT_INVENTED,
    VERDICT_MISSING,
)
from pricing import estimate_cost_usd  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CASES_PATH = EVAL_DIR / "cases.json"
REPORTS_DIR = EVAL_DIR / "reports"

# Curated highest-risk case IDs for the repeated-run nondeterminism check
# (Section 11) — dose-bearing and adversarial cases, where a nondeterministic
# LLM flip is most likely to matter clinically.
CRITICAL_CASE_IDS_FOR_REPEAT = [
    "MED-001", "MED-007", "MED-009", "MED-011", "MED-012", "MED-015",
    "MOB-001", "MOB-004", "MOB-008", "WOUND-003",
]


def resolve_model(provider_name: str, model_arg: str | None) -> str:
    """--model wins if given; otherwise the provider's own env var (so the same
    OPENAI_MODEL/ANTHROPIC_MODEL config the rest of the app would use also
    governs the evaluation runner, per Step 10's "model must be configurable,
    not hardcoded" requirement); otherwise a safe, cheap default."""
    if model_arg:
        return model_arg
    if provider_name == "openai":
        return os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    if provider_name == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5"
    if provider_name == "ollama":
        return os.environ.get("OLLAMA_MODEL") or "qwen3.5:9b"
    return "mock-extraction-v1"


def build_provider(provider_name: str, model: str) -> LLMProvider:
    if provider_name == "mock":
        # Harness self-test only — verifies the evaluation pipeline's own wiring
        # end to end at zero cost. Not a substitute for a real-provider run; the
        # Step 10 deliverable requires --provider openai/anthropic/both.
        from app.ai.mock_provider import MockLLMProvider

        return MockLLMProvider()
    if provider_name == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=os.environ.get("OPENAI_API_KEY"), model=model)
    if provider_name == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"), model=model)
    if provider_name == "ollama":
        from app.ai.ollama_provider import OllamaProvider

        base_url = os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
        temperature = float(os.environ.get("OLLAMA_TEMPERATURE") or 0.0)
        return OllamaProvider(base_url=base_url, model=model, temperature=temperature)
    raise ValueError(f"Unknown provider {provider_name!r}")


def _token_usage_totals(usage: dict | None, provider_name: str) -> tuple[int, int]:
    if not usage:
        return 0, 0
    if provider_name == "openai":
        return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def run_extraction_stage(provider: LLMProvider, provider_name: str, case: dict) -> dict:
    attempt = run_extraction(provider, case["instruction"])
    if not attempt.succeeded:
        return {
            "succeeded": False,
            "failure_reason": attempt.failure_reason,
            "latency_ms": None,
            "token_usage": None,
        }

    instruction_type = attempt.result.instruction_type
    raw_facts = attempt.result.facts.model_dump()
    ambiguities = attempt.result.ambiguities
    normalized_facts, _changes = normalize_facts(instruction_type, raw_facts)

    return {
        "succeeded": True,
        "instruction_type": instruction_type.value,
        "raw_facts": raw_facts,
        "normalized_facts": normalized_facts,
        "ambiguities": ambiguities,
        "latency_ms": attempt.metadata.latency_ms if attempt.metadata else None,
        "token_usage": attempt.metadata.token_usage if attempt.metadata else None,
        "provider_request_id": attempt.metadata.request_id if attempt.metadata else None,
    }


def grade_extraction(case: dict, extraction: dict) -> dict:
    category = case["category"]
    expected_facts = case["expected_facts"]

    if not extraction["succeeded"]:
        return {
            "classification_correct": False,
            "field_verdicts": {},
            "invented_critical_fields": [],
            "missing_critical_fields": list(critical_fields_for_category(category)),
            "incorrect_critical_fields": [],
            "failure_types": [FailureType.PROVIDER_FAILURE.value, FailureType.EXTRACTION_ERROR.value],
        }

    classification_correct = extraction["instruction_type"] == category
    field_verdicts = compare_case_facts(category, expected_facts, extraction["normalized_facts"])
    critical_fields = critical_fields_for_category(category)

    invented = [f for f, v in field_verdicts.items() if f in critical_fields and v == VERDICT_INVENTED]
    missing = [f for f, v in field_verdicts.items() if f in critical_fields and v == VERDICT_MISSING]
    incorrect = [f for f, v in field_verdicts.items() if f in critical_fields and v == VERDICT_INCORRECT]

    failure_types = []
    if not classification_correct:
        failure_types.append(FailureType.CLASSIFICATION_ERROR.value)
    if invented or incorrect:
        failure_types.append(FailureType.INVENTED_FACT.value)
    if missing:
        failure_types.append(FailureType.MISSED_FACT.value)

    return {
        "classification_correct": classification_correct,
        "field_verdicts": field_verdicts,
        "invented_critical_fields": invented,
        "missing_critical_fields": missing,
        "incorrect_critical_fields": incorrect,
        "failure_types": failure_types,
    }


def run_completeness_stage(case: dict, extraction: dict) -> dict:
    category = case["category"]
    instruction_type = InstructionType(category)

    ground_truth_completeness = evaluate_completeness(
        instruction_type, case["expected_facts"], case.get("expected_ambiguities", [])
    )

    if not extraction["succeeded"]:
        return {
            "actual_completeness_status": None,
            "actual_clarification_required_fields": [],
            "expected_clarification_required_fields": sorted(ground_truth_completeness.clarification_required_fields),
            "clarification_decision_correct": False,
            "failure_types": [],
        }

    actual = evaluate_completeness(
        InstructionType(extraction["instruction_type"]),
        extraction["normalized_facts"],
        extraction["ambiguities"],
    )

    expected_set = set(case["expected_clarification_required"])
    actual_set = set(actual.clarification_required_fields)
    decision_correct = expected_set == actual_set

    failure_types = [] if decision_correct else [FailureType.COMPLETENESS_ERROR.value]

    return {
        "actual_completeness_status": actual.completeness_status.value,
        "actual_clarification_required_fields": sorted(actual.clarification_required_fields),
        "expected_clarification_required_fields": sorted(expected_set),
        "clarification_decision_correct": decision_correct,
        "failure_types": failure_types,
        "_actual_completeness_result": actual,  # consumed by run_case_once, stripped before saving
    }


def run_generation_stage(provider: LLMProvider, case: dict, extraction: dict) -> dict | None:
    instruction_type = InstructionType(extraction["instruction_type"])
    try:
        attempt = run_generation(provider, case["instruction"], extraction["normalized_facts"], instruction_type)
    except ExtractionProviderError as exc:
        return {"attempted": True, "succeeded": False, "failure_reason": str(exc), "passed_validation": False}

    if not attempt.succeeded:
        return {
            "attempted": True,
            "succeeded": False,
            "failure_reason": attempt.failure_reason,
            "passed_validation": False,
            "differences": [],
        }

    reextraction = run_extraction(provider, attempt.patient_text)
    regenerated_instruction_type = None
    regenerated_facts = None
    regenerated_ambiguities = None
    if reextraction.succeeded:
        regenerated_instruction_type = reextraction.result.instruction_type
        regenerated_facts, _changes = normalize_facts(
            regenerated_instruction_type, reextraction.result.facts.model_dump()
        )
        regenerated_ambiguities = reextraction.result.ambiguities

    result = validate_fact_preservation(
        instruction_type=instruction_type,
        original_normalized_facts=extraction["normalized_facts"],
        generated_text=attempt.patient_text,
        regenerated_instruction_type=regenerated_instruction_type,
        regenerated_facts=regenerated_facts,
        regenerated_ambiguities=regenerated_ambiguities,
    )

    failure_types = []
    for diff in result.differences:
        if diff.type == "CHANGED":
            failure_types.append(FailureType.GENERATION_CHANGED_FACT.value)
        elif diff.type == "ADDED":
            failure_types.append(FailureType.GENERATION_ADDED_FACT.value)

    return {
        "attempted": True,
        "succeeded": True,
        "patient_text": attempt.patient_text,
        "passed_validation": result.passed,
        "differences": [{"field": d.field, "type": d.type} for d in result.differences],
        "messages": result.messages,
        "latency_ms": attempt.metadata.latency_ms if attempt.metadata else None,
        "token_usage": attempt.metadata.token_usage if attempt.metadata else None,
        "failure_types": list(dict.fromkeys(failure_types)),
    }


def run_translation_stage(provider: LLMProvider, case: dict, extraction: dict, patient_text: str, language: Language) -> dict:
    instruction_type = InstructionType(extraction["instruction_type"])
    attempt = run_translation(provider, patient_text, language, extraction["normalized_facts"])
    if not attempt.succeeded:
        return {"attempted": True, "succeeded": False, "failure_reason": attempt.failure_reason, "passed_validation": False}

    back_translation = run_translation(provider, attempt.translated_text, Language.ENGLISH, {})
    back_translated_instruction_type = None
    back_translated_facts = None
    back_translated_ambiguities = None
    if back_translation.succeeded:
        reextraction = run_extraction(provider, back_translation.translated_text)
        if reextraction.succeeded:
            back_translated_instruction_type = reextraction.result.instruction_type
            back_translated_facts, _changes = normalize_facts(
                back_translated_instruction_type, reextraction.result.facts.model_dump()
            )
            back_translated_ambiguities = reextraction.result.ambiguities

    result = validate_translation_preservation(
        instruction_type=instruction_type,
        original_normalized_facts=extraction["normalized_facts"],
        translated_text=attempt.translated_text,
        back_translated_instruction_type=back_translated_instruction_type,
        back_translated_facts=back_translated_facts,
        back_translated_ambiguities=back_translated_ambiguities,
    )

    failure_types = [FailureType.TRANSLATION_CHANGED_FACT.value] if not result.passed else []

    return {
        "attempted": True,
        "succeeded": True,
        "passed_validation": result.passed,
        "differences": [{"field": d.field, "type": d.type} for d in result.differences],
        "messages": result.messages,
        "latency_ms": attempt.metadata.latency_ms if attempt.metadata else None,
        "token_usage": attempt.metadata.token_usage if attempt.metadata else None,
        "failure_types": failure_types,
    }


def derive_safety_matrix_row(extraction_grading: dict, completeness: dict, generation: dict | None, translations: dict) -> dict:
    """The Case | LLM error? | SAFEHaven caught it? | Reached patient? row.

    "reached_patient" answers a stage-SCOPED question: did the SPECIFIC
    erroneous content actually become patient-visible? This matters because
    translation is gated per-language in the real app (see
    patient_access/service.py's get_care_plan(): only PASSED translations are
    ever included) — a blocked Telugu translation never reaches the patient
    even if Hindi (or English) passed cleanly alongside it. A naive "did ANY
    output reach the patient" check would wrongly call that case unsafe
    because the CASE overall published something, when the actual broken
    content specifically did not. By construction, a *_CHANGED_FACT/
    *_ADDED_FACT failure type at the generation or translation stage always
    means passed_validation is False for that exact stage/language (the
    validator that detected the difference is the same one that decided
    passed), so those stages are always "blocked", never "unsafe" here — the
    one scenario that CAN reach the patient unsafely is an invented/incorrect
    CRITICAL fact at extraction that nothing downstream compares against
    ground truth (only against itself), so it can propagate consistently."""
    llm_made_error = bool(
        extraction_grading["invented_critical_fields"]
        or extraction_grading["incorrect_critical_fields"]
        or extraction_grading["missing_critical_fields"]
        or not extraction_grading["classification_correct"]
        or not completeness["clarification_decision_correct"]
        or (generation and not generation.get("passed_validation", True))
        or any(not t.get("passed_validation", True) for t in translations.values())
    )

    completeness_passed = completeness.get("actual_completeness_status") == "PASSED"
    generation_passed = generation is not None and generation.get("passed_validation") is True

    stage_of_error = None
    error_reached_patient = False

    if extraction_grading["invented_critical_fields"] or extraction_grading["incorrect_critical_fields"]:
        stage_of_error = "EXTRACTION"
        # Only unsafe if the wrong fact was never caught downstream either —
        # completeness treating it as present (not missing) AND generation's
        # re-extraction agreeing with the (already wrong) original, since
        # fact-preservation only checks internal consistency, not ground truth.
        error_reached_patient = completeness_passed and generation_passed
    elif generation is not None and not generation.get("passed_validation", True):
        stage_of_error = "GENERATION"
        error_reached_patient = False  # the validator that flagged this also blocked it, by construction
    elif any(t.get("attempted") and not t.get("passed_validation", True) for t in translations.values()):
        stage_of_error = "TRANSLATION"
        error_reached_patient = False  # that specific language was blocked, by construction — other languages are unaffected
    elif llm_made_error:
        stage_of_error = "COMPLETENESS_OR_CLASSIFICATION"
        # A wrong clarification/classification decision only matters if it let
        # something through that should have stopped for clinician review.
        error_reached_patient = completeness_passed

    safehaven_caught_it = None
    if llm_made_error:
        safehaven_caught_it = not error_reached_patient

    return {
        "llm_made_error": llm_made_error,
        "safehaven_caught_it": safehaven_caught_it,
        "reached_patient": error_reached_patient if llm_made_error else True,
        "stage_of_error": stage_of_error,
    }


def run_case_once(provider: LLMProvider, provider_name: str, model: str, case: dict, skip_translation: bool) -> dict:
    extraction = run_extraction_stage(provider, provider_name, case)
    extraction_grading = grade_extraction(case, extraction)
    completeness = run_completeness_stage(case, extraction)
    actual_completeness_result = completeness.pop("_actual_completeness_result", None)

    generation = None
    translations: dict[str, dict] = {}

    should_generate = extraction["succeeded"] and completeness["actual_completeness_status"] == "PASSED"
    if should_generate:
        generation = run_generation_stage(provider, case, extraction)
        if not skip_translation and generation and generation.get("passed_validation"):
            for language in (Language.TELUGU, Language.HINDI):
                translations[language.value] = run_translation_stage(
                    provider, case, extraction, generation["patient_text"], language
                )

    safety_row = derive_safety_matrix_row(extraction_grading, completeness, generation, translations)

    all_failure_types = list(
        dict.fromkeys(
            extraction_grading.get("failure_types", [])
            + completeness.get("failure_types", [])
            + (generation.get("failure_types", []) if generation else [])
            + [ft for t in translations.values() for ft in t.get("failure_types", [])]
        )
    )

    return {
        "id": case["id"],
        "category": case["category"],
        "instruction": case["instruction"],
        "notes": case.get("notes"),
        "provider": provider_name,
        "model": model,
        "extraction": extraction,
        "extraction_grading": extraction_grading,
        "completeness": completeness,
        "generation": generation,
        "translations": translations,
        "safety_matrix_row": safety_row,
        "failure_types": all_failure_types,
    }


def run_repeats(provider: LLMProvider, provider_name: str, model: str, case: dict, times: int, skip_translation: bool) -> dict:
    runs = [run_case_once(provider, provider_name, model, case, skip_translation) for _ in range(times)]

    fact_snapshots = [json.dumps(r["extraction"].get("normalized_facts"), sort_keys=True) for r in runs]
    stable_facts = len(set(fact_snapshots)) == 1

    reached_patient_values = {r["safety_matrix_row"]["reached_patient"] for r in runs}
    stable_safety = len(reached_patient_values) == 1
    any_unsafe = any(
        r["safety_matrix_row"]["reached_patient"] and r["safety_matrix_row"]["llm_made_error"] for r in runs
    )
    is_stable = stable_facts and stable_safety

    # "Stable" is about whether repeats AGREE with each other, not whether they
    # happen to be safe -- a case that is *consistently* unsafe on every run is
    # a deterministic accuracy/validator gap (already visible in the main
    # matrix above), not the nondeterminism failure mode this check exists to
    # catch. Only report VARIABLE_AND_UNSAFE when runs actually disagree and at
    # least one of them was unsafe.
    if is_stable and not any_unsafe:
        classification = "STABLE"
    elif is_stable and any_unsafe:
        classification = "STABLE_BUT_CONSISTENTLY_UNSAFE"
    elif not is_stable and any_unsafe:
        classification = "VARIABLE_AND_UNSAFE"
    else:
        classification = "VARIABLE_BUT_BLOCKED_SAFELY"

    return {
        "case_id": case["id"],
        "runs": runs,
        "stable_facts": stable_facts,
        "stable_safety_outcome": stable_safety,
        "classification": classification,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["openai", "anthropic", "ollama", "both", "mock"], required=True)
    parser.add_argument("--model", default=None, help="Override the default model for the chosen provider")
    parser.add_argument("--cases", default=str(CASES_PATH))
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases (smoke test)")
    parser.add_argument("--skip-translation", action="store_true")
    parser.add_argument("--skip-repeats", action="store_true")
    parser.add_argument("--repeat-times", type=int, default=3)
    args = parser.parse_args()

    providers_to_run = ["openai", "anthropic"] if args.provider == "both" else [args.provider]

    cases = json.loads(Path(args.cases).read_text())
    if args.limit:
        cases = cases[: args.limit]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for provider_name in providers_to_run:
        print(f"\n=== Running evaluation against {provider_name} ===")
        model = resolve_model(provider_name, args.model)
        print(f"    model: {model}")
        try:
            provider = build_provider(provider_name, model)
        except ExtractionProviderError as exc:
            print(f"SKIPPING {provider_name}: {exc}")
            continue

        generation_params = provider.generation_params() if hasattr(provider, "generation_params") else {}
        print(f"    generation params: {generation_params}")

        results = []
        started_at = time.monotonic()
        for i, case in enumerate(cases, start=1):
            print(f"  [{i}/{len(cases)}] {case['id']} ({case['category']})...", end=" ", flush=True)
            result = run_case_once(provider, provider_name, model, case, args.skip_translation)
            results.append(result)
            print(
                "error"
                if result["safety_matrix_row"]["llm_made_error"]
                else "ok"
            )
        elapsed_s = time.monotonic() - started_at

        repeat_results = []
        if not args.skip_repeats:
            repeat_case_ids = [cid for cid in CRITICAL_CASE_IDS_FOR_REPEAT if any(c["id"] == cid for c in cases)]
            for cid in repeat_case_ids:
                case = next(c for c in cases if c["id"] == cid)
                print(f"  Repeating {cid} x{args.repeat_times} for stability check...")
                # Translation is already exercised once per case in the main pass
                # above; repeating it here too would triple translation cost for
                # marginal extra insight, since Section 11's stability concern is
                # about extraction/generation nondeterminism (dose handling),
                # not translation.
                repeat_results.append(
                    run_repeats(provider, provider_name, model, case, args.repeat_times, skip_translation=True)
                )

        output = {
            "provider": provider_name,
            "model": model,
            "generation_params": generation_params,
            "run_at": timestamp,
            "case_count": len(cases),
            "elapsed_seconds": round(elapsed_s, 1),
            "results": results,
            "repeat_results": repeat_results,
        }

        out_path = REPORTS_DIR / f"{provider_name}-{timestamp}.json"
        out_path.write_text(json.dumps(output, indent=2, default=str))
        print(f"Raw results written to {out_path}")

        from report import generate_report  # local import to avoid a cycle at module load time

        report_text = generate_report(output)
        report_path = REPORTS_DIR / f"{provider_name}-{timestamp}.md"
        report_path.write_text(report_text)
        print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
