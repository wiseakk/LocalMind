"""Trusted adapter outcomes. Acceptance and observation are separate facts."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ActionResult:
    success: bool
    action: str
    resolved_target: str | None
    execution_status: str
    observed_state: str | None = None
    error: str | None = None
    mode: str = 'REAL'
    duration_ms: int = 0
    status_text: str = ''

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return self.status_text

    def __contains__(self, value: str) -> bool:
        """Keep the former adapters' simple status containment API usable."""
        return value in self.status_text


def refused(action: str, target: str | None, reason: str, *, status='denied') -> ActionResult:
    return ActionResult(False, action, target, status, error=reason, status_text=reason)
