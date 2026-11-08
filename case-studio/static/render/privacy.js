/* Pose-aware sticker geometry. Every panel attaches its own chin to its own neck. */
const clamp = (x, a, b) => Math.min(Math.max(x, a), b);
const need = (f) => ["uncovered", "hidden"].includes(f.state);
export function headAnchor(face, points) {
  const [l, t, r, b] = face.box;
  let x = (l + r) / 2,
    method = "face_box";
  const valid = (i, c) =>
    points?.[i]?.length === 3 &&
    points[i].every(Number.isFinite) &&
    points[i][2] >= c &&
    points[i][0] >= l - 0.3 * (r - l) &&
    points[i][0] <= r + 0.3 * (r - l) &&
    points[i][1] >= t - 0.2 * (b - t) &&
    points[i][1] <= b;
  if (face.front || face.state === "hidden") {
    for (const [pair, c, label] of [
      [[3, 4], 0.6, "bilateral_ears"],
      [[1, 2], 0.7, "bilateral_eyes"],
    ]) {
      if (face.state === "hidden" && pair[0] === 1) continue;
      if (pair.every((i) => valid(i, c))) {
        x = pair.reduce((s, i) => s + points[i][0], 0) / 2;
        method = label;
        break;
      }
    }
  } else {
    const ears = [3, 4]
      .filter((i) => valid(i, 0.75))
      .sort((a, b) => points[b][2] - points[a][2]);
    if (ears.length && valid(0, 0.6)) {
      x = points[ears[0]][0];
      method = "visible_ear";
    }
  }
  return { anchor: [x, b + 0.04 * (b - t)], method };
}
const edge = (f) => f.box[1] <= Math.max(2, 0.1 * (f.box[3] - f.box[1]));
export function panelSource(source, aid, size, crop = null, back = false) {
  const [sw, sh] = source.size,
    [w, h] = size;
  const [x, y, cw, ch] = crop
    ? crop.map((n, i) => n * (i % 2 ? sh : sw))
    : [0, 0, sw, sh];
  const transform = ([px, py, c]) => [
    ((px - x) * w) / cw,
    ((py - y) * h) / ch,
    ...(c === undefined ? [] : [c]),
  ];
  const faces = source.faces
    .map((f) => {
      const a = transform(f.box.slice(0, 2)),
        b = transform(f.box.slice(2));
      return { ...f, box: [...a, ...b] };
    })
    .filter(
      (f) => f.box[2] > 0 && f.box[3] > 0 && f.box[0] < w && f.box[1] < h,
    );
  return {
    asset_id: aid,
    size,
    source,
    crop,
    back,
    faces,
    head_points: source.head_points?.map(transform),
    signature:
      "canvas-v1:" + JSON.stringify([source.source_hash, size, crop, back]),
  };
}
export function privacyLayout(
  member,
  materials,
  panels,
  scope,
  { neutral = false } = {},
) {
  const output = panels.map((p) => ({ ...p, faces: [] }));
  if (member.privacy?.enabled === false)
    return { enabled: false, scope, panels: output };
  const selected = panels.map((p) => {
    if (!p.source.checked && (!p.back || member.privacy?.mask_back))
      throw Error("面部遮挡尚未完成检查，请在会员信息顶部准备或重新检查");
    // Unchecked rear photos are permitted only when rear masking is off.
    return p.faces;
  });
  const main = selected.map((fs) =>
    fs.reduce(
      (best, f, i) =>
        best === null ||
        (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]) >
          (fs[best].box[2] - fs[best].box[0]) *
            (fs[best].box[3] - fs[best].box[1])
          ? i
          : best,
      null,
    ),
  );
  if (!selected.some((fs) => fs.some(need))) return { scope, panels: output };
  if (!materials.sticker) throw Error("请先准备或选择本会员的面部贴纸");
  const [aw, ah] = materials.sticker.size;
  const art = (f) => {
    const [l, t, r, b] = f.box,
      s = Math.max((r - l) / aw, (b - t) / ah) * materials.sticker_scale;
    return [Math.max(1, Math.ceil(aw * s)), Math.max(1, Math.ceil(ah * s))];
  };
  const subjects = panels
    .map((p, i) => [p, selected[i][main[i]]])
    .filter(([p, f]) => f && need(f) && (!p.back || member.privacy?.mask_back));
  let shared = subjects
    .map(([, f]) => art(f))
    .sort((a, b) => b[0] - a[0] || b[1] - a[1])[0];
  if (shared) {
    let scale = 1,
      fallback = 1;
    for (const [p, f] of subjects) {
      const {
          anchor: [x, b],
        } = headAnchor(f, p.head_points),
        [w, h] = p.size;
      if (!(b > 0 && b <= h))
        throw Error("取景框过紧，无法完整放下统一头像，请扩大取景范围");
      const width = Math.min((2 * x) / shared[0], (2 * (w - x)) / shared[0]);
      scale = Math.min(scale, width, b / shared[1]);
      fallback = Math.min(fallback, width, (edge(f) ? h : b) / shared[1]);
    }
    if (scale < 0.85) scale = fallback;
    if (scale < 0.85)
      throw Error("取景框过紧，无法完整放下统一头像，请扩大取景范围");
    shared = shared.map((n) => Math.max(1, Math.floor(n * scale)));
  }
  panels.forEach((p, i) => {
    const record = output[i];
    selected[i].forEach((f, j) => {
      if (!need(f)) return;
      const size = j === main[i] && shared ? shared : art(f),
        [sw, sh] = size,
        [w, h] = p.size;
      const disabled =
        !member.privacy?.mask_back && (p.back || f.state === "hidden");
      if ((sw > w || sh > h) && !disabled)
        throw Error("取景框过紧，无法完整放下统一头像，请扩大取景范围");
      const { anchor, method } = headAnchor(
        f,
        j === main[i] ? p.head_points : null,
      );
      let x = clamp(Math.round(anchor[0] - sw / 2), 0, w - sw),
        y = Math.round(anchor[1] - sh);
      if (!edge(f)) y = Math.max(0, y);
      y = Math.min(y, h - sh);
      const rect = [x, y, x + sw, y + sh],
        edit = member.mask_edits?.[scope]?.[p.asset_id];
      const compat = (materials.legacy_masks || []).some(
        (c) =>
          c.scope === scope &&
          c.asset_id === p.asset_id &&
          c.signature === edit?.signature &&
          c.back === p.back &&
          c.size.every((v, k) => Math.abs(v - p.size[k]) < 0.01) &&
          JSON.stringify(c.crop) === JSON.stringify(p.crop),
      );
      const e =
        !neutral && (edit?.signature === p.signature || compat)
          ? edit.faces?.[f.source_face]
          : null;
      if (e?.position) {
        x = clamp(Math.round(e.position[0] * w), 0, w - sw);
        y = clamp(Math.round(e.position[1] * h), Math.min(0, rect[1]), h - sh);
      }
      record.faces.push({
        source_face: f.source_face,
        shared: j === main[i],
        sticker_size: size,
        sticker_rect: [x, y, x + sw, y + sh],
        default_rect: rect,
        face_box: f.box,
        head_state: f.state,
        head_anchor: anchor,
        anchor_method: method,
        manual_position: e?.position || null,
        deleted: !!e?.deleted,
        back_disabled: disabled,
      });
    });
  });
  return {
    renderer: "instant-canvas-v1",
    scope,
    shared_sticker_size: shared || null,
    alignment: "individual_head_and_jaw",
    panels: output,
  };
}
