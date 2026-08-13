"""Lossless codecs between domain aggregates and authoritative JSON columns."""

from datetime import datetime
from typing import Any
from uuid import UUID

from autonoesis_domain import (
    Action,
    ActionAttempt,
    ActionAttemptStatus,
    ActionStatus,
    ApprovalRequest,
    ApprovalReview,
    ApprovalStatus,
    BudgetAmount,
    BudgetUnit,
    CandidateStatus,
    CandidateVersion,
    CompensationCapability,
    ContextSnapshot,
    DataClassification,
    Deployment,
    DeploymentStatus,
    EnvironmentFact,
    Evidence,
    EvidenceCaptureMethod,
    EvidenceIntegrity,
    ExecutionMode,
    ImprovementProposal,
    ImprovementTarget,
    JsonObject,
    KnowledgeRef,
    Outcome,
    OutcomeStatus,
    Plan,
    Release,
    RiskLevel,
    Run,
    RunExecutionSnapshot,
    RunStatus,
    StateTransition,
    SubjectRef,
    Task,
    TaskStatus,
    Trial,
    TrialStatus,
    TrustLevel,
)


def transition_payload(item: StateTransition) -> dict[str, str]:
    return {
        "from_status": item.from_status,
        "to_status": item.to_status,
        "occurred_at": item.occurred_at.isoformat(),
        "reason": item.reason,
        "actor_id": str(item.actor_id),
    }


def transitions_from(payload: object) -> tuple[StateTransition, ...]:
    if not isinstance(payload, list):
        return ()
    return tuple(
        StateTransition(
            from_status=item["from_status"],
            to_status=item["to_status"],
            occurred_at=datetime.fromisoformat(item["occurred_at"]),
            reason=item["reason"],
            actor_id=UUID(item["actor_id"]),
        )
        for item in payload
    )


def run_payload(run: Run) -> dict[str, Any]:
    snapshot = run.execution_snapshot
    return {
        "execution_snapshot": (
            {
                "plan_id": str(snapshot.plan_id),
                "context_snapshot_id": str(snapshot.context_snapshot_id),
                "agent_version_id": str(snapshot.agent_version_id),
                "skill_versions": snapshot.skill_versions,
                "tool_versions": snapshot.tool_versions,
                "model_route": snapshot.model_route,
                "policy_version": snapshot.policy_version,
            }
            if snapshot is not None
            else None
        ),
        "transitions": [transition_payload(item) for item in run.transitions],
    }


def run_from_row(row: dict[str, Any]) -> Run:
    definition = row["definition"] or {}
    snapshot = definition.get("execution_snapshot")
    return Run(
        tenant_id=UUID(row["tenant_id"]),
        goal_id=UUID(row["goal_id"]),
        agent_version_id=UUID(row["agent_version_id"]),
        execution_snapshot=(
            RunExecutionSnapshot(
                plan_id=UUID(snapshot["plan_id"]),
                context_snapshot_id=UUID(snapshot["context_snapshot_id"]),
                agent_version_id=UUID(snapshot["agent_version_id"]),
                skill_versions=tuple(snapshot["skill_versions"]),
                tool_versions=tuple(snapshot["tool_versions"]),
                model_route=snapshot["model_route"],
                policy_version=snapshot["policy_version"],
            )
            if snapshot
            else None
        ),
        run_id=UUID(row["id"]),
        status=RunStatus(row["status"]),
        optimistic_version=row["optimistic_version"],
        created_at=row["created_at"],
        transitions=transitions_from(definition.get("transitions")),
    )


def task_payload(task: Task) -> dict[str, Any]:
    return {
        "name": task.name,
        "completion_criterion": task.completion_criterion,
        "depends_on": [str(item) for item in task.depends_on],
        "preconditions": task.preconditions,
        "estimated_cost": {
            "amount": task.estimated_cost.amount,
            "unit": task.estimated_cost.unit.value,
        },
        "risk_level": task.risk_level.value,
        "compensation": task.compensation.value,
        "evidence_requirements": task.evidence_requirements,
        "transitions": [transition_payload(item) for item in task.transitions],
    }


def task_from_row(row: dict[str, Any]) -> Task:
    definition = row["definition"]
    estimated = definition["estimated_cost"]
    return Task(
        tenant_id=UUID(row["tenant_id"]),
        run_id=UUID(row["run_id"]),
        name=definition["name"],
        completion_criterion=definition["completion_criterion"],
        depends_on=tuple(UUID(item) for item in definition["depends_on"]),
        preconditions=tuple(definition["preconditions"]),
        estimated_cost=BudgetAmount(estimated["amount"], BudgetUnit(estimated["unit"])),
        risk_level=RiskLevel(definition["risk_level"]),
        compensation=CompensationCapability(definition["compensation"]),
        evidence_requirements=tuple(definition["evidence_requirements"]),
        task_id=UUID(row["id"]),
        status=TaskStatus(row["status"]),
        optimistic_version=row["optimistic_version"],
        transitions=transitions_from(definition.get("transitions")),
    )


