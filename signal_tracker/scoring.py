"""Match job titles to buying signals and score each account."""
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .sources import Job


@dataclass
class MatchedJob:
    job: Job
    signal: str
    score: float


@dataclass
class AccountResult:
    company: str
    tier: str = ""
    owner: str = ""
    score: float = 0.0
    status: str = "Cold"
    open_roles: int = 0
    matches: List[MatchedJob] = field(default_factory=list)
    error: str = ""

    @property
    def signals(self) -> Counter:
        return Counter(m.signal for m in self.matches)

    @property
    def top_signal(self) -> str:
        """The signal carrying the most score."""
        totals = Counter()
        for m in self.matches:
            totals[m.signal] += m.score
        return totals.most_common(1)[0][0] if totals else ""

    def ranked_matches(self) -> List[MatchedJob]:
        return sorted(self.matches, key=lambda m: m.score, reverse=True)

    def top_roles(self, n=3) -> List[str]:
        return [m.job.title for m in self.ranked_matches()[:n]]

    def talking_point(self) -> str:
        """A plain one-line reason to reach out, built from the evidence (no AI)."""
        if self.error:
            return f"Could not check: {self.error}"
        if not self.matches:
            return "No relevant hiring right now. Revisit next month."
        lead = self.ranked_matches()[0]
        others = len(self.matches) - 1
        more = f", plus {others} more relevant role{'s' if others != 1 else ''}" if others else ""
        return f"{lead.signal}: '{lead.job.title}'{more}."


def _compile(keywords: List[str]) -> List[re.Pattern]:
    return [re.compile(r"(?<![a-z0-9])" + re.escape(k.lower()) + r"(?![a-z0-9])") for k in keywords]


class Scorer:
    def __init__(self, config: Dict, today: Optional[datetime] = None):
        self.signals = [
            {"name": s["name"], "weight": float(s["weight"]), "patterns": _compile(s["keywords"])}
            for s in config["signals"]
        ]
        # Highest-weight signal wins when a title matches more than one.
        self.signals.sort(key=lambda s: s["weight"], reverse=True)
        boost = config.get("seniority_boost", {})
        self.senior_patterns = _compile(boost.get("keywords", []))
        self.senior_multiplier = float(boost.get("multiplier", 1.0))
        self.lookback = timedelta(days=int(config.get("lookback_days", 60)))
        self.hot = float(config.get("thresholds", {}).get("hot", 15))
        self.warm = float(config.get("thresholds", {}).get("warm", 6))
        self.today = today or datetime.now(timezone.utc)

    def match(self, job: Job) -> Optional[MatchedJob]:
        if job.posted_at and self.today - job.posted_at > self.lookback:
            return None
        text = f"{job.title} {job.department}".lower()
        for s in self.signals:
            if any(p.search(text) for p in s["patterns"]):
                score = s["weight"]
                if any(p.search(job.title.lower()) for p in self.senior_patterns):
                    score *= self.senior_multiplier
                return MatchedJob(job, s["name"], score)
        return None

    def score_account(self, company: str, jobs: List[Job], tier: str = "", owner: str = "") -> AccountResult:
        result = AccountResult(company=company, tier=tier, owner=owner, open_roles=len(jobs))
        result.matches = [m for m in (self.match(j) for j in jobs) if m]
        result.score = round(sum(m.score for m in result.matches), 1)
        result.status = "Hot" if result.score >= self.hot else "Warm" if result.score >= self.warm else "Cold"
        return result


def rank(results: List[AccountResult]) -> List[AccountResult]:
    return sorted(results, key=lambda r: (r.error == "", r.score), reverse=True)
