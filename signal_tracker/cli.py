"""Command line entry point. Run `python track.py --help` for options."""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .report import post_to_slack, slack_message, write_csv, write_markdown
from .scoring import AccountResult, Scorer, rank
from .sources import SourceError, get_jobs

ROOT = Path(__file__).resolve().parent.parent


def read_accounts(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("company") or "").strip()]
    required = {"company", "job_board", "board_token"}
    if rows and not required.issubset(rows[0].keys()):
        sys.exit(f"Accounts file needs these columns: {', '.join(sorted(required))}")
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Rank target accounts by hiring-based buying signals.")
    p.add_argument("--accounts", default="accounts.csv", help="CSV of target accounts (default: accounts.csv)")
    p.add_argument("--config", default=str(ROOT / "config" / "signals.json"), help="Signal keywords and weights")
    p.add_argument("--out", default="output", help="Folder for the CSV and Markdown report")
    p.add_argument("--demo", action="store_true", help="Use the saved sample data in examples/demo (no internet)")
    p.add_argument("--slack", action="store_true", help="Post the top accounts to Slack (needs SLACK_WEBHOOK_URL)")
    p.add_argument("--today", help=argparse.SUPPRESS)  # fixed date for demo runs and tests
    args = p.parse_args(argv)

    accounts_path = Path(args.accounts)
    if args.demo and not accounts_path.exists():
        accounts_path = ROOT / "examples" / "demo" / "accounts.csv"
    if not accounts_path.exists():
        sys.exit(f"Can't find {accounts_path}. Copy accounts.example.csv to accounts.csv and add your accounts.")

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    today = datetime.fromisoformat(args.today).replace(tzinfo=timezone.utc) if args.today else None
    if args.demo and not today:
        today = datetime(2026, 11, 15, tzinfo=timezone.utc)  # matches the sample data
    scorer = Scorer(config, today=today)
    demo_dir = ROOT / "examples" / "demo" if args.demo else None

    results = []
    accounts = read_accounts(accounts_path)
    for a in accounts:
        name = a["company"].strip()
        print(f"Checking {name}...", end=" ", flush=True)
        try:
            jobs = get_jobs(name, a["job_board"].strip().lower(), a["board_token"].strip(), demo_dir=demo_dir)
            r = scorer.score_account(name, jobs, tier=a.get("tier", ""), owner=a.get("owner", ""))
            print(f"{len(jobs)} open roles, {len(r.matches)} relevant, {r.status}")
        except SourceError as e:
            r = AccountResult(company=name, tier=a.get("tier", ""), owner=a.get("owner", ""), error=str(e))
            print(f"skipped ({e})")
        results.append(r)

    results = rank(results)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_date = scorer.today
    write_csv(results, out / "signals.csv")
    write_markdown(results, out / "report.md", run_date, demo=args.demo)
    print(f"\nSaved {out / 'signals.csv'} and {out / 'report.md'}")

    if args.slack:
        url = os.environ.get("SLACK_WEBHOOK_URL")
        if not url:
            print("SLACK_WEBHOOK_URL is not set, so nothing was posted.")
        else:
            post_to_slack(url, slack_message(results))
            print("Posted to Slack.")
    return 0
