"""
Calls the pipeline over the organizer inbox and saves whatever it returns.
No classification, extraction, or comparison logic lives here (PROJECT_RULES.md
section 8) - this script only orchestrates process_email() and persists its
output. Never touches ground_truth.json (PROJECT_RULES.md section 19).

Usage:
    python evaluation/run_all.py --stub
    python evaluation/run_all.py --ids email_004 --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
os.chdir(_REPO_ROOT)

_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from loader import Inbox  # noqa: E402  (organizer's frozen loader, unmodified)
from models import EmailResult  # noqa: E402  (pydantic only, safe for --stub)

RETRY_WAITS = [2, 4]


def _load_opencode_settings() -> tuple[bool, bool]:
    """
    backend/config.py builds its Settings() at import time, resolving its
    env_file=".env" relative to the current working directory. Since this
    script chdir's to the repo root, backend/.env would otherwise never be
    found. Temporarily switch to backend/ for this one import so
    pydantic-settings picks it up; config's module (and its already-built
    settings object) stays cached in sys.modules afterwards.
    """
    original_cwd = Path.cwd()
    try:
        os.chdir(_BACKEND_DIR)
        import config  # noqa: PLC0415  (backend/config.py, flat import)
    finally:
        os.chdir(original_cwd)
    return bool(config.settings.OPENCODE_API_KEY), bool(config.settings.OPENCODE_MODEL)


def _import_process_email():
    """Lazy import: only pulled in for a real run, never for --stub."""
    original_cwd = Path.cwd()
    try:
        os.chdir(_BACKEND_DIR)
        from pipeline.run import process_email
    finally:
        os.chdir(original_cwd)
    return process_email


def _make_stub():
    def stub_process_email(email: dict, attachment_bytes=None):
        return EmailResult(email_id=email["email_id"], category="GENERAL")
    return stub_process_email


def _result_to_dict(result) -> dict:
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result.dict()


def _process_with_retries(process_email, email: dict, retries: int) -> dict:
    attempts = retries + 1
    last_error = None
    start = time.time()
    for attempt in range(attempts):
        try:
            result = process_email(email)
            seconds = time.time() - start
            return {
                "ok": True,
                "email_id": email["email_id"],
                "result": _result_to_dict(result),
                "seconds": seconds,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts - 1:
                time.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)])
    seconds = time.time() - start
    return {
        "ok": False,
        "email_id": email["email_id"],
        "error": last_error,
        "seconds": seconds,
    }


def _load_existing(out_path: Path) -> list[dict]:
    if not out_path.exists():
        return []
    content = out_path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return json.loads(content)


def _save(out_path: Path, results_by_id: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [results_by_id[eid] for eid in sorted(results_by_id.keys())]
    out_path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run process_email over the organizer inbox")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--out", default="evaluation/output/results.json")
    parser.add_argument("--ids", default=None, help="comma separated email IDs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stub", action="store_true")
    args = parser.parse_args()

    key_loaded, model_set = _load_opencode_settings()
    print(f"OpenCode key loaded: {key_loaded}")
    print(f"OpenCode model set: {model_set}")

    out_path = Path(args.out)

    inbox = Inbox(args.data_dir)
    all_emails = list(inbox)
    emails_by_id = {e["email_id"]: e for e in all_emails}

    if args.ids:
        wanted = [e.strip() for e in args.ids.split(",") if e.strip()]
        missing = [e for e in wanted if e not in emails_by_id]
        if missing:
            print(f"Unknown email IDs requested: {missing}")
            return 1
        selected_ids = wanted
    else:
        selected_ids = sorted(emails_by_id.keys())

    if args.limit is not None:
        selected_ids = selected_ids[: args.limit]

    existing_results = _load_existing(out_path)
    results_by_id = {r["email_id"]: r for r in existing_results if "email_id" in r}

    if args.force:
        to_process = list(selected_ids)
    else:
        to_process = [eid for eid in selected_ids if eid not in results_by_id]

    if args.stub:
        process_email = _make_stub()
    else:
        try:
            process_email = _import_process_email()
        except Exception as exc:
            print("Failed to import process_email from pipeline.run.")
            print(f"Exception: {type(exc).__name__}: {exc}")
            return 1

    n_total = len(selected_ids)
    k = 0
    run_seconds: list[float] = []
    error_ids: list[str] = []
    processed_since_save = 0

    for email_id in selected_ids:
        if email_id not in to_process:
            k += 1
            r = results_by_id[email_id]
            print(
                f"[{k}/{n_total}] {email_id} {r.get('category')}/{r.get('status')} "
                f"(resumed)",
                flush=True,
            )

    if to_process:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_process_with_retries, process_email, emails_by_id[eid], args.retries): eid
                for eid in to_process
            }
            for future in as_completed(futures):
                record = future.result()
                k += 1
                if record["ok"]:
                    results_by_id[record["email_id"]] = record["result"]
                    run_seconds.append(record["seconds"])
                    r = record["result"]
                    print(
                        f"[{k}/{n_total}] {record['email_id']} {r.get('category')}/{r.get('status')} "
                        f"{record['seconds']:.2f}s",
                        flush=True,
                    )
                else:
                    error_ids.append(record["email_id"])
                    run_seconds.append(record["seconds"])
                    print(
                        f"[{k}/{n_total}] {record['email_id']} ERROR: {record['error']} "
                        f"{record['seconds']:.2f}s",
                        flush=True,
                    )

                processed_since_save += 1
                if processed_since_save >= 10:
                    _save(out_path, results_by_id)
                    processed_since_save = 0

    _save(out_path, results_by_id)

    category_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for r in results_by_id.values():
        category_counts[r.get("category")] = category_counts.get(r.get("category"), 0) + 1
        status_counts[r.get("status")] = status_counts.get(r.get("status"), 0) + 1

    avg_seconds = (sum(run_seconds) / len(run_seconds)) if run_seconds else 0.0

    print("--- Summary ---")
    print(f"Total emails in results file: {len(results_by_id)}")
    print(f"Category counts: {category_counts}")
    print(f"Status counts: {status_counts}")
    print(f"Errors this run: {len(error_ids)}")
    if error_ids:
        print(f"Error IDs: {error_ids}")
    print(f"Average seconds per email (this run): {avg_seconds:.4f}")
    print(
        "Next: python evaluation/build_submission.py --results evaluation/output/results.json "
        "--data-dir data --out evaluation/output/submission.json"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
