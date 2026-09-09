/**
 * Typed API client for the Autonoesis control plane.
 *
 * Reads connection settings (base URL, tenant, actor identity, roles) from
 * localStorage so operators can point the console at any deployment. Every
 * mutation carries a fresh Idempotency-Key and the operator identity headers;
 * errors surface the platform's uniform envelope instead of raw text.
 */

export type ApiSettings = {
  baseUrl: string;
  tenantId: string;
  actorId: string;
  principalId: string;
  roles: string;
};

const SETTINGS_KEY = "autonoesis.console.settings";

export const DEFAULT_SETTINGS: ApiSettings = {
  baseUrl: (import.meta.env.VITE_AUTONOESIS_API_URL as string | undefined) ?? "/",
  tenantId: "",
  actorId: "",
  principalId: "",
  roles: "tenant_admin,operator,approver,release_executor",
};

export function loadSettings(): ApiSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<ApiSettings>) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: ApiSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly correlationId?: string,
    readonly auditRef?: string | null,
  ) {
    super(message);
  }
}

function requireSettings(): ApiSettings {
  const settings = loadSettings();
  if (!settings.tenantId || !settings.actorId) {
    throw new ApiError(
      0,
      "console_not_configured",
      "请先在“连接设置”中填写租户与操作者身份（X-Tenant-ID / X-Actor-ID）。",
    );
  }
  return settings;
}

export async function apiGet<T>(path: string): Promise<T> {
  const settings = requireSettings();
  const response = await fetch(`${settings.baseUrl.replace(/\/$/, "")}${path}`, {
    headers: identityHeaders(settings),
  });
  return unwrap<T>(response);
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  idempotencyKey?: string,
): Promise<T> {
  const settings = requireSettings();
  const response = await fetch(`${settings.baseUrl.replace(/\/$/, "")}${path}`, {
    method: "POST",
    headers: {
      ...identityHeaders(settings),
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey ?? crypto.randomUUID(),
    },
    body: JSON.stringify(body ?? {}),
  });
  return unwrap<T>(response);
}

export async function apiDelete<T>(path: string, idempotencyKey?: string): Promise<T> {
  const settings = requireSettings();
  const response = await fetch(`${settings.baseUrl.replace(/\/$/, "")}${path}`, {
    method: "DELETE",
    headers: {
      ...identityHeaders(settings),
      "Idempotency-Key": idempotencyKey ?? crypto.randomUUID(),
    },
  });
  return unwrap<T>(response);
}

function identityHeaders(settings: ApiSettings): Record<string, string> {
  return {
    "X-Tenant-ID": settings.tenantId,
    "X-Actor-ID": settings.actorId,
    "X-Principal-ID": settings.principalId || settings.actorId,
    "X-Roles": settings.roles,
  };
}

async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }
  let code = `http_${response.status}`;
  let message = `请求失败（HTTP ${response.status}）`;
  let correlationId: string | undefined;
  let auditRef: string | null = null;
  try {
    const payload = (await response.json()) as {
      error?: { code?: string; message?: string; correlation_id?: string; audit_ref?: string | null };
    };
    if (payload.error) {
      code = payload.error.code ?? code;
      message = payload.error.message ?? message;
      correlationId = payload.error.correlation_id;
      auditRef = payload.error.audit_ref ?? null;
    }
  } catch {
    // Non-JSON error bodies keep the generic message.
  }
  throw new ApiError(response.status, code, message, correlationId, auditRef);
}

export function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
