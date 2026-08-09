"""Analysis, proposal, candidate, release, and rollback for Autonoesis.

Extends the CandidateLifecycleService in packages/application with
analysis and proposal generation capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain import (
    ImprovementProposal,
    ImprovementTarget,
)


class AnalysisKind(StrEnum):
    REGRESSION = "regression"
    DRIFT = "drift"
    OPPORTUNITY = "opportunity"
    INCIDENT = "incident"


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Output of analysing a target for improvement opportunities."""

    analysis_id: UUID = field(default_factory=uuid4)
    target: ImprovementTarget = ImprovementTarget.AGENT_INSTRUCTION
    target_version_id: UUID = field(default_factory=uuid4)
    kind: AnalysisKind = AnalysisKind.OPPORTUNITY
    diagnosis: str = ""
    evidence_refs: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    analysed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ImprovementAnalyser:
    """Analyses evaluation results, production metrics, and incidents to
    identify improvement opportunities.
    """

    @staticmethod
    async def analyse_trial_results(
        target: ImprovementTarget,
        target_version_id: UUID,
        trial_results: tuple[tuple[str, float], ...],
    ) -> AnalysisResult:
        """Analyse trial scores to detect regressions or drift."""
        if not trial_results:
            return AnalysisResult(
                target=target,
                target_version_id=target_version_id,
                kind=AnalysisKind.OPPORTUNITY,
                diagnosis="no trial data available",
            )
        scores = [score for _, score in trial_results]
        avg = sum(scores) / len(scores)
        if avg < 0.7:
            return AnalysisResult(
                target=target,
                target_version_id=target_version_id,
                kind=AnalysisKind.REGRESSION,
                diagnosis=f"average trial score {avg:.2f} below 0.7 threshold",
                metrics={"avg_score": avg, "min_score": min(scores), "max_score": max(scores)},
            )
        return AnalysisResult(
            target=target,
            target_version_id=target_version_id,
            kind=AnalysisKind.OPPORTUNITY,
            diagnosis="scores within acceptable range",
            metrics={"avg_score": avg},
        )


class ProposalGenerator:
    """Generates ImprovementProposals from AnalysisResults."""

    @staticmethod
    async def generate(
        analysis: AnalysisResult,
        proposed_change: str,
        rollback_plan: str,
        validation_suite_id: str,
        proposer_id: str,
        tenant_id: UUID,
    ) -> ImprovementProposal:
        return ImprovementProposal(
            tenant_id=tenant_id,
            target=analysis.target,
            target_version_id=analysis.target_version_id,
            diagnosis=analysis.diagnosis,
            proposed_change=proposed_change,
            rollback_plan=rollback_plan,
            validation_suite_id=validation_suite_id,
            evidence_refs=analysis.evidence_refs if analysis.evidence_refs else ("generated",),
            proposer_id=proposer_id,
        )


__all__ = [
    "AnalysisKind",
    "AnalysisResult",
    "ImprovementAnalyser",
    "ProposalGenerator",
]
