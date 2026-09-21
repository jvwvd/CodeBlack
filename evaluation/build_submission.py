"""
Projects internal EmailResult dicts into the organizer submission format
(PROJECT_RULES.md section 13). This file only converts and checks values for
internal consistency; it never re-derives category/status/defect decisions
and never touches ground_truth.json.

Usage:
    python evaluation/build_submission.py --results evaluation/output/results.json \
        --data-dir data --out evaluation/output/submission.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VALID_CATEGORIES = {"BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"}
VALID_STATUSES = {"OK", "MISMATCH", "NEEDS_REVIEW"}
VALID_REVIEW_REASONS = {"wrong_doc_type", "missing_attachment", "unreadable", "missing_value"}
VALID_DEFECT_FIELDS = {
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
}

SUBMISSION_KEYS = ("category", "status", "review_reason", "defect_fields", "has_defect")


def project_result(result: dict) -> dict:
    """
    Project one EmailResult dict down to exactly the 5 organizer submission
    keys. Values are copied as-is, never changed.
    """
    return {key: result.get(key) for key in SUBMISSION_KEYS}


def _check_entry(email_id: str, entry: dict) -> list[str]:
    warnings: list[str] = []

    category = entry.get("category")
    if category not in VALID_CATEGORIES:
        warnings.append(f"{email_id}: invalid category {category!r}")

    status = entry.get("status")
    if status not in VALID_STATUSES:
        warnings.append(f"{email_id}: invalid status {status!r}")

    review_reason = entry.get("review_reason")
    if review_reason is not None and review_reason not in VALID_REVIEW_REASONS:
        warnings.append(f"{email_id}: invalid review_reason {review_reason!r}")

    if entry.get("has_defect") and status != "MISMATCH":
        warnings.append(f"{email_id}: has_defect true but status is not MISMATCH")

    defect_fields = entry.get("defect_fields") or []
    invalid_fields = [f for f in defect_fields if f not in VALID_DEFECT_FIELDS]
    if invalid_fields:
        warnings.append(f"{email_id}: defect_fields contains unknown field(s) {invalid_fields}")

    if status == "NEEDS_REVIEW" and review_reason is None:
        warnings.append(f"{email_id}: NEEDS_REVIEW without a review_reason")

    return warnings


def _load_sample_submission(data_dir: str | Path) -> dict:
    path = Path(data_dir) / "sample_submission.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def build_submission(
    results: list[dict],
    email_ids: list[str],
    data_dir: str | Path = "data",
) -> tuple[dict, list[str]]:
    """
    Build the full organizer submission for every ID in email_ids.

    Never repairs a value; only reports inconsistencies as warnings. IDs with
    no result fall back to that email's entry in <data_dir>/sample_submission.json.
    """
    sample_submission = _load_sample_submission(data_dir)
    results_by_id = {r["email_id"]: r for r in results if "email_id" in r}
    submission: dict[str, dict] = {}
    warnings: list[str] = []

    for email_id in sorted(email_ids):
        result = results_by_id.get(email_id)
        if result is None:
            fallback = sample_submission.get(email_id, {})
            submission[email_id] = {key: fallback.get(key) for key in SUBMISSION_KEYS}
            warnings.append(f"{email_id}: no result")
            continue

        entry = project_result(result)
        submission[email_id] = entry
        warnings.extend(_check_entry(email_id, entry))

    return submission, warnings


def _load_results(results_path: Path) -> list[dict]:
    if not results_path.exists():
        return []
    with results_path.open(encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    return json.loads(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Project EmailResult dicts into the organizer submission format")
    parser.add_argument("--results", default="evaluation/output/results.json")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--out", default="evaluation/output/submission.json")
    args = parser.parse_args()

    results_path = Path(args.results)
    out_path = Path(args.out)

    results = _load_results(results_path)
    sample_submission = _load_sample_submission(args.data_dir)
    email_ids = list(sample_submission.keys())

    submission, warnings = build_submission(results, email_ids, data_dir=args.data_dir)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2)

    print(f"Entries: {len(submission)}")
    print(f"Warnings: {len(warnings)}")
    for w in warnings[:10]:
        print(f"  - {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
