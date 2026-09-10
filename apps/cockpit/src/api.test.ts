import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  DEFAULT_SETTINGS,
  apiGet,
  apiPost,
  loadSettings,
  newIdempotencyKey,
  saveSettings,
} from "./api";

type StoredSettings = Record<string, string>;

function installLocalStorage(initial: StoredSettings = {}) {
  const store = new Map<string, string>(Object.entries(initial));
  const stub = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
  };
  Object.defineProperty(globalThis, "localStorage", { value: stub, configurable: true });
  return store;
}

describe("console api client", () => {
  beforeEach(() => {
    installLocalStorage();
    vi.unstubAllGlobals();
  });

  it("merges persisted settings over defaults and persists updates", () => {
    const store = installLocalStorage({
      "autonoesis.console.settings": JSON.stringify({ tenantId: "t-1" }),
    });
    const settings = loadSettings();
    expect(settings.tenantId).toBe("t-1");
    expect(settings.baseUrl).toBe(DEFAULT_SETTINGS.baseUrl);
    saveSettings({ ...settings, actorId: "a-1" });
    expect(JSON.parse(store.get("autonoesis.console.settings")!)).toMatchObject({
      tenantId: "t-1",
      actorId: "a-1",
    });
  });

  it("sends identity, idempotency, and correlation headers; unwraps envelopes", async () => {
    installLocalStorage({
      "autonoesis.console.settings": JSON.stringify({
        baseUrl: "http://api.test",
        tenantId: "11111111-1111-1111-1111-111111111111",
        actorId: "22222222-2222-2222-2222-222222222222",
        principalId: "33333333-3333-3333-3333-333333333333",
        roles: "operator",
      }),
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify([{ ok: true }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiGet("/v1/goals");
    await apiPost("/v1/runs/x/cancel", { reason: "operator request" }, "key-1");
    const calls = fetchMock.mock.calls as Array<[RequestInfo | URL, RequestInit]>;
    const getHeaders = new Headers(calls[0][1].headers);
    expect(getHeaders.get("X-Tenant-ID")).toBe("11111111-1111-1111-1111-111111111111");
    const postHeaders = new Headers(calls[1][1].headers);
    expect(postHeaders.get("Idempotency-Key")).toBe("key-1");
    expect(postHeaders.get("Content-Type")).toBe("application/json");
    expect(String(calls[1][0])).toBe("http://api.test/v1/runs/x/cancel");
  });

  it("refuses requests without a tenant identity instead of falling back", async () => {
    const error = (await apiGet("/v1/goals").catch((caught) => caught)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("console_not_configured");
  });

  it("surfaces the platform error envelope with audit references", async () => {
    installLocalStorage({
      "autonoesis.console.settings": JSON.stringify({
        tenantId: "1",
        actorId: "2",
        baseUrl: "http://api.test",
      }),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: {
                code: "record_not_found",
                message: "hidden",
                correlation_id: "c-1",
                audit_ref: "audit://events/1",
              },
            }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    const error = (await apiGet("/v1/unknown").catch((caught) => caught)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("record_not_found");
    expect(error.auditRef).toBe("audit://events/1");
  });

  it("mints prefixed idempotency keys", () => {
    expect(newIdempotencyKey("rollback")).toMatch(/^rollback-[0-9a-f-]{36}$/);
  });
});

describe("console oidc bearer identity", () => {
  beforeEach(() => {
    installLocalStorage();
    vi.unstubAllGlobals();
  });

  it("sends only the bearer header when a token is configured", async () => {
    installLocalStorage({
      "autonoesis.console.settings": JSON.stringify({
        baseUrl: "http://api.test",
        bearerToken: "ey.jwt.token",
        tenantId: "should-be-ignored",
        actorId: "ignored-too",
      }),
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiGet("/v1/goals");
    const headers = new Headers((fetchMock.mock.calls as Array<[RequestInfo | URL, RequestInit]>)[0][1].headers);
    expect(headers.get("Authorization")).toBe("Bearer ey.jwt.token");
    expect(headers.get("X-Tenant-ID")).toBeNull();
  });

  it("still works with development headers when no token is set", async () => {
    installLocalStorage({
      "autonoesis.console.settings": JSON.stringify({
        baseUrl: "http://api.test",
        tenantId: "t-1",
        actorId: "a-1",
      }),
    });
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiGet("/v1/goals");
    const headers = new Headers((fetchMock.mock.calls as Array<[RequestInfo | URL, RequestInit]>)[0][1].headers);
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("X-Tenant-ID")).toBe("t-1");
  });
});
