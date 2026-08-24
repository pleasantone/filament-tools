"""Short-lived capabilities for reviewed editor installation plans."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

from filament_tools.model import InstallPlan


class ReviewedInstallPlans:
    def __init__(
        self,
        *,
        ttl_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._plans: dict[str, tuple[float, InstallPlan]] = {}

    def issue(self, plan: InstallPlan) -> str:
        if not plan.valid:
            raise ValueError("cannot issue an installation capability for an invalid plan")
        self._purge()
        token = secrets.token_urlsafe(32)
        self._plans[token] = (self.clock() + self.ttl_seconds, plan)
        return token

    def consume(self, token: str) -> InstallPlan:
        value = token.strip()
        if not value:
            raise ValueError("installation plan ID is required")
        entry = self._plans.pop(value, None)
        if entry is None:
            raise ValueError("installation plan is missing, expired, or already used")
        expires_at, plan = entry
        if expires_at < self.clock():
            raise ValueError("installation plan is missing, expired, or already used")
        return plan

    def _purge(self) -> None:
        now = self.clock()
        self._plans = {
            token: entry for token, entry in self._plans.items() if entry[0] >= now
        }
