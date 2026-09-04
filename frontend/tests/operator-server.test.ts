import assert from "node:assert/strict";
import test from "node:test";

import { performOperatorAction } from "../src/lib/operator-server";

const PASSWORD = "operator-password";
const ADMIN_SECRET = "admin-secret";
const BASE_URL = "https://api.example.invalid";

function configure({
  password = PASSWORD,
  adminSecret = ADMIN_SECRET,
  baseUrl = BASE_URL,
}: {
  password?: string;
  adminSecret?: string;
  baseUrl?: string;
} = {}) {
  process.env.ADMIN_PANEL_PASSWORD = password;
  process.env.REGRET_API_ADMIN_SECRET = adminSecret;
  process.env.REGRET_API_BASE_URL = baseUrl;
}

function reset() {
  delete process.env.ADMIN_PANEL_PASSWORD;
  delete process.env.REGRET_API_ADMIN_SECRET;
  delete process.env.REGRET_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
}

function okFetch(body: unknown = { runtime_control: { state: "START_REQUESTED" } }) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const impl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      json: async () => body,
    } as unknown as Response;
  }) as unknown as typeof fetch;
  return { impl, calls };
}

function errorFetch(status: number, body: unknown) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const impl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return {
      ok: false,
      status,
      json: async () => body,
    } as unknown as Response;
  }) as unknown as typeof fetch;
  return { impl, calls };
}

// 38 — no password
test("an absent password is rejected without calling the admin API", async () => {
  reset();
  configure();
  const { impl, calls } = okFetch();

  const result = await performOperatorAction("arm", undefined, impl);

  assert.equal(result.status, 401);
  assert.equal(result.body.code, "INVALID_OPERATOR_PASSWORD");
  assert.equal(calls.length, 0);
  reset();
});

// 39 — wrong password
test("a wrong password is rejected without calling the admin API", async () => {
  reset();
  configure();
  const { impl, calls } = okFetch();

  const result = await performOperatorAction("arm", "not-the-password", impl);

  assert.equal(result.status, 401);
  assert.equal(calls.length, 0);
  reset();
});

// 40 — correct password proxies to FastAPI with the server-side secret
test("a correct password proxies the arm request with the admin secret", async () => {
  reset();
  configure();
  const { impl, calls } = okFetch();

  const result = await performOperatorAction("arm", PASSWORD, impl);

  assert.equal(result.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${BASE_URL}/api/admin/agent-control/arm-request`);
  assert.equal(calls[0].init.method, "POST");
  const headers = calls[0].init.headers as Record<string, string>;
  assert.equal(headers["X-Regret-Admin-Secret"], ADMIN_SECRET);
  // The operator password is never forwarded upstream.
  assert.equal(calls[0].init.body, undefined);
  reset();
});

// 43 — disarm is authenticated too
test("disarm requires authentication and targets the disarm route", async () => {
  reset();
  configure();
  const denied = okFetch();
  const allowed = okFetch();

  const rejected = await performOperatorAction("disarm", "wrong", denied.impl);
  const accepted = await performOperatorAction("disarm", PASSWORD, allowed.impl);

  assert.equal(rejected.status, 401);
  assert.equal(denied.calls.length, 0);
  assert.equal(accepted.status, 200);
  assert.equal(
    allowed.calls[0].url,
    `${BASE_URL}/api/admin/agent-control/disarm`,
  );
  reset();
});

// 12 — fail closed when nothing is configured
test("operator control fails closed when the password is unconfigured", async () => {
  reset();
  const { impl, calls } = okFetch();

  const result = await performOperatorAction("arm", PASSWORD, impl);

  assert.equal(result.status, 503);
  assert.equal(result.body.code, "OPERATOR_CONTROL_DISABLED");
  assert.equal(calls.length, 0);
  reset();
});

test("operator control fails closed when the admin secret is unconfigured", async () => {
  reset();
  configure({ adminSecret: "" });
  const { impl, calls } = okFetch();

  const result = await performOperatorAction("arm", PASSWORD, impl);

  assert.equal(result.status, 503);
  assert.equal(calls.length, 0);
  reset();
});

// upstream conflicts are surfaced as codes only
test("an upstream conflict is surfaced as a code without leaking detail", async () => {
  reset();
  configure();
  const { impl } = errorFetch(409, {
    detail: { code: "ALREADY_ACTIVE", message: "An arm session is active." },
  });

  const result = await performOperatorAction("arm", PASSWORD, impl);

  assert.equal(result.status, 409);
  assert.equal(result.body.code, "ALREADY_ACTIVE");
  assert.equal(Object.keys(result.body).length, 1);
  reset();
});

test("an unreachable admin API is reported without throwing", async () => {
  reset();
  configure();
  const impl = (async () => {
    throw new Error("connection refused");
  }) as unknown as typeof fetch;

  const result = await performOperatorAction("arm", PASSWORD, impl);

  assert.equal(result.status, 502);
  assert.equal(result.body.code, "ADMIN_API_UNREACHABLE");
  reset();
});

test("no response body ever contains a configured secret", async () => {
  reset();
  configure();
  const { impl } = okFetch({ runtime_control: { state: "ARMED" } });

  const results = [
    await performOperatorAction("arm", PASSWORD, impl),
    await performOperatorAction("arm", "wrong", impl),
    await performOperatorAction("disarm", PASSWORD, impl),
  ];

  for (const result of results) {
    const blob = JSON.stringify(result.body);
    assert.ok(!blob.includes(ADMIN_SECRET));
    assert.ok(!blob.includes(PASSWORD));
  }
  reset();
});