def plan_from_rows(plan_row: dict[str, Any], task_rows: list[dict[str, Any]]) -> Plan:
    return Plan(
        tenant_id=UUID(plan_row["tenant_id"]),
        goal_id=UUID(plan_row["goal_id"]),
        run_id=UUID(plan_row["run_id"]),
        tasks=tuple(task_from_row(row) for row in task_rows),
        version=plan_row["version"],
        plan_id=UUID(plan_row["id"]),
    )


def action_payload(action: Action) -> dict[str, Any]:
    return {
        "tool_name": action.tool_name,
        "tool_version": action.tool_version,
        "operation": action.operation,
        "resource_scope": action.resource_scope,
        "parameters": action.parameters.to_value(),
        "risk_level": action.risk_level.value,
        "expected_effect": action.expected_effect,
        "classification": action.classification.value,
        "execution_mode": action.execution_mode.value,
        "transitions": [transition_payload(item) for item in action.transitions],
    }


def action_from_row(row: dict[str, Any]) -> Action:
    definition = row["definition"]
    return Action(
        tenant_id=UUID(row["tenant_id"]),
        run_id=UUID(row["run_id"]),
        task_id=UUID(row["task_id"]),
        tool_name=definition["tool_name"],
        tool_version=definition["tool_version"],
        operation=definition["operation"],
        resource_scope=definition["resource_scope"],
        parameters=JsonObject.from_value(definition["parameters"]),
        risk_level=RiskLevel(definition["risk_level"]),
        idempotency_key=row["idempotency_key"],
        expected_effect=definition["expected_effect"],
        classification=DataClassification(definition["classification"]),
        execution_mode=ExecutionMode(definition["execution_mode"]),
        action_id=UUID(row["id"]),
        status=ActionStatus(row["status"]),
        optimistic_version=row["optimistic_version"],
        transitions=transitions_from(definition.get("transitions")),
    )


def action_attempt_payload(item: ActionAttempt) -> dict[str, Any]:
    return {
        "executor_identity": item.executor_identity,
        "failure_reason": item.failure_reason,
        "recorded_at": item.recorded_at.isoformat(),
    }


def action_attempt_from_row(row: dict[str, Any]) -> ActionAttempt:
    definition = row["definition"]
    return ActionAttempt(
        tenant_id=UUID(row["tenant_id"]),
        run_id=UUID(row["run_id"]),
        action_id=UUID(row["action_id"]),
        invocation_id=UUID(row["invocation_id"]),
        status=ActionAttemptStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        receipt_ref=row["receipt_ref"],
        executor_identity=definition["executor_identity"],
        failure_reason=definition.get("failure_reason"),
        attempt_id=UUID(row["id"]),
        recorded_at=datetime.fromisoformat(definition["recorded_at"]),
    )


def context_snapshot_payload(item: ContextSnapshot) -> dict[str, Any]:
    return {
        "environment_facts": [
            {
                "fact_id": fact.fact_id,
                "source": fact.source,
                "subject": fact.subject,
                "value": fact.value,
                "observed_at": fact.observed_at.isoformat(),
                "valid_until": fact.valid_until.isoformat(),
                "trust": fact.trust.value,
            }
            for fact in item.environment_facts
        ],
        "knowledge_refs": [
            {
                "knowledge_id": ref.knowledge_id,
                "version": ref.version,
                "source": ref.source,
                "citation": ref.citation,
                "trust": ref.trust.value,
            }
            for ref in item.knowledge_refs
        ],
        "memory_ids": [str(value) for value in item.memory_ids],
        "history_digest": item.history_digest,
        "tool_versions": list(item.tool_versions),
        "conflicts": list(item.conflicts),
        "created_at": item.created_at.isoformat(),
    }


