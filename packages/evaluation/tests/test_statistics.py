"""Tests for repeated-Trial statistical confidence gates."""

from dataclasses import replace
from statistics import NormalDist
from typing import Any
from uuid import uuid4

import pytest
from autonoesis_domain import (
    Trial,
    TrialCaseResult,
    TrialStatus,
)
from autonoesis_evaluation import (
    ConfidenceDecision,
    RepeatedTrialPolicy,
    TrialConfidenceGate,
    wilson_score_interval,
)

TENANT_ID = uuid4()
SUBJECT_VERSION_ID = uuid4()

_EXECUTED_CASE = TrialCaseResult(
    case_id="c1",
    input_payload={},
    output_payload={"answer": 42},
    subject_executed=True,
    executor_id="subject-runtime",
    evidence_refs=("evidence://execution/1",),
    environment_ref="environment://fixture/1",
)


def make_trial(status: TrialStatus, **overrides: Any) -> Trial:
    defaults: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "suite_id": "s1",
        "suite_version": "1",
        "subject_version_id": SUBJECT_VERSION_ID,
        "harness_version": "2",
        "trial_id": uuid4(),
        "status": status,
        "case_results": (_EXECUTED_CASE,) if status is not TrialStatus.INVALID else (),
        "failure_reason": "infrastructure failure" if status is TrialStatus.INVALID else None,
    }
    return Trial(**{**defaults, **overrides})


def trials(*statuses: TrialStatus) -> tuple[Trial, ...]:
    return tuple(make_trial(status) for status in statuses)


class TestWilsonScoreInterval:
    def test_all_pass_lower_bound_is_n_over_n_plus_z_squared(self) -> None:
        # With rate 1.0 the Wilson lower bound simplifies to n / (n + z^2).
        z = NormalDist().inv_cdf(0.975)
        lower, upper = wilson_score_interval(16, 16, 0.95)
        assert lower == pytest.approx(16 / (16 + z**2), rel=1e-12)
        assert upper == pytest.approx(1.0, abs=1e-3)

    def test_zero_passes_has_zero_lower_bound(self) -> None:
        lower, upper = wilson_score_interval(0, 10, 0.95)
        assert lower == 0.0
        assert 0.0 < upper < 0.5

    def test_bounds_stay_within_unit_range(self) -> None:
        lower, upper = wilson_score_interval(5, 9, 0.99)
        assert 0.0 <= lower < upper <= 1.0

    def test_rejects_impossible_arguments(self) -> None:
        with pytest.raises(ValueError, match="at least one trial"):
            wilson_score_interval(0, 0, 0.95)
        with pytest.raises(ValueError, match="between zero and the trial total"):
            wilson_score_interval(11, 10, 0.95)
        with pytest.raises(ValueError, match="confidence level"):
            wilson_score_interval(1, 10, 1.0)


class TestRepeatedTrialPolicy:
    def test_rejects_undemonstrable_thresholds(self) -> None:
        with pytest.raises(ValueError, match="exclusive"):
            RepeatedTrialPolicy(pass_threshold=1.0)
        with pytest.raises(ValueError, match="exclusive"):
            RepeatedTrialPolicy(pass_threshold=0.0)

    def test_rejects_invalid_confidence_and_sample(self) -> None:
        with pytest.raises(ValueError, match="confidence level"):
            RepeatedTrialPolicy(pass_threshold=0.8, confidence_level=0.5)
        with pytest.raises(ValueError, match="at least one valid trial"):
            RepeatedTrialPolicy(pass_threshold=0.8, min_valid_trials=0)


