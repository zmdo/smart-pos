/* Pure selection/layout rules used by both preview and server export. */
export const VERSION = "instant-canvas-v1";
export const family = (v) => (v.startsWith("side") ? "side" : v);
export const views = ["front", "side", "back"];
const labels = { front: "正面", side: "侧面", back: "背面" };
const compare = (a, b) => {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] > b[i] ? 1 : -1;
  }
  return 0;
};
export function priority(p) {
  return [
    p.preferred || p.confirmed
      ? 3
      : { human: 3, rule: 2, inferred: 1, pending: 0 }[p.label_kind] || 0,
    p.preferred ? 1 : p.confirmed ? 0.99 : p.confidence || 0,
    p.asset_id,
  ];
}
export function plans(member) {
  const products = [],
    gaps = [],
    pairs = {};
  for (const p of member.photos)
    products.push({
      kind: "single",
      view: family(p.view),
      asset_ids: [p.asset_id],
      name: `${p.phase === "before" ? "训练前" : "训练后"}-${labels[family(p.view)]}-${p.asset_id}.jpg`,
    });
  for (const view of views) {
    const choose = (phase) =>
      member.photos
        .filter((p) => family(p.view) === view && p.phase === phase)
        .sort((a, b) => compare(priority(b), priority(a)));
    const candidates = choose("before").flatMap((a) =>
      choose("after")
        .filter((b) => a.source_sha256 !== b.source_sha256)
        .map((b) => [a, b]),
    );
    const pair = candidates[0];
    if (pair) {
      pairs[view] = pair.map((p) => p.asset_id);
      products.push({
        kind: "vs",
        view,
        asset_ids: pairs[view],
        name: labels[view] + "对比图.jpg",
      });
    } else
      gaps.push({
        product: "vs-" + view,
        reason: "缺少不同原图构成的训练前后配对",
      });
  }
  if (views.every((v) => pairs[v]))
    products.push({
      kind: "three_views",
      view: "all",
      asset_ids: [0, 1].flatMap((i) => views.map((v) => pairs[v][i])),
      name: "完整三视图.png",
    });
  else gaps.push({ product: "three_views", reason: "六个朝向/阶段槽位未齐" });
  if (pairs.front)
    products.push({
      kind: "cover",
      view: "front",
      asset_ids: pairs.front,
      name: "会员案例封面.jpg",
    });
  else gaps.push({ product: "cover", reason: "缺少正面训练前后配对" });
  if (member.table.rows.length)
    products.push({
      kind: "report",
      view: "all",
      asset_ids: [],
      name: "体测报告对比.png",
    });
  else gaps.push({ product: "report", reason: "没有可输出的表格数据" });
  return { products, gaps };
}
export function vsGeometry(sizes, count = 3) {
  const footer = 338 + 90 * (Math.ceil(count / 3) - 1),
    available = 1440 - 219 - footer,
    ratio = sizes.reduce((s, [w, h]) => s + w / h, 0);
  const height = Math.min(Math.round(1080 / ratio), available),
    total = Math.min(1080, Math.round(height * ratio));
  const left = Math.round((total * (sizes[0][0] / sizes[0][1])) / ratio),
    offset = Math.floor((1080 - total) / 2),
    top = 219 + Math.floor((available - height) / 2);
  return {
    footer,
    footer_top: 1440 - footer,
    photo_height: height,
    boxes: [
      [offset, top, left, height],
      [offset + left, top, total - left, height],
    ],
  };
}
export function coverCrops(member, materials, ids) {
  const pair = materials.pairs[[...ids].sort().join("|")];
  if (!pair || pair.error)
    throw Error(pair?.error || "缺少可靠的肩胯标定，无法生成封面");
  return ids.map((id) => member.cover.crops[id] || pair.crops[id]);
}
export function validCrop(rect, source) {
  if (!rect || rect.length !== 4 || rect.some((n) => !Number.isFinite(n)))
    return false;
  const [w, h] = source.size,
    [x, y, cw, ch] = rect.map((v, i) => v * (i % 2 ? h : w));
  if (
    cw <= 0 ||
    ch <= 0 ||
    x < -0.1 ||
    y < -0.1 ||
    x + cw > w + 0.1 ||
    y + ch > h + 0.1 ||
    Math.abs(cw / ch - 500 / 478) > 0.003
  )
    return false;
  // Convex source support; no transparent wedges inside the rectangular frame.
  const poly = source.polygon;
  return [
    [x, y],
    [x + cw, y],
    [x + cw, y + ch],
    [x, y + ch],
  ].every(([px, py]) => {
    const cross = poly.map(([ax, ay], i) => {
      const [bx, by] = poly[(i + 1) % poly.length];
      return (
        ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) /
        Math.hypot(bx - ax, by - ay)
      );
    });
    return cross.every((v) => v >= -1.2) || cross.every((v) => v <= 1.2);
  });
}
export function resetSection(member, baseline, section) {
  if (!["vs", "cover", "table", "three_views"].includes(section))
    throw Error("不支持的重置区域");
  if (section !== "three_views")
    member[section] = structuredClone(baseline[section]);
  member.fonts ||= {};
  for (const k of Object.keys(member.fonts))
    if (k.startsWith(section + ".")) delete member.fonts[k];
  for (const [k, v] of Object.entries(baseline.fonts || {}))
    if (k.startsWith(section + ".")) member.fonts[k] = v;
  for (const k of Object.keys(member.mask_edits || {}))
    if (k.startsWith(section + ":")) delete member.mask_edits[k];
}
export function honorific(p) {
  const surnames = [
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "夏侯",
    "东方",
    "皇甫",
    "尉迟",
    "公孙",
    "慕容",
    "司徒",
    "司空",
  ];
  return (
    (/^[\u3400-\u9fff]+$/.test(p.name)
      ? surnames.find((s) => p.name.startsWith(s)) || p.name[0]
      : p.name) + ({ 男: "先生", 女: "女士" }[p.gender] || "会员")
  );
}
export function syncProfile(m, old) {
  const a = honorific(old),
    b = honorific(m.profile);
  m.vs.nickname = b;
  for (const k of ["title", "subtitle", "headline", "story"])
    m.cover[k] = m.cover[k].replaceAll(a, b);
  if (old.coach && old.coach !== m.profile.coach)
    m.cover.story = m.cover.story.replaceAll(
      old.coach + " 教练",
      m.profile.coach ? m.profile.coach + " 教练" : "教练",
    );
}
