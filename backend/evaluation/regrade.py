#!/usr/bin/env python3
"""Re-grades a saved raw results file against the CURRENT evaluation/cases.json
ground truth, using the ALREADY-SAVED raw extraction/generation/translation
outputs — no new API calls. Use this after correcting a ground-truth
authoring mistake (as opposed to a change in model behavior), so a correction
doesn't require re-spending API budget on cases whose real model output is
unchanged.
"""

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from runner import derive_safety_matrix_row, grade_extraction  # noqa: E402
from report import generate_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_json", help="Path to evaluation/reports/<provider>-<timestamp>.json")
    parser.add_argument("--cases", default=str(EVAL_DIR / "cases.json"))
    parser.add_argument("--in-place", action="store_true", help="Overwrite the input file and its .md report")
    args = parser.parse_args()

    cases_by_id = {c["id"]: c for c in json.loads(Path(args.cases).read_text())}

    path = Path(args.results_json)
    data = json.loads(path.read_text())

    for r in data["results"]:
        case = cases_by_id[r["id"]]
        r["notes"] = case.get("notes")
        r["extraction_grading"] = grade_extraction(case, r["extraction"])
        # completeness's clarification_decision_correct depends only on the
        # already-saved actual_clarification_required_fields vs the case's
        # (possibly updated) expected_clarification_required — no re-derivation
        # needed unless expected_facts changed what completeness itself would
        # compute, which only ever affects grading (ground truth), not the
        # model's own real completeness decision already recorded.
        r["safety_matrix_row"] = derive_safety_matrix_row(
            r["extraction_grading"], r["completeness"], r["generation"], r["translations"]
        )

    out_path = path if args.in_place else path.with_name(path.stem + "-regraded.json")
    out_path.write_text(json.dumps(data, indent=2, default=str))

    report_text = generate_report(data)
    report_path = out_path.with_suffix(".md")
    report_path.write_text(report_text)

    print(f"Regraded results written to {out_path}")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