class TestTrialConfidenceGate:
    def test_fixed_run_count_is_not_a_substitute_for_confidence(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.8, min_valid_trials=3)
        assessment = TrialConfidenceGate(policy).assess(trials(*[TrialStatus.PASSED] * 3))
        assert assessment.decision is ConfidenceDecision.INSUFFICIENT_SAMPLE
        assert assessment.lower_bound is not None and assessment.lower_bound < 0.5
        assert not assessment.met

    def test_all_pass_needs_enough_trials_to_cross_the_threshold(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.8, min_valid_trials=3)
        gate = TrialConfidenceGate(policy)
        below = gate.assess(trials(*[TrialStatus.PASSED] * 15))
        above = gate.assess(trials(*[TrialStatus.PASSED] * 16))
        assert below.decision is ConfidenceDecision.INSUFFICIENT_SAMPLE
        assert above.decision is ConfidenceDecision.MET
        assert above.pass_rate == 1.0
        assert above.passed_trials == 16

    def test_straddling_interval_keeps_sampling_instead_of_rejecting(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.9, min_valid_trials=10)
        gate = TrialConfidenceGate(policy)
        straddling = gate.assess(trials(*[TrialStatus.PASSED] * 8 + [TrialStatus.FAILED] * 2))
        assert straddling.decision is ConfidenceDecision.INSUFFICIENT_SAMPLE
        assert straddling.lower_bound is not None and straddling.lower_bound < 0.9
        assert straddling.upper_bound is not None and straddling.upper_bound >= 0.9

    def test_conclusive_failure_requires_the_upper_bound_below_threshold(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.8, min_valid_trials=10)
        gate = TrialConfidenceGate(policy)
        assessment = gate.assess(trials(*[TrialStatus.PASSED] * 2 + [TrialStatus.FAILED] * 28))
        assert assessment.decision is ConfidenceDecision.NOT_MET
        assert assessment.upper_bound is not None and assessment.upper_bound < 0.8

    def test_large_mixed_sample_can_meet_threshold(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.7, min_valid_trials=30)
        sample = trials(*([TrialStatus.PASSED] * 80 + [TrialStatus.FAILED] * 20))
        assessment = TrialConfidenceGate(policy).assess(sample)
        assert assessment.decision is ConfidenceDecision.MET
        assert assessment.pass_rate == pytest.approx(0.8)
        assert assessment.lower_bound == pytest.approx(0.712, abs=1e-3)

    def test_threshold_equal_to_lower_bound_is_met(self) -> None:
        lower, _ = wilson_score_interval(12, 15, 0.95)
        policy = RepeatedTrialPolicy(pass_threshold=lower, min_valid_trials=10)
        assessment = TrialConfidenceGate(policy).assess(
            trials(*[TrialStatus.PASSED] * 12 + [TrialStatus.FAILED] * 3)
        )
        assert assessment.decision is ConfidenceDecision.MET

    def test_insufficient_sample_fails_closed(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.6, min_valid_trials=10)
        assessment = TrialConfidenceGate(policy).assess(trials(*[TrialStatus.PASSED] * 5))
        assert assessment.decision is ConfidenceDecision.INSUFFICIENT_SAMPLE
        assert not assessment.met
        assert assessment.pass_rate == 1.0

    def test_empty_sample_fails_closed_without_an_estimate(self) -> None:
        assessment = TrialConfidenceGate(RepeatedTrialPolicy(pass_threshold=0.8)).assess(())
        assert assessment.decision is ConfidenceDecision.INSUFFICIENT_SAMPLE
        assert assessment.pass_rate is None
        assert assessment.lower_bound is None

    def test_invalid_trials_are_neither_green_nor_sample(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.7, min_valid_trials=15)
        sample = trials(*([TrialStatus.PASSED] * 10 + [TrialStatus.INVALID] * 5))
        assessment = TrialConfidenceGate(policy).assess(sample)
        assert assessment.decision is ConfidenceDecision.INSUFFICIENT_SAMPLE
        assert assessment.invalid_trials == 5
        assert assessment.valid_trials == 10

    def test_invalid_trials_do_not_enter_the_pass_rate(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.7, min_valid_trials=10)
        sample = trials(*([TrialStatus.PASSED] * 10 + [TrialStatus.INVALID] * 5))
        assessment = TrialConfidenceGate(policy).assess(sample)
        assert assessment.pass_rate == 1.0
        assert assessment.passed_trials == 10

    def test_duplicate_trial_ids_are_rejected(self) -> None:
        shared_id = uuid4()
        sample = (
            make_trial(TrialStatus.PASSED, trial_id=shared_id),
            make_trial(TrialStatus.PASSED, trial_id=shared_id),
        )
        with pytest.raises(ValueError, match="duplicate trial id"):
            TrialConfidenceGate(RepeatedTrialPolicy(pass_threshold=0.8)).assess(sample)

    def test_non_terminal_trials_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="terminal trials only"):
            TrialConfidenceGate(RepeatedTrialPolicy(pass_threshold=0.8)).assess(
                (make_trial(TrialStatus.RUNNING),)
            )

    @pytest.mark.parametrize(
        ("field", "divergent_value"),
        [
            ("tenant_id", uuid4()),
            ("suite_id", "other-suite"),
            ("suite_version", "2"),
            ("subject_version_id", uuid4()),
            ("harness_version", "3"),
        ],
    )
    def test_heterogeneous_samples_are_rejected(self, field: str, divergent_value: Any) -> None:
        divergent = replace(make_trial(TrialStatus.PASSED), **{field: divergent_value})
        with pytest.raises(ValueError, match=f"share {field}"):
            TrialConfidenceGate(RepeatedTrialPolicy(pass_threshold=0.8)).assess(
                (make_trial(TrialStatus.PASSED), divergent)
            )

    def test_assessment_reports_policy_and_rationale(self) -> None:
        policy = RepeatedTrialPolicy(pass_threshold=0.8, min_valid_trials=3)
        assessment = TrialConfidenceGate(policy).assess(trials(*[TrialStatus.PASSED] * 16))
        assert assessment.policy == policy
        assert assessment.rationale
        assert "95%" in assessment.rationale
