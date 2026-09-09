/**
 * Real-data console pages backed by the platform API.
 *
 * Every page renders loading, error, and empty states explicitly — the console
 * never substitutes sample rows for missing API data.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, apiGet, apiPost, loadSettings, saveSettings, type ApiSettings } from "./api";

export type Row = Record<string, unknown>;

function isScalar(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (isScalar(value)) return String(value);
  return JSON.stringify(value);
}

export function ResourcePage({
  title,
  eyebrow,
  description,
  path,
  columns,
}: {
  title: string;
  eyebrow: string;
  description: string;
  path: string;
  columns: string[];
}) {
  const query = useQuery({
    queryKey: ["resource", path],
    queryFn: () => apiGet<Row[]>(path),
  });
  const rows = query.data ?? [];
  return (
    <div className="page">
      <PageHeader eyebrow={`${eyebrow} · LIVE API`} title={title} description={description} />
      <ConnectionBar />
      <section className="section-grid">
        <div className="panel table-panel">
          <div className="panel-title">
            <h3>真实数据（{path}）</h3>
            <button onClick={() => query.refetch()} disabled={query.isFetching}>
              <RefreshCw size={14} /> 刷新
            </button>
          </div>
          {query.isLoading ? (
            <p className="state-note">加载中…</p>
          ) : query.isError ? (
            <p className="state-note error">
              <AlertTriangle size={14} /> API 不可用或未配置：{(query.error as Error).message}
            </p>
          ) : rows.length === 0 ? (
            <p className="state-note">无数据（空状态，非样例）</p>
          ) : (
            <div className="table-head">
              {columns.map((column) => (
                <span key={column}>{column}</span>
              ))}
            </div>
          )}
          {rows.map((row, index) => (
            <div className="table-row" key={index}>
              {columns.map((column) => (
                <small key={column}>{formatCell(row[column])}</small>
              ))}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function ConnectionBar() {
  const [settings, setSettings] = useState<ApiSettings>(() => loadSettings());
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  useEffect(() => saveSettings(settings), [settings]);
  return (
    <div className="panel connection-bar">
      <button className="link-button" onClick={() => setOpen(!open)}>
        连接设置（API 地址 / 租户 / 身份）
      </button>
      {open && (
        <div className="connection-form">
          {(
            [
              ["baseUrl", "API 地址"],
              ["tenantId", "租户 ID (X-Tenant-ID)"],
              ["actorId", "操作者 (X-Actor-ID)"],
              ["principalId", "Principal ID"],
              ["roles", "角色（逗号分隔）"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              <span>{label}</span>
              <input
                value={settings[key]}
                onChange={(event) =>
                  setSettings({ ...settings, [key]: event.target.value })
                }
              />
            </label>
          ))}
          <button
            onClick={() => {
              saveSettings(settings);
              queryClient.invalidateQueries();
            }}
          >
            保存并刷新
          </button>
        </div>
      )}
      {!settings.tenantId && (
        <p className="state-note error">
          未配置租户身份：所有真实数据页面将显示错误状态（不会回退到样例数据）。
        </p>
      )}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="page-header">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}

/** High-risk operations: typed confirmation + fresh idempotency key. */
export function ConfirmDialog({
  action,
  requireText,
  fields,
  onSubmit,
}: {
  action: string;
  requireText: string;
  fields: Array<{ key: string; label: string; placeholder?: string; type?: string }>;
  onSubmit: (values: Record<string, string>, idempotencyKey: string) => Promise<unknown>;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState("");
  const mutation = useMutation({ mutationFn: () => onSubmit(values, crypto.randomUUID()) });
  const ready = confirmed === requireText;
  return (
    <div className="confirm-dialog">
      <p className="confirm-title">
        <AlertTriangle size={15} /> {action}
      </p>
      {fields.map((field) => (
        <label key={field.key}>
          <span>{field.label}</span>
          <input
            type={field.type ?? "text"}
            placeholder={field.placeholder}
            value={values[field.key] ?? ""}
            onChange={(event) =>
              setValues({ ...values, [field.key]: event.target.value })
            }
          />
        </label>
      ))}
      <label>
        <span>输入 {requireText} 以确认</span>
        <input value={confirmed} onChange={(event) => setConfirmed(event.target.value)} />
      </label>
      <button disabled={!ready || mutation.isPending} onClick={() => mutation.mutate()}>
        {mutation.isPending ? "提交中…" : "执行（携带幂等键）"}
      </button>
      {mutation.isError && (
        <p className="state-note error">失败：{(mutation.error as Error).message}</p>
      )}
      {mutation.isSuccess && <p className="state-note">已提交。请刷新查看权威状态。</p>}
    </div>
  );
}

export function useApiQuery<T>(key: unknown[], path: string, enabled = true) {
  return useQuery({
    queryKey: key,
    queryFn: () => apiGet<T>(path),
    enabled,
    retry: false,
  });
}

export { ApiError, apiGet, apiPost };
