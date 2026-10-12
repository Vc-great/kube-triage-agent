// Regression: keep dev01/local keys separate and safely migrate the old storage.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";

const source = await readFile(
  new URL("../src/lib/api-key.tsx", import.meta.url),
  "utf8",
);
const { code } = await transform(source, { loader: "tsx", format: "esm" });
const { getApiKey, setApiKey } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);
const data = new Map();
globalThis.window = {
  localStorage: {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
    removeItem: (key) => data.delete(key),
  },
};
const remote = "http://192.168.31.110:12026";
const local = "http://localhost:12026";
data.set("lg:chat:apiKey", "legacy-test-value");
data.set("lg:chat:apiKeyHost", remote);
assert.equal(getApiKey(local), null);
assert.equal(getApiKey(remote), "legacy-test-value");
setApiKey(local, "dev-test-value");
assert.equal(getApiKey(remote), "legacy-test-value");
assert.equal(getApiKey(local + "/threads"), "dev-test-value");
setApiKey(remote, "");
assert.equal(getApiKey(remote), null);
assert.equal(getApiKey(local), "dev-test-value");
assert.equal(getApiKey("http://127.0.0.1:12026"), null);
assert.equal(getApiKey("invalid"), null);
delete globalThis.window;
assert.equal(getApiKey(local), null);
console.log("API Token origin isolation and legacy migration: PASS");
