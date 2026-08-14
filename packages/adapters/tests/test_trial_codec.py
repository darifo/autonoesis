"""Lossless persistence coverage for auditable evaluation Trials."""

from datetime import UTC, datetime
from uuid import uuid4

from autonoesis_adapters.persistence_codec import trial_from_row, trial_payload
from autonoesis_domain import GraderResult, Trial, TrialCaseResult, TrialStatus


def test_trial_result_round_trips_through_authoritative_json() -> None:
    tenant_id = uuid4()
    subject_version_id = uuid4()
    trial_id = uuid4()
    recorded_at = datetime.now(UTC)
    trial = Trial(
        tenant_id=tenant_id,
        suite_id="release-gate",
        suite_version="7",
        subject_version_id=subject_version_id,
        harness_version="2",
        trial_id=trial_id,
        status=TrialStatus.PASSED,
        random_seed=73,
        case_results=(
            TrialCaseResult(
                case_id="case-1",
                input_payload={"prompt": "fixed"},
                output_payload={"answer": 42},
                subject_executed=True,
                grader_results=(
                    GraderResult(
                        trial_id=trial_id,
                        grader_id="rules",
                        grader_version="3",
                        score=1.0,
                        passed=True,
                        rationale="exact match",
                        evidence_refs=("evidence://grade/1",),
                    ),
                ),
                evidence_refs=("evidence://subject/1",),
                executor_id="subject-runtime",
                environment_ref="environment://snapshot/1",
                model_ref="model://route/1",
                tool_refs=("tool://read/1",),
                random_seed=73,
                cost_microunits=29,
            ),
        ),
        total_cost_microunits=29,
        started_at=recorded_at,
        completed_at=recorded_at,
    )

    restored = trial_from_row(
        {
            "id": str(trial_id),
            "tenant_id": str(tenant_id),
            "suite_id": trial.suite_id,
            "suite_version": trial.suite_version,
            "subject_version_id": str(subject_version_id),
            "harness_version": trial.harness_version,
            "status": trial.status.value,
            "result": trial_payload(trial),
        }
    )

    assert restored == trial
