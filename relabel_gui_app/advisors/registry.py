"""The set of advisors the app offers. Adding a provider means adding one class to default_advisors()."""
from __future__ import annotations

from typing import Dict, Iterable, List

from .base import Advisor, AdvisorError
from .claude_api import ClaudeAPIAdvisor
from .cli_agents import ClaudeCodeAdvisor, CodexAdvisor


class AdvisorRegistry:
    def __init__(self, advisors: Iterable[Advisor]):
        self._by_id: Dict[str, Advisor] = {a.id: a for a in advisors}

    def describe(self) -> List[dict]:
        out = []
        for a in self._by_id.values():
            ready, hint = a.availability()
            out.append({"id": a.id, "label": a.label, "ready": ready, "hint": hint})
        return out

    def get(self, advisor_id: str) -> Advisor:
        try:
            return self._by_id[advisor_id]
        except KeyError:
            raise AdvisorError(f"Unknown advisor: {advisor_id}")


def default_advisors() -> List[Advisor]:
    return [ClaudeAPIAdvisor(), ClaudeCodeAdvisor(), CodexAdvisor()]
