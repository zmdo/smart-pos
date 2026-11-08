import test from "node:test";
import assert from "node:assert/strict";
import {
  plans,
  coverCrops,
  validCrop,
  resetSection,
  vsGeometry,
  syncProfile,
} from "../static/render/model.js";
import {
  headAnchor,
  panelSource,
  privacyLayout,
} from "../static/render/privacy.js";
import { drainChanges } from "../static/save-pump.js";
const photo = (asset_id, view, phase, extra = {}) => ({
  asset_id,
  view,
  phase,
  source_sha256: asset_id,
  label_kind: "pending",
  confidence: 0.8,
  confirmed: false,
  preferred: false,
  ...extra,
});
const member = () => ({
  photos: ["front", "side", "back"].flatMap((v) =>
    ["before", "after"].map((p) => photo(v + p, v, p)),
  ),
  table: { rows: [{}] },
  cover: { crops: {} },
  vs: { metrics: [] },
  privacy: { enabled: false },
  fonts: {},
  mask_edits: {},
});
test("same selection yields six order and changes immediately after phase edits", () => {
  let m = member(),
    r = plans(m);
  assert.deepEqual(r.products.find((p) => p.kind === "three_views").asset_ids, [
    "frontbefore",
    "sidebefore",
    "backbefore",
    "frontafter",
    "sideafter",
    "backafter",
  ]);
  m.photos[0].phase = "after";
  assert.equal(
    plans(m).products.some((p) => p.kind === "three_views"),
    false,
  );
});
test("priority selects preferred/confirmed first; identical source cannot form before-after pair", () => {
  const m = member();
  m.photos.push(photo("better", "front", "before", { preferred: true }));
  assert.equal(
    plans(m).products.find((p) => p.kind === "vs").asset_ids[0],
    "better",
  );
  m.photos = m.photos.filter((p) => p.view === "front");
  m.photos.forEach((p) => (p.source_sha256 = "same"));
  assert.equal(
    plans(m).products.some((p) => p.kind === "vs"),
    false,
  );
});
test("rectangular cover refuses transparent corners and keeps uniform scale", () => {
  const source = {
    size: [1000, 1000],
    polygon: [
      [50, 0],
      [950, 0],
      [1000, 1000],
      [0, 1000],
    ],
  };
  assert(validCrop([0.1, 0.1, 0.5, 0.478], source));
  assert(!validCrop([0, 0, 0.5, 0.478], source));
  assert(!validCrop([0.1, 0.1, 0.5, 0.4], source));
});
test("same-view photos touch each other; padding stays outside", () => {
  for (const n of [0, 1, 3, 6]) {
    const g = vsGeometry(
      [
        [360, 900],
        [360, 900],
      ],
      n,
    );
    assert.equal(g.boxes[0][0] + g.boxes[0][2], g.boxes[1][0]);
    assert(g.boxes[0][0] >= 0);
    assert.equal(g.footer_top + g.footer, 1440);
  }
});
test("reset affects one section, preserves phases, identity and other text", () => {
  const m = member();
  m.cover.title = "custom";
  m.vs.nickname = "Test";
  m.fonts = { "cover.title": "serif", "vs.address": "serif" };
  m.mask_edits = { "cover:front": { a: {} }, "vs:front": { b: {} } };
  resetSection(
    m,
    { cover: { title: "original", crops: {} }, fonts: {} },
    "cover",
  );
  assert.equal(m.cover.title, "original");
  assert.equal(m.vs.nickname, "Test");
  assert.equal(m.fonts["vs.address"], "serif");
  assert(!m.mask_edits["cover:front"]);
  assert(m.mask_edits["vs:front"]);
  assert.equal(m.photos.length, 6);
});
test("head anchor attaches to reliable ears independently, not image center", () => {
  const f = { box: [20, 10, 80, 80], front: true, state: "uncovered" },
    points = [
      [50, 30, 1],
      [40, 20, 1],
      [60, 20, 1],
      [30, 35, 1],
      [60, 35, 1],
    ];
  assert.equal(headAnchor(f, points).anchor[0], 45);
  assert.equal(headAnchor(f, points).method, "bilateral_ears");
});
test("manual mask edits bind to image/crop geometry; rear off is respected", () => {
  const src = {
      size: [200, 400],
      source_hash: "x",
      checked: true,
      faces: [
        {
          box: [65, 20, 135, 100],
          source_face: 0,
          state: "uncovered",
          front: true,
        },
      ],
    },
    p = panelSource(src, "a", [200, 400]);
  const m = { privacy: { enabled: true, mask_back: false }, mask_edits: {} },
    a = { sticker: { size: [100, 100] }, sticker_scale: 1 };
  let l = privacyLayout(m, a, [p], "vs:front");
  m.mask_edits = {
    "vs:front": {
      a: {
        signature: p.signature,
        faces: { 0: { position: [0.1, 0.1], deleted: false } },
      },
    },
  };
  l = privacyLayout(m, a, [p], "vs:front");
  assert.deepEqual(l.panels[0].faces[0].sticker_rect.slice(0, 2), [20, 40]);
  p.signature += "new";
  l = privacyLayout(m, a, [p], "vs:front");
  assert.equal(l.panels[0].faces[0].manual_position, null);
});
test("event saves immediately and coalesces all typing while request is pending", async () => {
  const s = { dirty: true, saving: null },
    seen = [];
  let current = "a",
    release;
  const save = async () => {
    const value = current;
    seen.push(value);
    if (seen.length === 1) await new Promise((r) => (release = r));
    s.dirty = value !== current;
  };
  const first = drainChanges(s, save);
  await Promise.resolve();
  assert.deepEqual(seen, ["a"]);
  current = "abcdef";
  s.dirty = true;
  const second = drainChanges(s, save);
  assert.equal(first, second);
  release();
  await first;
  assert.deepEqual(seen, ["a", "abcdef"]);
  assert.equal(s.saving, null);
});
test("failed saving preserves dirty state and supports explicit retry", async () => {
  const s = { dirty: true, saving: null };
  await assert.rejects(
    drainChanges(s, async () => {
      throw Error("offline");
    }),
    /offline/,
  );
  assert.equal(s.dirty, true);
  assert.equal(s.saving, null);
  await drainChanges(s, async () => {
    s.dirty = false;
  });
  assert.equal(s.dirty, false);
});

test("legacy edits migrate only when source, crop and size still agree", () => {
  const source = {
    size: [200, 400],
    source_hash: "old-photo",
    checked: true,
    faces: [
      {
        box: [65, 20, 135, 100],
        source_face: 0,
        state: "uncovered",
        front: true,
      },
    ],
  };
  const p = panelSource(source, "a", [200, 400]);
  const m = {
    privacy: { enabled: true },
    mask_edits: {
      "vs:front": {
        a: {
          signature: "old-python-hash",
          faces: { 0: { position: null, deleted: true } },
        },
      },
    },
  };
  const a = {
    sticker: { size: [100, 100] },
    sticker_scale: 1,
    legacy_masks: [
      {
        scope: "vs:front",
        asset_id: "a",
        signature: "old-python-hash",
        size: [200, 400],
        crop: null,
        back: false,
      },
    ],
  };
  assert.equal(
    privacyLayout(m, a, [p], "vs:front").panels[0].faces[0].deleted,
    true,
  );
  a.legacy_masks[0].size = [100, 200];
  assert.equal(
    privacyLayout(m, a, [p], "vs:front").panels[0].faces[0].deleted,
    false,
  );
});
