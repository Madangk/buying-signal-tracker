"""Write results as a CSV (for a CRM or spreadsheet), a Markdown report, and an optional Slack message."""
import csv
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List

from .scoring import AccountResult

STATUS_ICON = {"Hot": "🔥", "Warm": "🟡", "Cold": "⚪"}


def write_csv(results: List[AccountResult], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "company", "status", "score", "tier", "owner", "relevant_roles",
                    "open_roles_total", "top_signal", "top_roles", "talking_point", "role_links"])
        for i, r in enumerate(results, 1):
            links = " | ".join(m.job.url for m in r.ranked_matches()[:3])
            w.writerow([i, r.company, r.status if not r.error else "Error", r.score, r.tier, r.owner,
                        len(r.matches), r.open_roles, r.top_signal, "; ".join(r.top_roles()), r.talking_point(), links])


def write_markdown(results: List[AccountResult], path: Path, run_date: datetime, demo: bool) -> None:
    hot = [r for r in results if r.status == "Hot" and not r.error]
    warm = [r for r in results if r.status == "Warm" and not r.error]
    lines = [
        f"# Buying-signal report: {run_date:%d %b %Y}",
        "",
        "> Demo run on sample data for fictional companies." if demo else "> Live run on public job boards.",
        "",
        f"**{len(results)} accounts checked · {len(hot)} hot · {len(warm)} warm**",
        "",
        "| # | Account | Status | Score | Relevant roles | Why reach out now |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        status = "⚠️ Error" if r.error else f"{STATUS_ICON[r.status]} {r.status}"
        lines.append(f"| {i} | {r.company} | {status} | {r.score:g} | {len(r.matches)} | {r.talking_point()} |")

    for r in hot + warm:
        lines += ["", f"## {r.company} ({r.status}, score {r.score:g})", ""]
        for name, count in r.signals.most_common():
            lines.append(f"- **{name}:** {count}")
        lines += ["", "Top roles:"]
        for m in r.ranked_matches()[:5]:
            posted = f", posted {m.job.posted_at:%d %b}" if m.job.posted_at else ""
            loc = f" ({m.job.location})" if m.job.location else ""
            lines.append(f"- [{m.job.title}]({m.job.url}){loc}{posted}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def slack_message(results: List[AccountResult], top_n: int = 5) -> str:
    hot_warm = [r for r in results if r.status in ("Hot", "Warm") and not r.error][:top_n]
    if not hot_warm:
        return "Buying-signal tracker: no hot or warm accounts this run."
    lines = [f"*Buying signals this week: top {len(hot_warm)} accounts*"]
    for r in hot_warm:
        owner = f" (owner: {r.owner})" if r.owner else ""
        lines.append(f"{STATUS_ICON[r.status]} *{r.company}*, score {r.score:g}{owner}: {r.talking_point()}")
    return "\n".join(lines)


def post_to_slack(webhook_url: str, text: str) -> None:
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Slack returned HTTP {resp.status}")
