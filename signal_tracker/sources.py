"""Fetch open roles from public job-board APIs and turn them into one common shape.

Supported job boards (all public, no API key needed):
  - Greenhouse: https://boards-api.greenhouse.io/v1/boards/<token>/jobs
  - Lever:      https://api.lever.co/v0/postings/<token>?mode=json
  - Ashby:      https://api.ashbyhq.com/posting-api/job-board/<token>
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

USER_AGENT = "buying-signal-tracker/1.0 (+https://github.com/Madangk/buying-signal-tracker)"

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}


@dataclass
class Job:
    company: str
    title: str
    department: str
    location: str
    url: str
    posted_at: Optional[datetime]


class SourceError(Exception):
    pass


# ---------- fetching ----------

def fetch_raw(source: str, token: str, timeout: int = 20):
    """Download the job board JSON for one company."""
    if source not in URLS:
        raise SourceError(f"Unknown job board '{source}'. Use one of: {', '.join(URLS)}")
    url = URLS[source].format(token=token)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SourceError(f"No {source} job board found for '{token}' (check the token)") from e
        raise SourceError(f"{source} returned HTTP {e.code} for '{token}'") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SourceError(f"Could not reach {source} for '{token}': {e}") from e


def load_demo(source: str, token: str, demo_dir: Path):
    """Read a saved JSON response instead of calling the internet (demo and tests)."""
    path = demo_dir / f"{source}_{token}.json"
    if not path.exists():
        raise SourceError(f"No {source} job board found for '{token}' (check the token)")
    return json.loads(path.read_text(encoding="utf-8"))


def get_jobs(company: str, source: str, token: str, demo_dir: Optional[Path] = None, pause: float = 0.5) -> List[Job]:
    raw = load_demo(source, token, demo_dir) if demo_dir else fetch_raw(source, token)
    if not demo_dir:
        time.sleep(pause)  # be polite to public APIs
    return normalise(company, source, raw)


# ---------- normalising ----------

def normalise(company: str, source: str, raw) -> List[Job]:
    if source == "greenhouse":
        return [_greenhouse(company, j) for j in raw.get("jobs", [])]
    if source == "lever":
        return [_lever(company, j) for j in raw]
    if source == "ashby":
        return [_ashby(company, j) for j in raw.get("jobs", []) if j.get("isListed", True)]
    raise SourceError(f"Unknown job board '{source}'")


def _greenhouse(company, j) -> Job:
    depts = ", ".join(d.get("name", "") for d in j.get("departments", []) or [])
    return Job(company, j.get("title", ""), depts, (j.get("location") or {}).get("name", ""),
               j.get("absolute_url", ""), parse_date(j.get("first_published") or j.get("updated_at")))


def _lever(company, j) -> Job:
    cats = j.get("categories") or {}
    created = j.get("createdAt")
    posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc) if isinstance(created, (int, float)) else None
    return Job(company, j.get("text", ""), cats.get("team", "") or cats.get("department", ""),
               cats.get("location", ""), j.get("hostedUrl", ""), posted)


def _ashby(company, j) -> Job:
    return Job(company, j.get("title", ""), j.get("department", "") or j.get("team", ""),
               j.get("location", ""), j.get("jobUrl", ""), parse_date(j.get("publishedAt")))


def parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
