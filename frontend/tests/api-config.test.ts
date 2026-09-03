import assert from "node:assert/strict";
import test from "node:test";

import { resolveApiBaseUrl } from "../src/lib/api";


test("frontend API URL has an explicit local development fallback", () => {
  assert.equal(resolveApiBaseUrl(), "http://127.0.0.1:8000");
});

test("frontend API URL uses the configured production HTTPS origin", () => {
  assert.equal(
    resolveApiBaseUrl("https://regret-api.example/"),
    "https://regret-api.example",
  );
});

test("frontend API URL rejects credentials and non-HTTP protocols", () => {
  assert.throws(() => resolveApiBaseUrl("ftp://example.com"));
  assert.throws(() => resolveApiBaseUrl("https://user:secret@example.com"));
});
