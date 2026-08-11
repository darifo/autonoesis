"""Application use cases and ports for the industry-neutral platform."""

from autonoesis_application.evolution import (
    CandidateLifecycleService,
    EvaluationDecision,
    EvolutionRepository,
)
from autonoesis_application.platform import (
    AuditEvent,
    CapabilityCatalog,
    ConcurrencyConflict,
    CreateGoal,
    CreateGoalHandler,
    IdentityContext,
    PlatformRepository,
    RecordNotFound,
    StartGoalRun,
    StartGoalRunHandler,
    TenantBoundaryViolation,
)
from autonoesis_application.repositories import (
    AuditRepository,
    EvaluationRepository,
    ExecutionRepository,
    GovernanceRepository,
    VerificationRepository,
)

__all__ = [
    "AuditEvent",
    "AuditRepository",
    "CandidateLifecycleService",
    "CapabilityCatalog",
    "ConcurrencyConflict",
    "CreateGoal",
    "CreateGoalHandler",
    "EvaluationDecision",
    "EvaluationRepository",
    "EvolutionRepository",
    "ExecutionRepository",
    "GovernanceRepository",
    "IdentityContext",
    "PlatformRepository",
    "RecordNotFound",
    "StartGoalRun",
    "StartGoalRunHandler",
    "TenantBoundaryViolation",
    "VerificationRepository",
]
