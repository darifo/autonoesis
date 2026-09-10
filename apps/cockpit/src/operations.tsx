/**
 * Operations center: the five high-risk operator surfaces required by P1-07 —
 * approval decisions, unknown-action reconciliation, kill switch, release
 * rollback, and manual run takeover/cancel. Each action demands role headers,
 * a fresh idempotency key, and a typed confirmation before dispatch.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiDelete, apiPost, newIdempotencyKey } from "./api";
import type {
  ApprovalDecisionRequest,
  HumanDecisionRequest,
  ReconcileRequest,
  RunControlRequest,
} from "./contract";
import { ConfirmDialog, PageHeader, useApiQuery } from "./pages";

type ApprovalRow = {
  approval_id: string;
  run_id: string;
  status: string;
  required_role: string;
  expires_at: string;
  impact_summary?: string;
  action_digest?: string;
};

type RunRow = { run_id: string; goal_id: string; status: string };
type ActionRow = { action_id: string; run_id: string; tool_name: string; status: string };
type ReleaseRow = { release_id: string; stable_version_id: string; candidate_id: string };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel table-panel">
      <div className="panel-title">
        <h3>{title}</h3>
      </div>
      {children}
    </div>
  );
}

export function OperationsPage() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries();

  const approvals = useApiQuery<ApprovalRow[]>(["approvals"], "/v1/approvals");
  const runs = useApiQuery<RunRow[]>(["runs"], "/v1/runs");
  const releases = useApiQuery<ReleaseRow[]>(["releases"], "/v1/releases");

  const [selectedRun, setSelectedRun] = useState<string>("");
  const actions = useApiQuery<ActionRow[]>(
    ["run-actions", selectedRun],
    `/v1/runs/${selectedRun}/actions`,
    Boolean(selectedRun),
  );
  const unknownActions = (actions.data ?? []).filter(
    (action) => action.status === "unknown",
  );

  return (
    <div className="page">
      <PageHeader
        eyebrow="OPERATIONS · LIVE API"
        title="运营操作中心"
        description="审批处置、Unknown 对账、Kill Switch、回滚与人工接管。所有高风险操作要求角色权限、幂等键和输入目标标识的二次确认。"
      />
      <Section title={`审批处置（${approvals.data?.length ?? 0} 条）`}>
        {approvals.isError && <p className="state-note error">审批队列不可用：{(approvals.error as Error).message}</p>}
        {approvals.data?.map((approval) => (
          <div className="table-row" key={approval.approval_id}>
            <strong>{approval.approval_id}</strong>
            <span>{approval.impact_summary ?? approval.status}</span>
            <small>{approval.action_digest ?? "无摘要"}</small>
          </div>
        ))}
        {approvals.data && approvals.data.length > 0 && (
          <ConfirmDialog
            action="审批决策（批准需独立理由）"
            requireText="APPROVE"
            fields={[
              { key: "approval_id", label: "Approval ID", placeholder: "从上方列表复制" },
              {
                key: "action_digest",
                label: "Action 摘要（action_digest，二次确认素材）",
                placeholder: "从上方列表复制",
              },
              { key: "reason", label: "决策理由（必填）" },
            ]}
            onSubmit={async (values, key) => {
              const body: ApprovalDecisionRequest = {
                approved: true,
                action_digest: values.action_digest,
                reason: values.reason,
              };
              const result = await apiPost(
                `/v1/approvals/${values.approval_id}/decision`,
                body,
                key,
              );
              refresh();
              return result;
            }}
          />
        )}
      </Section>

      <Section title="Unknown Action 对账">
        <label className="inline-field">
          <span>选择 Run</span>
          <select
            value={selectedRun}
            onChange={(event) => setSelectedRun(event.target.value)}
          >
            <option value="">—</option>
            {(runs.data ?? []).map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.run_id}（{run.status}）
              </option>
            ))}
          </select>
        </label>
        {selectedRun && actions.isError && (
          <p className="state-note error">无法加载 Action：{(actions.error as Error).message}</p>
        )}
        {unknownActions.map((action) => (
          <div className="table-row" key={action.action_id}>
            <strong>{action.action_id}</strong>
            <span>{action.tool_name}</span>
            <small>unknown — 需权威回读对账</small>
          </div>
        ))}
        {selectedRun && (actions.data ?? []).length > 0 && unknownActions.length === 0 && (
          <p className="state-note">该 Run 当前没有 Unknown Action。</p>
        )}
        {unknownActions.length > 0 && (
          <ConfirmDialog
            action="Unknown 对账（以权威凭证为准，禁止臆断）"
            requireText="RECONCILE"
            fields={[
              { key: "action_id", label: "Action ID", placeholder: "从上方列表复制" },
              { key: "invocation_id", label: "外部调用 ID（invocation_id）" },
              { key: "receipt_ref", label: "权威凭证引用（receipt_ref）" },
              { key: "succeeded", label: "外部状态为成功？(true/false)" },
              { key: "failure_reason", label: "失败原因（失败时填写）" },
            ]}
            onSubmit={async (values, key) => {
              const body: ReconcileRequest = {
                invocation_id: values.invocation_id,
                succeeded: values.succeeded === "true",
                receipt_ref: values.receipt_ref,
                failure_reason: values.failure_reason || null,
              };
              const result = await apiPost(
                `/v1/actions/${values.action_id}/reconcile`,
                body,
                key,
              );
              refresh();
              return result;
            }}
          />
        )}
      </Section>

      <Section title="Kill Switch（租户维度）">
        <ConfirmDialog
          action="激活租户 Kill Switch（阻断后续外部副作用）"
          requireText="HALT"
          fields={[{ key: "reason", label: "原因（必填，进入审计链）" }]}
          onSubmit={async (values, key) => {
            const settings = await import("./api").then((m) => m.loadSettings());
            const result = await apiPost(
              "/v1/kill-switches",
              { dimension: "tenant", target: settings.tenantId, reason: values.reason },
              key,
            );
            refresh();
            return result;
          }}
        />
        <ConfirmDialog
          action="解除租户 Kill Switch（需要解除理由）"
          requireText="RESUME"
          fields={[{ key: "reason", label: "解除理由（必填）" }]}
          onSubmit={async (values, key) => {
            const settings = await import("./api").then((m) => m.loadSettings());
            const result = await apiDelete(
              `/v1/kill-switches?dimension=tenant&target=${settings.tenantId}`,
              key,
            );
            refresh();
            return result;
          }}
        />
      </Section>

      <Section title={`发布回滚（${releases.data?.length ?? 0} 个 Release）`}>
        {releases.data?.map((release) => (
          <div className="table-row" key={release.release_id}>
            <strong>{release.release_id}</strong>
            <span>stable → {release.stable_version_id}</span>
            <small>candidate: {release.candidate_id}</small>
          </div>
        ))}
        <ConfirmDialog
          action="回滚 Release（经独立 Release Executor 派发）"
          requireText="ROLLBACK"
          fields={[{ key: "release_id", label: "Release ID", placeholder: "从上方列表复制" }]}
          onSubmit={async (values, key) => {
            const result = await apiPost(
              `/v1/releases/${values.release_id}/rollback`,
              {},
              key,
            );
            refresh();
            return result;
          }}
        />
      </Section>

      <Section title="人工接管 / 取消 Run">
        <ConfirmDialog
          action="人工接管 Run（Run 转入 BLOCKED，自动化停止）"
          requireText="TAKEOVER"
          fields={[
            { key: "run_id", label: "Run ID" },
            { key: "reason", label: "接管理由（必填）" },
          ]}
          onSubmit={async (values, key) => {
            const body: RunControlRequest = { reason: values.reason };
            const result = await apiPost(`/v1/runs/${values.run_id}/takeover`, body, key);
            refresh();
            return result;
          }}
        />
        <ConfirmDialog
          action="取消 Run（记录取消原因）"
          requireText="CANCEL"
          fields={[
            { key: "run_id", label: "Run ID" },
            { key: "reason", label: "取消理由（必填）" },
          ]}
          onSubmit={async (values, key) => {
            const body: RunControlRequest = { reason: values.reason };
            const result = await apiPost(`/v1/runs/${values.run_id}/cancel`, body, key);
            refresh();
            return result;
          }}
        />
      </Section>
    </div>
  );
}

export { newIdempotencyKey };
