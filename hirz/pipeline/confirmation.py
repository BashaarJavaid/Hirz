"""Request-local requester review, installed only by authenticated MCP elicitation.

No grant survives the originating tool call. The binding covers the freshly
resolved action, current policy and linked principal, including lowered claims.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime

from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Principal


class RequesterReview(Exception):
    def __init__(self, binding: str, action: Action, message: str | None = None):
        self.binding, self.action, self.message = binding, action, message


@dataclass
class Review:
    accepted: set[str] = field(default_factory=set)
    scheduled_at: datetime | None = None

    def immediate_at(self, now: datetime) -> datetime:
        # Rebuilding an immediate request after a human reply must not change
        # its action hash merely because the wall clock advanced. Evaluations,
        # observations, policy and credential checks still use current time.
        if self.scheduled_at is None:
            self.scheduled_at = now
        return self.scheduled_at

    @staticmethod
    def binding(policy: str, action: Action, principal: Principal) -> str:
        return digest(
            {
                "policy": policy,
                "action": action.content_hash,
                "principal": principal.model_dump(mode="json"),
            }
        )


review_context: ContextVar[Review | None] = ContextVar("requester_review", default=None)
