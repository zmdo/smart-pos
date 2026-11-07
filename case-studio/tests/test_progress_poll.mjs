import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(
  new URL("../static/app.js", import.meta.url),
  "utf8",
);
const start = source.indexOf("async function refreshJob() {");
const end = source.indexOf("\nfunction stepper(", start);
assert.ok(start >= 0 && end > start);
const code = source.slice(start, end);

for (const destination of [null, { id: "other-job", status: "review" }]) {
  let resolve;
  const warnings = [];
  const context = {
    state: { job: { id: "original-job", status: "processing" } },
    api: () =>
      new Promise((done) => {
        resolve = done;
      }),
    console: { warn: (message) => warnings.push(message) },
  };
  vm.runInNewContext(code, context);
  const pending = context.refreshJob();
  context.state.job = destination;
  resolve({ id: "original-job", status: "review", review_version: 1 });
  await pending;
  assert.equal(context.state.job, destination);
  assert.deepEqual(warnings, []);
}

const nodes = new Map();
const context = {
  state: {
    job: { id: "current", status: "processing", review_version: 0 },
    review: null,
  },
  api: async () => ({
    id: "current",
    status: "processing",
    review_version: 0,
    progress: 40,
  }),
  $: (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {});
    return nodes.get(selector);
  },
  nodes: () => "nodes",
  memberProgress: () => "member lists",
  console: { warn: (message) => assert.fail(message) },
};
vm.runInNewContext(code, context);
await context.refreshJob();
assert.equal(nodes.get("#progress-number").textContent, "40%");
assert.equal(nodes.get("#member-progress").innerHTML, "member lists");
console.log("3 progress polling behavior checks passed");
