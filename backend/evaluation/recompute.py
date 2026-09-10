#!/usr/bin/env python3
"""Recomputes safety_matrix_row for every case in a saved raw results file,
using the CURRENT derive_safety_matrix_row logic — no API calls. Useful after
fixing a bug in the grading/derivation logic itself (as opposed to the
underlying model behavior), so a correction doesn't require re-spending API
budget on cases whose raw extraction/generation/translation data is unchanged.
"""

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from runner import derive_safety_matrix_row  # noqa: E402
from report import generate_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_json", help="Path to evaluation/reports/<provider>-<timestamp>.json")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the input file and its .md report")
    args = parser.parse_args()

    path = Path(args.results_json)
    data = json.loads(path.read_text())

    for r in data["results"]:
        r["safety_matrix_row"] = derive_safety_matrix_row(
            r["extraction_grading"], r["completeness"], r["generation"], r["translations"]
        )

    out_path = path if args.in_place else path.with_name(path.stem + "-recomputed.json")
    out_path.write_text(json.dumps(data, indent=2, default=str))

    report_text = generate_report(data)
    report_path = out_path.with_suffix(".md")
    report_path.write_text(report_text)

    print(f"Recomputed results written to {out_path}")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
