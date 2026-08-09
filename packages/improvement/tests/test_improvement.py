"""Tests for improvement package."""

from uuid import uuid4

import pytest
from autonoesis_domain import ImprovementTarget
from autonoesis_improvement import AnalysisKind, ImprovementAnalyser, ProposalGenerator


class TestImprovementAnalyser:
    @pytest.mark.asyncio
    async def test_detects_regression(self) -> None:
        result = await ImprovementAnalyser.analyse_trial_results(
            target=ImprovementTarget.AGENT_INSTRUCTION,
            target_version_id=uuid4(),
            trial_results=(("case-1", 0.5), ("case-2", 0.6)),
        )
        assert result.kind == AnalysisKind.REGRESSION

    @pytest.mark.asyncio
    async def test_no_regression_with_good_scores(self) -> None:
        result = await ImprovementAnalyser.analyse_trial_results(
            target=ImprovementTarget.AGENT_INSTRUCTION,
            target_version_id=uuid4(),
            trial_results=(("case-1", 0.9), ("case-2", 0.95)),
        )
        assert result.kind == AnalysisKind.OPPORTUNITY

    @pytest.mark.asyncio
    async def test_handles_empty_results(self) -> None:
        result = await ImprovementAnalyser.analyse_trial_results(
            target=ImprovementTarget.SKILL,
            target_version_id=uuid4(),
            trial_results=(),
        )
        assert result.kind == AnalysisKind.OPPORTUNITY


class TestProposalGenerator:
    @pytest.mark.asyncio
    async def test_generates_proposal(self) -> None:
        analysis = await ImprovementAnalyser.analyse_trial_results(
            target=ImprovementTarget.AGENT_INSTRUCTION,
            target_version_id=uuid4(),
            trial_results=(("case-1", 0.5),),
        )
        proposal = await ProposalGenerator.generate(
            analysis=analysis,
            proposed_change="increase context window",
            rollback_plan="revert to previous version",
            validation_suite_id="suite-1",
            proposer_id="test-proposer",
            tenant_id=uuid4(),
        )
        assert proposal.target == ImprovementTarget.AGENT_INSTRUCTION
        assert "average trial score" in proposal.diagnosis.lower()
