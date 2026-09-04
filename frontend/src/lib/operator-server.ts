/**
 * SERVER-ONLY operator proxy.
 *
 * The browser never learns ADMIN_PANEL_PASSWORD, REGRET_API_ADMIN_SECRET or
 * REGRET_GITHUB_DISPATCH_TOKEN. It posts the operator's password to this
 * Next.js server route, which validates it here and then calls the FastAPI
 * admin surface with the server-side admin secret.
 *
 * Never import this module from a client component.
 */

import { timingSafeEqual } from "node:crypto";

export type OperatorActionName = "arm" | "disarm";

const ADMIN_PATHS: Record<OperatorActionName, string> = {
  arm: "/api/admin/agent-control/arm-request",
  disarm: "/api/admin/agent-control/disarm",
};

export type OperatorResult = {
  status: number;
  body: Record<string, unknown>;
};

function constantTimeEquals(a: string, b: string): boolean {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  if (left.length !== right.length) {
    // Still burn a comparison so a length mismatch is not trivially timed.
    timingSafeEqual(left, left);
    return false;
  }
  return timingSafeEqual(left, right);
}

function resolveApiBaseUrl(): string | null {
  const candidate =
    process.env.REGRET_API_BASE_URL?.trim() ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!candidate) return null;
  return candidate.replace(/\/$/, "");
}

/**
 * Validate the operator password, then forward the action to FastAPI.
 *
 * Returns only a status and a safe body. No secret, and no upstream detail
 * that could contain one, is ever propagated to the browser.
 */
export async function performOperatorAction(
  action: OperatorActionName,
  password: unknown,
  fetchImpl: typeof fetch = fetch,
): Promise<OperatorResult> {
  const expected = process.env.ADMIN_PANEL_PASSWORD ?? "";
  if (!expected.trim()) {
    return {
      status: 503,
      body: { code: "OPERATOR_CONTROL_DISABLED" },
    };
  }

  if (typeof password !== "string" || !constantTimeEquals(password, expected)) {
    return { status: 401, body: { code: "INVALID_OPERATOR_PASSWORD" } };
  }

  const adminSecret = process.env.REGRET_API_ADMIN_SECRET ?? "";
  const baseUrl = resolveApiBaseUrl();
  if (!adminSecret.trim() || !baseUrl) {
    return { status: 503, body: { code: "OPERATOR_CONTROL_DISABLED" } };
  }

  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}${ADMIN_PATHS[action]}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Regret-Admin-Secret": adminSecret,
      },
      cache: "no-store",
    });
  } catch {
    return { status: 502, body: { code: "ADMIN_API_UNREACHABLE" } };
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail;
    const code =
      typeof detail === "object" && detail !== null && "code" in detail
        ? String((detail as { code: unknown }).code)
        : "ADMIN_ACTION_REJECTED";
    return { status: response.status, body: { code } };
  }

  const runtimeControl =
    (payload as { runtime_control?: unknown } | null)?.runtime_control ?? null;
  return { status: 200, body: { runtime_control: runtimeControl } };
}