def context_snapshot_from_row(row: dict[str, Any]) -> ContextSnapshot:
    payload = row["payload"]
    return ContextSnapshot(
        tenant_id=UUID(row["tenant_id"]),
        goal_id=UUID(row["goal_id"]),
        run_id=UUID(row["run_id"]),
        environment_facts=tuple(
            EnvironmentFact(
                fact_id=fact["fact_id"],
                source=fact["source"],
                subject=fact["subject"],
                value=fact["value"],
                observed_at=datetime.fromisoformat(fact["observed_at"]),
                valid_until=datetime.fromisoformat(fact["valid_until"]),
                trust=TrustLevel(fact["trust"]),
            )
            for fact in payload["environment_facts"]
        ),
        knowledge_refs=tuple(
            KnowledgeRef(
                knowledge_id=ref["knowledge_id"],
                version=ref["version"],
                source=ref["source"],
                citation=ref["citation"],
                trust=TrustLevel(ref["trust"]),
            )
            for ref in payload["knowledge_refs"]
        ),
        memory_ids=tuple(UUID(value) for value in payload["memory_ids"]),
        history_digest=payload["history_digest"],
        tool_versions=tuple(payload["tool_versions"]),
        conflicts=tuple(payload["conflicts"]),
        snapshot_id=UUID(row["id"]),
        created_at=datetime.fromisoformat(payload["created_at"]),
    )


def approval_payload(approval: ApprovalRequest) -> dict[str, Any]:
    return {
        "tool_version": approval.tool_version,
        "operation": approval.operation,
        "resource_scope": approval.resource_scope,
        "argument_digest": approval.argument_digest,
        "policy_version": approval.policy_version,
        "impact_summary": approval.impact_summary,
        "required_role": approval.required_role,
        "decided_by": str(approval.decided_by) if approval.decided_by else None,
        "reason": approval.reason,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "required_reviews": approval.required_reviews,
        "reviews": [
            {
                "actor_id": str(review.actor_id),
                "principal_id": str(review.principal_id),
                "approved": review.approved,
                "reason": review.reason,
                "reviewed_at": review.reviewed_at.isoformat(),
            }
            for review in approval.reviews
        ],
        "transitions": [transition_payload(item) for item in approval.transitions],
    }


def approval_from_row(row: dict[str, Any]) -> ApprovalRequest:
    definition = row["definition"]
    return ApprovalRequest(
        tenant_id=UUID(row["tenant_id"]),
        run_id=UUID(row["run_id"]),
        action_id=UUID(row["action_id"]),
        action_digest=row["action_digest"],
        tool_version=definition["tool_version"],
        operation=definition["operation"],
        resource_scope=definition["resource_scope"],
        argument_digest=definition["argument_digest"],
        policy_version=definition["policy_version"],
        impact_summary=definition["impact_summary"],
        required_role=definition["required_role"],
        expires_at=row["expires_at"],
        approval_id=UUID(row["id"]),
        status=ApprovalStatus(row["status"]),
        decided_by=UUID(definition["decided_by"]) if definition.get("decided_by") else None,
        reason=definition.get("reason"),
        created_at=row["created_at"],
        decided_at=(
            datetime.fromisoformat(definition["decided_at"])
            if definition.get("decided_at")
            else None
        ),
        optimistic_version=row["optimistic_version"],
        transitions=transitions_from(definition.get("transitions")),
        required_reviews=int(definition.get("required_reviews", 1)),
        reviews=tuple(
            ApprovalReview(
                actor_id=UUID(item["actor_id"]),
                principal_id=UUID(item["principal_id"]),
                approved=bool(item["approved"]),
                reason=item["reason"],
                reviewed_at=datetime.fromisoformat(item["reviewed_at"]),
            )
            for item in definition.get("reviews", ())
        ),
    )


def evidence_payload(item: Evidence) -> dict[str, Any]:
    return {
        "observed_state": item.observed_state,
        "captured_at": item.captured_at.isoformat(),
        "source_reference": item.source_reference,
        "subject_refs": [
            {
                "system": value.system,
                "subject_type": value.subject_type,
                "subject_id": value.subject_id,
                "version": value.version,
            }
            for value in item.subject_refs
        ],
        "retained_until": item.retained_until.isoformat() if item.retained_until else None,
        "artifact_version_id": item.artifact_version_id,
    }


def evidence_from_row(row: dict[str, Any]) -> Evidence:
    definition = row["definition"]
    return Evidence(
        tenant_id=UUID(row["tenant_id"]),
        run_id=UUID(row["run_id"]),
        action_id=UUID(row["action_id"]),
        source=row["source"],
        source_identity=row["source_identity"],
        capture_method=EvidenceCaptureMethod(row["capture_method"]),
        reference=row["artifact_uri"],
        observed_state=definition["observed_state"],
        content_digest=row["content_digest"],
        classification=DataClassification(row["classification"]),
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        integrity=EvidenceIntegrity(row["integrity"]),
        source_reference=definition.get("source_reference", ""),
        subject_refs=tuple(
            SubjectRef(
                value["system"], value["subject_type"], value["subject_id"], value.get("version")
            )
            for value in definition.get("subject_refs", ())
        ),
        retained_until=(
            datetime.fromisoformat(definition["retained_until"])
            if definition.get("retained_until")
            else None
        ),
        artifact_version_id=definition.get("artifact_version_id"),
        evidence_id=UUID(row["id"]),
        captured_at=datetime.fromisoformat(definition["captured_at"]),
    )


