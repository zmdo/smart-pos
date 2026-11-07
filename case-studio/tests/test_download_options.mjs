import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const source = await readFile(
  new URL("../static/download-options.js", import.meta.url),
  "utf8",
);
const { downloadPlan, archiveURL } = await import(
  "data:text/javascript;base64," + Buffer.from(source).toString("base64")
);
const version = {
  members: [
    {
      member_id: "m1",
      products: [{ kind: "cover" }, { kind: "vs" }, { kind: "vs" }],
    },
    { member_id: "m2", products: [{ kind: "report" }] },
  ],
};
const all = downloadPlan(version);
assert.deepEqual(all.selected, all.available);
assert.equal(all.total, 4);
assert.equal(all.queryTypes, null);
assert.equal(
  archiveURL("j", "v", null, all.queryTypes),
  "/api/jobs/j/download/v",
);

const subset = downloadPlan(version, ["cover", "vs"]);
assert.equal(subset.total, 3);
assert.deepEqual(subset.byMember, { m1: 3, m2: 0 });
const query = new URL(
  archiveURL("j", "v", "m1", subset.queryTypes),
  "https://studio.test",
).searchParams;
assert.deepEqual(query.getAll("types"), ["vs", "cover"]);
assert.equal(query.get("member"), "m1");

const empty = downloadPlan(version, []);
assert.equal(empty.total, 0);
assert.equal(archiveURL("j", "v", null, empty.queryTypes), null);
assert.equal(downloadPlan(version, ["life"]).total, 0);
assert.equal(downloadPlan({ members: [] }).total, 0);
console.log("5 download selection behavior checks passed");
