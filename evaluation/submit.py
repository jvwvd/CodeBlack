"""
Submits an organizer-format submission to the scoring server via POST /submit
and prints the scoreboard. Never touches ground_truth.json (PROJECT_RULES.md
section 19) - scoring happens entirely server-side; this script only formats
what the server returns.

Usage:
    python evaluation/submit.py --url http://localhost:8080 --save
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from loader import Inbox  # noqa: E402  (organizer's frozen loader, unmodified)

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]


def _git_short_hash() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


def _print_scoreboard(result: dict) -> None:
    s1 = result.get("stage1", {})
    s3 = result.get("stage3", {})
    rel = result.get("reliability", {})
    e2e = result.get("end_to_end", {})
    weights = result.get("weights", {})
    final_score = result.get("final_score")

    print("=== Final score ===")
    print(f"final_score = {final_score}")
    print(f"weights     = {weights}")
    print()

    print("=== Stage 1: classification ===")
    print(f"accuracy = {s1.get('accuracy')}  macro_f1 = {s1.get('macro_f1')}")
    rule_pct = s1.get("rule_pct")
    if rule_pct is not None:
        print(f"decided_by rule share = {rule_pct}")
    rows = []
    for cat in CATEGORIES:
        per = s1.get("per", {}).get(cat, {"tp": 0, "fp": 0, "fn": 0})
        p, r, f = _prf(per.get("tp", 0), per.get("fp", 0), per.get("fn", 0))
        rows.append([cat, f"{p:.3f}", f"{r:.3f}", f"{f:.3f}"])
    _print_table(["category", "precision", "recall", "f1"], rows)
    print()

    print("Confusion matrix (rows = actual, cols = predicted):")
    confusion = s1.get("confusion", {})
    header = ["actual\\pred"] + CATEGORIES
    rows = []
    for actual in CATEGORIES:
        row = [actual]
        for pred in CATEGORIES:
            row.append(str(confusion.get(actual, {}).get(pred, 0)))
        rows.append(row)
    _print_table(header, rows)
    print()

    print("=== Stage 3: defect detection ===")
    rows = [[
        f"{s3.get('defect_precision'):.3f}",
        f"{s3.get('defect_recall'):.3f}",
        f"{s3.get('defect_f1'):.3f}",
        f"{s3.get('field_f1'):.3f}",
        f"{s3.get('exact_match_rate'):.3f}",
        str(s3.get("doc_total")),
    ]]
    _print_table(
        ["defect_p", "defect_r", "defect_f1", "field_f1", "exact_match", "doc_total"],
        rows,
    )
    print()

    print("=== Reliability (escalation) ===")
    rows = [[
        f"{rel.get('escalation_precision'):.3f}",
        f"{rel.get('escalation_recall'):.3f}",
        f"{rel.get('escalation_f1'):.3f}",
        str(rel.get("gold_review")),
        str(rel.get("pred_review")),
    ]]
    _print_table(
        ["esc_p", "esc_r", "esc_f1", "gold_review", "pred_review"],
        rows,
    )
    per_reason = rel.get("per_reason")
    if per_reason:
        print()
        print("Per-reason escalation (reason: caught/total):")
        rows = [[reason, str(v.get("caught")), str(v.get("total"))] for reason, v in per_reason.items()]
        _print_table(["reason", "caught", "total"], rows)
    print()

    print("=== End-to-end ===")
    rows = [[str(e2e.get("success")), str(e2e.get("total")), f"{e2e.get('rate'):.3f}"]]
    _print_table(["success", "total", "rate"], rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a submission to the scoring server")
    parser.add_argument("--submission", default="evaluation/output/submission.json")
    parser.add_argument(
        "--url",
        default=os.environ.get("SCORING_SERVER_URL", "http://localhost:8080"),
    )
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    submission_path = Path(args.submission)
    if not submission_path.exists():
        print(f"Cannot find submission at {submission_path}")
        return 1

    with submission_path.open(encoding="utf-8") as f:
        submission = json.load(f)

    if len(submission) != 520:
        print(
            f"Submission has {len(submission)} entries, expected 520. "
            "Refusing to submit an incomplete submission."
        )
        return 1

    inbox = Inbox(args.url)

    try:
        result = inbox.submit(submission)
    except urllib.error.URLError as exc:
        print(f"Could not reach scoring server at {args.url}: {exc}")
        return 1
    except OSError as exc:
        print(f"Could not reach scoring server at {args.url}: {exc}")
        return 1

    _print_scoreboard(result)

    if args.save:
        out_dir = submission_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        score_path = out_dir / f"score_{timestamp}.json"
        with score_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)

        s1 = result.get("stage1", {})
        s3 = result.get("stage3", {})
        rel = result.get("reliability", {})
        e2e = result.get("end_to_end", {})
        final_score = result.get("final_score")
        git_hash = _git_short_hash()

        history_path = out_dir / "score_history.csv"
        is_new = not history_path.exists()
        previous_score = None
        if history_path.exists():
            with history_path.open(encoding="utf-8", newline="") as f:
                reader = list(csv.DictReader(f))
                if reader:
                    previous_score = float(reader[-1]["final_score"])

        with history_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow([
                    "timestamp", "git_hash", "final_score", "macro_f1",
                    "defect_f1", "end_to_end_rate", "escalation_f1",
                ])
            writer.writerow([
                timestamp,
                git_hash or "",
                final_score,
                s1.get("macro_f1"),
                s3.get("defect_f1"),
                e2e.get("rate"),
                rel.get("escalation_f1"),
            ])

        print()
        print(f"Saved scoreboard to {score_path}")
        print(f"Appended row to {history_path}")
        if previous_score is not None:
            delta = final_score - previous_score
            print(f"Change vs previous run: {delta:+.6f} (prev {previous_score}, now {final_score})")
        else:
            print("No previous run to compare against.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
