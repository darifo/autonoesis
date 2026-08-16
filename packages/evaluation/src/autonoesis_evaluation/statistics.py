"""Statistical confidence gates over repeated evaluation Trials."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import NormalDist
from uuid import UUID

from autonoesis_domain import Trial, TrialStatus

_TERMINAL_STATUSES = frozenset({TrialStatus.PASSED, TrialStatus.FAILED, TrialStatus.INVALID})


class ConfidenceDecision(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


@dataclass(frozen=True, slots=True)
class RepeatedTrialPolicy:
    """Statistical acceptance policy for one repeated-Trial evaluation.

    A threshold of exactly one can never be demonstrated: the Wilson lower bound
    stays below one for any finite sample. Policies must state a demonstrable
    target rate instead of demanding perfection.
    """

    pass_threshold: float
    confidence_level: float = 0.95
    min_valid_trials: int = 10

    def __post_init__(self) -> None:
        if not 0 < self.pass_threshold < 1:
            raise ValueError("repeated-trial threshold must be between zero and one, exclusive")
        if not 0.5 < self.confidence_level < 1:
            raise ValueError("confidence level must be between one half and one, exclusive")
        if self.min_valid_trials < 1:
            raise ValueError("repeated-trial policy requires at least one valid trial")


@dataclass(frozen=True, slots=True)
class TrialConfidenceAssessment:
    """Auditable record of one confidence decision over repeated Trials."""

    policy: RepeatedTrialPolicy
    decision: ConfidenceDecision
    passed_trials: int
    failed_trials: int
    invalid_trials: int
    pass_rate: float | None
    lower_bound: float | None
    upper_bound: float | None
    rationale: str

    @property
    def valid_trials(self) -> int:
        return self.passed_trials + self.failed_trials

    @property
    def met(self) -> bool:
        return self.decision is ConfidenceDecision.MET


def wilson_score_interval(passes: int, total: int, confidence_level: float) -> tuple[float, float]:
    """Two-sided Wilson score interval for a binomial pass rate."""
    if total <= 0:
        raise ValueError("wilson interval requires at least one trial")
    if not 0 <= passes <= total:
        raise ValueError("passes must be between zero and the trial total")
    if not 0.5 < confidence_level < 1:
        raise ValueError("confidence level must be between one half and one, exclusive")
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    rate = passes / total
    z_squared = z * z
    denominator = 1 + z_squared / total
    center = (rate + z_squared / (2 * total)) / denominator
    spread = (z / denominator) * math.sqrt(
        rate * (1 - rate) / total + z_squared / (4 * total * total)
    )
    return max(0.0, center - spread), min(1.0, center + spread)


class TrialConfidenceGate:
    """Fails closed unless repeated Trials demonstrate the target rate with confidence.

    Invalid Trials are infrastructure evidence, not subject evidence: they are
    excluded from both the numerator and the sample size, so outages can neither
    turn the gate green nor silently shrink the required sample.
    """

    def __init__(self, policy: RepeatedTrialPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> RepeatedTrialPolicy:
        return self._policy

    def assess(self, trials: tuple[Trial, ...]) -> TrialConfidenceAssessment:
        self._require_one_subject(trials)
        passed = sum(trial.status is TrialStatus.PASSED for trial in trials)
        failed = sum(trial.status is TrialStatus.FAILED for trial in trials)
        invalid = sum(trial.status is TrialStatus.INVALID for trial in trials)
        valid = passed + failed
        lower, upper = (
            wilson_score_interval(passed, valid, self._policy.confidence_level)
            if valid
            else (None, None)
        )
        rate = passed / valid if valid else None
        threshold = self._policy.pass_threshold
        if valid < self._policy.min_valid_trials:
            return TrialConfidenceAssessment(
                policy=self._policy,
                decision=ConfidenceDecision.INSUFFICIENT_SAMPLE,
                passed_trials=passed,
                failed_trials=failed,
                invalid_trials=invalid,
                pass_rate=rate,
                lower_bound=lower,
                upper_bound=upper,
                rationale=(
                    f"{valid} valid trials do not satisfy the minimum sample of "
                    f"{self._policy.min_valid_trials}; {invalid} invalid trials "
                    "cannot close the gap"
                ),
            )
        assert lower is not None and upper is not None and rate is not None
        confidence = self._policy.confidence_level
        if lower >= threshold:
            decision = ConfidenceDecision.MET
            rationale = (
                f"pass rate {rate:.4f} holds a {confidence:.0%} lower bound of "
                f"{lower:.4f} at or above threshold {threshold}"
            )
        else:
            decision = ConfidenceDecision.NOT_MET
            rationale = (
                f"pass rate {rate:.4f} only holds a {confidence:.0%} lower bound of "
                f"{lower:.4f} below threshold {threshold}"
            )
        return TrialConfidenceAssessment(
            policy=self._policy,
            decision=decision,
            passed_trials=passed,
            failed_trials=failed,
            invalid_trials=invalid,
            pass_rate=rate,
            lower_bound=lower,
            upper_bound=upper,
            rationale=rationale,
        )

    def _require_one_subject(self, trials: tuple[Trial, ...]) -> None:
        seen: set[UUID] = set()
        for trial in trials:
            if trial.status not in _TERMINAL_STATUSES:
                raise ValueError("confidence assessment requires terminal trials only")
            if trial.trial_id in seen:
                raise ValueError("repeated trials must be distinct: duplicate trial id")
            seen.add(trial.trial_id)
        if not trials:
            return
        reference = trials[0]
        for field in (
            "tenant_id",
            "suite_id",
            "suite_version",
            "subject_version_id",
            "harness_version",
        ):
            if any(getattr(trial, field) != getattr(reference, field) for trial in trials):
                raise ValueError(f"repeated trials must share {field}")


__all__ = [
    "ConfidenceDecision",
    "RepeatedTrialPolicy",
    "TrialConfidenceAssessment",
    "TrialConfidenceGate",
    "wilson_score_interval",
]
