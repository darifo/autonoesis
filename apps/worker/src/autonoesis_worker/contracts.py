"""Stable, serialization-safe Temporal Workflow and Activity contracts."""

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class GoalRunInput:
    tenant_id: str
    goal_id: str
    run_id: str
    deadline_epoch_seconds: float
    requires_approval: bool = False
    continuation_count: int = 0
    max_continuations: int = 100

    def continued(self) -> "GoalRunInput":
        return replace(
            self,
            requires_approval=False,
            continuation_count=self.continuation_count + 1,
        )


@dataclass(frozen=True, slots=True)
class CandidateLifecycleInput:
    tenant_id: str
    candidate_id: str


@dataclass(frozen=True, slots=True)
class RunIdentityInput:
    tenant_id: str
    goal_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class PrepareRunInput(RunIdentityInput):
    pass


@dataclass(frozen=True, slots=True)
class CancelRunInput(RunIdentityInput):
    reason: str = "cancelled_by_user"


@dataclass(frozen=True, slots=True)
class RejectRunInput(RunIdentityInput):
    reason: str = "rejected_by_policy"


@dataclass(frozen=True, slots=True)
class TakeOverRunInput(RunIdentityInput):
    reason: str = "manual_takeover"


@dataclass(frozen=True, slots=True)
class ExecuteRunInput(RunIdentityInput):
    pass


@dataclass(frozen=True, slots=True)
class EvaluateRunInput(RunIdentityInput):
    pass


@dataclass(frozen=True, slots=True)
class ApprovalLookupInput:
    tenant_id: str
    run_id: str
    approval_id: str


@dataclass(frozen=True, slots=True)
class ApprovalState:
    approval_id: str
    status: str


@dataclass(frozen=True, slots=True)
class EvaluateCandidateInput:
    tenant_id: str
    candidate_id: str


@dataclass(frozen=True, slots=True)
class PromoteCandidateInput:
    tenant_id: str
    candidate_id: str
    stable_version_id: str
