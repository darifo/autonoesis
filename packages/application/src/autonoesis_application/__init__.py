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

__all__ = [
    "AuditEvent",
    "CandidateLifecycleService",
    "CapabilityCatalog",
    "ConcurrencyConflict",
    "CreateGoal",
    "CreateGoalHandler",
    "EvaluationDecision",
    "EvolutionRepository",
    "IdentityContext",
    "PlatformRepository",
    "RecordNotFound",
    "StartGoalRun",
    "StartGoalRunHandler",
    "TenantBoundaryViolation",
]
