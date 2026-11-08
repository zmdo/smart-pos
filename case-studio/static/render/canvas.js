import { VERSION, plans, vsGeometry, coverCrops, validCrop } from "./model.js";
import { panelSource, privacyLayout } from "./privacy.js";
const RED = "#E70012",
  INK = "#242821";
const make = (w, h) => {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
};
function round(c, box, r, fill, stroke = null, line = 1) {
  c.beginPath();
  c.roundRect(...box, r);
  c.fillStyle = fill;
  c.fill();
  if (stroke) {
    c.strokeStyle = stroke;
    c.lineWidth = line;
    c.stroke();
  }
}
function contain(c, image, box) {
  const [x, y, w, h] = box,
    s = Math.min(w / image.width, h / image.height);
  c.drawImage(
    image,
    x + (w - image.width * s) / 2,
    y + (h - image.height * s) / 2,
    image.width * s,
    image.height * s,
  );
}
function typesetter(c, member, assets, section) {
  const settings = member.render_settings,
    overrides = { ...settings.font_overrides, ...member.fonts };
  const font = (key, size, weight) => {
    const id =
      overrides[section === "table" ? "table.all" : section + "." + key] ||
      settings.default_font;
    c.font = `${weight} ${size}px "${assets.family(id)}"`;
    return c.measureText("国");
  };
  const lines = (value, width) => {
    const out = [];
    let line = "";
    // Wrap at Latin words where possible, preserve CJK punctuation and all characters.
    for (const token of String(value).match(/[A-Za-z0-9.+%_-]+|[^\n]|\n/g) ||
      []) {
      if (token === "\n") {
        out.push(line);
        line = "";
        continue;
      }
      if (line && c.measureText(line + token).width > width) {
        out.push(line);
        line = "";
      }
      if (c.measureText(token).width > width) {
        for (const char of token) {
          if (line && c.measureText(line + char).width > width) {
            out.push(line);
            line = "";
          }
          line += char;
        }
      } else line += token;
    }
    if (line || !out.length) out.push(line);
    return out;
  };
  return (
    value,
    box,
    {
      key = "",
      size = 40,
      min = 8,
      color = section === "vs" ? RED : INK,
      weight = 700,
      align = "center",
      wrap = false,
      lineHeight = 1.35,
      top = false,
    } = {},
  ) => {
    const [x, y, w, h] = box;
    let fs = size,
      list;
    for (; fs >= min; fs--) {
      font(key, fs, weight);
      list = wrap ? lines(value, w) : [String(value)];
      if (
        list.every((t) => c.measureText(t).width <= w) &&
        list.length * fs * lineHeight <= h + 0.1
      )
        break;
    }
    if (fs < min) throw Error("文字超出固定区域，请缩短内容或更换字体");
    (c.textLayout ||= []).push({
      key,
      box,
      size: fs,
      lines: list,
      font: c.font,
    });
    c.fillStyle = color;
    c.textAlign = align;
    c.textBaseline = "alphabetic";
    const height = list.length * fs * lineHeight,
      start = top ? y : y + (h - height) / 2;
    list.forEach((t, i) => {
      const b = c.measureText(t),
        actual = b.actualBoundingBoxAscent + b.actualBoundingBoxDescent;
      c.fillText(
        t,
        align === "left" ? x : align === "right" ? x + w : x + w / 2,
        start +
          i * fs * lineHeight +
          (fs * lineHeight - actual) / 2 +
          b.actualBoundingBoxAscent,
      );
    });
    return {
      size: fs,
      lines: list,
      width: Math.max(...list.map((t) => c.measureText(t).width)),
    };
  };
}
function panelsFor(member, materials, product) {
  const ids = product.asset_ids;
  if (product.kind === "cover") {
    const crops = coverCrops(member, materials, ids);
    return ids.map((id, i) => {
      const source = materials.photos[id]?.cover;
      if (!source) throw Error("缺少封面专用原图");
      if (!validCrop(crops[i], source))
        throw Error("封面取景不能超出完整原图范围，请调整取景框");
      return panelSource(source, id, [500, 478], crops[i]);
    });
  }
  const sizes = ids.map((id) => materials.photos[id].size),
    boxes =
      product.kind === "vs"
        ? vsGeometry(sizes, member.vs.metrics.length).boxes
        : null;
  return ids.map((id, i) =>
    panelSource(
      materials.photos[id],
      id,
      boxes ? boxes[i].slice(2) : sizes[i],
      null,
      member.photos.find((p) => p.asset_id === id).view === "back",
    ),
  );
}
export function maskGeometry(member, materials, product, options = {}) {
  return privacyLayout(
    member,
    materials,
    panelsFor(member, materials, product),
    product.kind + ":" + product.view,
    options,
  );
}
export async function photoPanels(
  member,
  assets,
  product,
  { neutral = false } = {},
) {
  assets.panels ||= new Map();
  const cacheKey = JSON.stringify([
    product,
    neutral,
    member.privacy,
    member.cover.crops,
    member.vs.metrics.length,
    member.mask_edits,
    member.photos.map((p) => [p.asset_id, p.view]),
  ]);
  if (assets.panels.has(cacheKey)) return assets.panels.get(cacheKey);
  const mats = assets.materials,
    panels = await panelsFor(member, mats, product),
    scope = product.kind + ":" + product.view;
  const layout = privacyLayout(member, mats, panels, scope, { neutral });
  const sticker = mats.sticker ? await assets.image(mats.sticker.image) : null;
  const images = await Promise.all(
    panels.map(async (p, i) => {
      const im = await assets.image(p.source.image),
        canvas = make(...p.size),
        c = canvas.getContext("2d");
      c.imageSmoothingQuality = "high";
      if (p.crop) {
        const [w, h] = p.source.size,
          [x, y, cw, ch] = p.crop.map((v, i) => v * (i % 2 ? h : w));
        c.drawImage(im, x, y, cw, ch, 0, 0, ...p.size);
      } else c.drawImage(im, 0, 0, ...p.size);
      if (!neutral)
        for (const f of layout.panels[i].faces)
          if (!f.deleted && !f.back_disabled)
            c.drawImage(
              sticker,
              f.sticker_rect[0],
              f.sticker_rect[1],
              ...f.sticker_size,
            );
      return canvas;
    }),
  );
  const result = { images, layout };
  assets.panels.set(cacheKey, result);
  while (assets.panels.size > 10)
    assets.panels.delete(assets.panels.keys().next().value);
  return result;
}
async function drawVS(c, m, a, p, images) {
  const v = m.vs,
    t = typesetter(c, m, a, "vs"),
    g = vsGeometry(
      images.map((im) => [im.width, im.height]),
      v.metrics.length,
    );
  c.fillStyle = RED;
  c.fillRect(0, 0, 1080, 219);
  c.fillRect(0, g.footer_top, 1080, g.footer);
  images.forEach((im, i) => c.drawImage(im, ...g.boxes[i]));
  if (a.materials.logo)
    contain(c, await a.image(a.materials.logo), [210, 35, 660, 130]);
  else
    t(v.brand_name, [200, 45, 680, 105], {
      size: 60,
      color: "white",
      key: "brand_name",
    });
  t(v.consent_text, [690, 186, 374, 26], {
    size: 18,
    weight: 400,
    color: "white",
    align: "right",
    key: "consent_text",
  });
  round(c, [405, 173, 270, 97], 25, "white", RED, 6);
  t(v.titles[p.view], [423, 188, 234, 68], {
    size: 42,
    key: "titles." + p.view,
  });
  c.save();
  c.translate(540, g.boxes[0][1] + g.photo_height * 0.4);
  c.transform(1, 0, -0.23, 1, 0, 0);
  t(v.vs_text, [-100, -65, 200, 130], {
    size: 96,
    weight: 900,
    key: "vs_text",
    color: RED,
  });
  c.lineWidth = 14;
  c.lineJoin = "round";
  c.strokeStyle = "white";
  c.textAlign = "center";
  c.textBaseline = "middle";
  c.strokeText(v.vs_text, 0, 0);
  c.fillStyle = RED;
  c.fillText(v.vs_text, 0, 0);
  c.restore();
  const bottom = g.boxes[0][1] + g.boxes[0][3],
    y = bottom - 125;
  g.boxes.forEach(([x, , w], i) => {
    const half = Math.min(120, w * 0.38),
      box = [x + w / 2 - half, y, half * 2, 100];
    round(c, box, 50, "white", RED, 6);
    t(i ? v.after_text : v.before_text, [box[0] + 18, y + 6, box[2] - 36, 88], {
      size: 43,
      key: i ? "after_text" : "before_text",
    });
  });
  const cy = y + 50;
  c.beginPath();
  [
    [484, cy - 27],
    [556, cy - 27],
    [556, cy - 54],
    [617, cy],
    [556, cy + 54],
    [556, cy + 27],
    [484, cy + 27],
  ].forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y)));
  c.closePath();
  c.fillStyle = RED;
  c.fill();
  c.strokeStyle = "white";
  c.lineWidth = 6;
  c.stroke();
  const fy = g.footer_top + 36;
  round(c, [62, fy, 962, 100], 50, RED, "white", 4);
  round(c, [62, fy, 238, 100], 50, "white");
  t(v.nickname, [82, fy + 15, 198, 69], { size: 43, key: "nickname" });
  t(v.address, [326, fy + 18, 674, 64], {
    size: 31,
    color: "white",
    key: "address",
  });
  v.metrics.forEach((r, i) => {
    const line = Math.floor(i / 3),
      col = i % 3,
      count = Math.min(3, v.metrics.length - line * 3),
      w = (1080 - 28 - 6 * (count - 1)) / count,
      x = 14 + col * (w + 6),
      y = g.footer_top + 171 + 90 * line;
    round(c, [x, y, w, 72], 36, "white");
    t(r.text, [x + 20, y + 8, w - 40, 56], { size: 41, key: "metrics." + i });
  });
}
async function drawCover(c, m, a, images) {
  const v = m.cover,
    t = typesetter(c, m, a, "cover");
  round(
    c,
    [692, 26, 358, 104],
    52,
    m.render_settings.output_background,
    RED,
    8,
  );
  t(v.badge, [720, 40, 302, 74], { key: "badge", size: 62, color: RED });
  const title = t(v.title, [30, 81, 634, 130], {
    key: "title",
    size: 119,
    min: 30,
    color: RED,
    align: "left",
  });
  c.fillStyle = RED;
  c.fillRect(30, 214, Math.min(634, title.width), 6);
  t(v.subtitle, [32, 244, 1016, 74], {
    key: "subtitle",
    size: 67,
    color: "#805126",
    align: "left",
  });
  t(v.headline, [32, 339, 1016, 75], {
    key: "headline",
    size: 71,
    align: "left",
  });
  round(c, [32, 452, 1016, 622], 54, RED);
  c.save();
  c.beginPath();
  c.roundRect(40, 460, 1000, 478, [44, 44, 0, 0]);
  c.clip();
  images.forEach((im, i) => c.drawImage(im, 40 + i * 500, 460, 500, 478));
  c.restore();
  if (a.materials.logo)
    contain(c, await a.image(a.materials.logo), [70, 966, 325, 86]);
  else
    t(v.brand_name, [70, 968, 430, 83], {
      key: "brand_name",
      size: 37,
      color: "white",
      align: "left",
    });
  c.fillStyle = "white";
  c.beginPath();
  c.arc(597, 1000, 31, Math.PI, 0);
  c.bezierCurveTo(628, 1020, 609, 1034, 597, 1045);
  c.bezierCurveTo(582, 1033, 566, 1018, 566, 1000);
  c.fill();
  c.fillStyle = RED;
  c.beginPath();
  c.arc(597, 1000, 9, 0, Math.PI * 2);
  c.fill();
  t(v.address, [645, 964, 370, 40], {
    key: "address",
    size: 31,
    color: "white",
    align: "left",
  });
  t(v.store_text, [645, 1007, 370, 40], {
    key: "store_text",
    size: 31,
    color: "white",
    align: "left",
  });
  t("“", [28, 1093, 52, 65], { key: "story", size: 72, color: "#5c5353" });
  t("”", [1007, 1366, 43, 66], { key: "story", size: 72, color: "#5c5353" });
  t(v.story, [87, 1102, 914, 285], {
    key: "story",
    size: 28,
    min: 16,
    color: "#5c5353",
    weight: 400,
    align: "left",
    wrap: true,
    lineHeight: 1.68,
    top: true,
  });
}
async function drawReport(c, m, a) {
  const v = m.table,
    t = typesetter(c, m, a, "table"),
    margin = 27,
    inner = 1026,
    rows = v.rows;
  let tableY = 77;
  if (a.materials.reports.before && a.materials.reports.after) {
    c.fillStyle = RED;
    c.fillRect(0, 0, 1080, 10);
    t(v.report_title, [27, 16, 1026, 46], { size: 31, weight: 500 });
    const maxH =
      1440 -
      27 -
      1 -
      Math.max(430, Math.round(1080 * (0.043 + 0.025 * rows.length))) -
      50 -
      19 -
      120;
    const images = await Promise.all(
      ["before", "after"].map((k) => a.image(a.materials.reports[k].image)),
    );
    const sizes = images.map((im) => {
      const s = Math.min(513 / im.width, maxH / im.height);
      return [Math.round(im.width * s), Math.round(im.height * s)];
    });
    const h = Math.max(...sizes.map((s) => s[1]));
    images.forEach((im, i) => {
      const side = i ? "after" : "before";
      t(
        v[side + "_label"] + "  " + (a.materials.dates[side + "_date"] || ""),
        [27 + i * 513, 80, 513, 30],
        { size: 18, weight: 500, color: i ? RED : INK },
      );
      const [w, ih] = sizes[i];
      c.drawImage(im, 27 + i * 513 + (513 - w) / 2, 120 + (h - ih) / 2, w, ih);
    });
    tableY = 120 + h + 19 + 50;
  }
  t(v.table_title, [margin, tableY - 50, inner, 42], {
    size: 27,
    color: RED,
    weight: 500,
  });
  const tableH = 1440 - tableY - margin - 1,
    header = 46,
    rowH = (tableH - header) / rows.length;
  const xs = [27];
  for (const f of [0.17, 0.24, 0.24, 0.22, 0.13])
    xs.push(xs.at(-1) + Math.round(inner * f));
  xs[5] = 1053;
  c.fillStyle = "white";
  c.fillRect(margin, tableY, inner, tableH);
  c.fillStyle = RED;
  c.fillRect(margin, tableY, inner, header);
  v.headers.forEach((s, i) =>
    t(s, [xs[i] + 5, tableY, xs[i + 1] - xs[i] - 10, header], {
      size: 18,
      color: "white",
      weight: 500,
      wrap: true,
    }),
  );
  rows.forEach((r, i) => {
    const y = tableY + header + i * rowH;
    if (i % 2) {
      c.fillStyle = "#faf8f5";
      c.fillRect(margin, y, inner, rowH);
    }
    ["type", "before", "after", "delta", "unit"].forEach((k, j) =>
      t(
        String(r[k] ?? "").trim() || "—",
        [xs[j] + 7, y + 4, xs[j + 1] - xs[j] - 14, rowH - 8],
        {
          size: Math.min(20.5, rowH * 0.52),
          weight: 500,
          color: k === "delta" ? RED : INK,
          wrap: true,
        },
      ),
    );
    c.strokeStyle = "#e4e0d9";
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(margin, y + rowH);
    c.lineTo(1053, y + rowH);
    c.stroke();
  });
}
export async function render(
  canvas,
  member,
  assets,
  product,
  { width = 1080 } = {},
) {
  await assets.prepare(member);
  let images = [],
    layout = null;
  if (product.kind !== "report")
    ({ images, layout } = await photoPanels(member, assets, product));
  // Draw to a detached canvas: a stale asynchronous render can never partly overwrite the current one.
  const work = make(width, (width * 4) / 3),
    c = work.getContext("2d");
  c.scale(width / 1080, width / 1080);
  c.imageSmoothingQuality = "high";
  c.fillStyle = member.render_settings.output_background;
  c.fillRect(0, 0, 1080, 1440);
  if (product.kind === "vs") await drawVS(c, member, assets, product, images);
  else if (product.kind === "cover") await drawCover(c, member, assets, images);
  else if (product.kind === "report") await drawReport(c, member, assets);
  else if (product.kind === "single") contain(c, images[0], [0, 0, 1080, 1440]);
  else if (product.kind === "three_views") {
    if (new Set(images.map((im) => im.width + "x" + im.height)).size !== 1)
      throw Error("完整六图需要六张相同尺寸的标准化照片");
    const w = images[0].width,
      h = images[0].height,
      s = Math.min(1080 / (3 * w), 1440 / (2 * h)),
      x = (1080 - 3 * w * s) / 2,
      y = (1440 - 2 * h * s) / 2;
    images.forEach((im, i) =>
      c.drawImage(
        im,
        x + (i % 3) * w * s,
        y + Math.floor(i / 3) * h * s,
        w * s,
        h * s,
      ),
    );
  } else throw Error("不支持的成品类型");
  if (canvas) {
    canvas.width = work.width;
    canvas.height = work.height;
    canvas.getContext("2d").drawImage(work, 0, 0);
  }
  const text_layout = c.textLayout || [];
  const encoded = new TextEncoder().encode(
    JSON.stringify({ text_layout, privacy_layout: layout }),
  );
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  const layout_hash = [...new Uint8Array(digest)]
    .map((n) => n.toString(16).padStart(2, "0"))
    .join("");
  return {
    canvas: work,
    privacy_layout: layout,
    text_layout,
    layout_hash,
    renderer: VERSION,
    cover_sources:
      product.kind === "cover"
        ? product.asset_ids.map((id, i) => ({
            asset_id: id,
            crop: coverCrops(member, assets.materials, product.asset_ids)[i],
          }))
        : [],
  };
}
export { plans, VERSION };