def outcome_payload(item: Outcome) -> dict[str, Any]:
    return {
        "evidence_ids": [str(value) for value in item.evidence_ids],
        "verified_at": item.verified_at.isoformat() if item.verified_at else None,
    }


def outcome_from_row(row: dict[str, Any], evidence_items: tuple[Evidence, ...]) -> Outcome:
    payload = row["result"]
    return Outcome(
        tenant_id=UUID(row["tenant_id"]),
        goal_id=UUID(row["goal_id"]),
        run_id=UUID(row["run_id"]),
        criterion_id=row["criterion_id"],
        verifier_version=row["verifier_version"],
        status=OutcomeStatus(row["status"]),
        evidence=evidence_items,
        outcome_id=UUID(row["id"]),
        verified_at=(
            datetime.fromisoformat(payload["verified_at"]) if payload.get("verified_at") else None
        ),
    )


def proposal_payload(item: ImprovementProposal) -> dict[str, Any]:
    return {
        "evidence_refs": item.evidence_refs,
        "diagnosis": item.diagnosis,
        "proposed_change": item.proposed_change,
        "validation_suite_id": item.validation_suite_id,
        "rollback_plan": item.rollback_plan,
        "proposer_id": item.proposer_id,
    }


def proposal_from_row(row: dict[str, Any]) -> ImprovementProposal:
    payload = row["proposal"]
    return ImprovementProposal(
        tenant_id=UUID(row["tenant_id"]),
        target=ImprovementTarget(row["target_type"]),
        target_version_id=UUID(row["target_version_id"]),
        evidence_refs=tuple(payload["evidence_refs"]),
        diagnosis=payload["diagnosis"],
        proposed_change=payload["proposed_change"],
        validation_suite_id=payload["validation_suite_id"],
        rollback_plan=payload["rollback_plan"],
        proposer_id=payload["proposer_id"],
        proposal_id=UUID(row["id"]),
    )


def candidate_payload(item: CandidateVersion) -> dict[str, Any]:
    return {
        "transitions": [transition_payload(value) for value in item.transitions],
        "grader_principal_id": item.grader_principal_id,
        "approver_principal_id": item.approver_principal_id,
    }


def candidate_from_row(row: dict[str, Any]) -> CandidateVersion:
    definition = row["definition"]
    return CandidateVersion(
        tenant_id=UUID(row["tenant_id"]),
        proposal_id=UUID(row["proposal_id"]),
        baseline_version_id=UUID(row["baseline_version_id"]),
        artifact_ref=row["artifact_uri"],
        generator_id=row["generator_id"],
        candidate_id=UUID(row["id"]),
        status=CandidateStatus(row["status"]),
        optimistic_version=row["optimistic_version"],
        transitions=transitions_from(definition.get("transitions")),
        grader_principal_id=definition.get("grader_principal_id"),
        approver_principal_id=definition.get("approver_principal_id"),
    )


def deployment_payload(item: Deployment) -> dict[str, Any]:
    return {"transitions": [transition_payload(value) for value in item.transitions]}


def deployment_from_row(row: dict[str, Any]) -> Deployment:
    return Deployment(
        tenant_id=UUID(row["tenant_id"]),
        candidate_id=UUID(row["candidate_id"]),
        status=DeploymentStatus(row["status"]),
        deployment_id=UUID(row["id"]),
        optimistic_version=row["optimistic_version"],
        transitions=transitions_from(row["definition"].get("transitions")),
    )


def release_payload(item: Release) -> dict[str, str]:
    return {"approved_by": str(item.approved_by)}


def release_from_row(row: dict[str, Any]) -> Release:
    return Release(
        tenant_id=UUID(row["tenant_id"]),
        candidate_id=UUID(row["candidate_id"]),
        deployment_id=UUID(row["deployment_id"]),
        stable_version_id=UUID(row["stable_version_id"]),
        previous_stable_version_id=UUID(row["previous_stable_version_id"]),
        approved_by=UUID(row["approved_by"]),
        release_id=UUID(row["id"]),
    )


def trial_payload(item: Trial) -> dict[str, Any]:
    return {}


def trial_from_row(row: dict[str, Any]) -> Trial:
    return Trial(
        tenant_id=UUID(row["tenant_id"]),
        suite_id=row["suite_id"],
        suite_version=row["suite_version"],
        subject_version_id=UUID(row["subject_version_id"]),
        harness_version=row["harness_version"],
        trial_id=UUID(row["id"]),
        status=TrialStatus(row["status"]),
    )
