import { NextResponse } from "next/server";

import { performOperatorAction } from "@/lib/operator-server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const password = (body as { password?: unknown } | null)?.password;
  const result = await performOperatorAction("arm", password);
  return NextResponse.json(result.body, { status: result.status });
}
