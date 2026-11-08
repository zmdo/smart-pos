import { Assets } from "./render/assets.js";
import { render, plans, photoPanels } from "./render/canvas.js";
import { imageURL } from "./media-cache.js";
import { previewPrerequisite } from "./review-state.js";
const sections = ["vs", "cover", "table", "three_views"];
const books = new Map();
export function clearInstant() {
  books.clear();
}
export async function createPreview({
  job,
  mid,
  api,
  getMember,
  active,
  onCover,
  onResult,
}) {
  const key = job + "/" + mid,
    member = getMember(),
    identity = JSON.stringify([
      member.material_key,
      member.privacy?.sticker_id,
      member.render_settings,
    ]);
  let book = books.get(key);
  if (!book || book.identity !== identity) {
    const promise = Promise.all([
      api(`/jobs/${job}/members/${mid}/materials`),
      api("/fonts"),
      api(`/jobs/${job}/members/${mid}/defaults`),
    ]).then(([mats, fonts, defaults]) => ({
      mats,
      defaults,
      assets: new Assets(
        mats,
        fonts.map((f) => ({
          ...f,
          url: `/api/fonts/${f.id}/file?v=${f.sha256}`,
        })),
        imageURL,
      ),
    }));
    book = { identity, promise, view: "front" };
    books.set(key, book);
    promise.catch(() => {
      if (books.get(key) === book) books.delete(key);
    });
    while (books.size > 3) books.delete(books.keys().next().value);
  }
  const data = await book.promise;
  if (!active()) return null;
  let frame = null,
    revision = 0,
    dead = false;
  const pending = new Set(),
    sequences = {};
  async function paint(section) {
    const rev = sequences[section],
      m = structuredClone(getMember()),
      target = document.querySelector("#" + section + "-preview");
    if (!target || !active()) return;
    const ready = () =>
      !dead && active() && sequences[section] === rev && target.isConnected;
    const state = document.querySelector(`[data-preview-status="${section}"]`);
    const fail = (text) => {
      if (ready()) {
        target.innerHTML = "";
        const p = document.createElement("p");
        p.className = "empty";
        p.textContent = text;
        target.append(p);
        if (state) state.textContent = "当前区域暂不可用";
      }
    };
    const prerequisite = previewPrerequisite(m, section);
    if (prerequisite) return fail(prerequisite);
    const all = plans(m).products.filter(
      (p) => p.kind === (section === "table" ? "report" : section),
    );
    if (!all.length)
      return fail(
        section === "table"
          ? "没有表格数据时，不生成报告。"
          : "缺少所需的训练前后或朝向照片。",
      );
    const plan =
      section === "vs"
        ? all.find((p) => p.view === book.view) || all[0]
        : all[0];
    try {
      const start = performance.now();
      const result = await render(null, m, data.assets, plan, { width: 540 });
      if (!ready()) return;
      if (section === "vs") {
        if (
          !target.querySelector(".preview-tabs") ||
          target.dataset.views !== all.map((p) => p.view).join(",")
        ) {
          target.innerHTML = '<div class="preview-tabs"></div>';
          const tabs = target.firstElementChild;
          all.forEach((p) => {
            const b = document.createElement("button");
            b.textContent = p.name.replace("对比图.jpg", "");
            b.dataset.view = p.view;
            b.onclick = () => {
              book.view = p.view;
              update(["vs"]);
            };
            tabs.append(b);
          });
          target.dataset.views = all.map((p) => p.view).join(",");
        }
        target
          .querySelectorAll("[data-view]")
          .forEach((b) =>
            b.classList.toggle("active", b.dataset.view === plan.view),
          );
        book.view = plan.view;
      } else if (!target.querySelector("canvas")) target.innerHTML = "";
      let canvas = target.querySelector("canvas");
      if (!canvas) {
        canvas = document.createElement("canvas");
        canvas.setAttribute(
          "aria-label",
          {
            vs: "同朝向对比图实时预览",
            cover: "会员案例封面实时预览",
            table: "体测对比表实时预览",
            three_views: "完整六图实时预览",
          }[section],
        );
        target.append(canvas);
        if (section === "cover") {
          canvas.onclick = onCover;
          canvas.style.cursor = "pointer";
        }
      }
      canvas.width = result.canvas.width;
      canvas.height = result.canvas.height;
      canvas.getContext("2d").drawImage(result.canvas, 0, 0);
      canvas.dataset.renderMs = (performance.now() - start).toFixed(1);
      canvas.dataset.revision = rev;
      canvas.dataset.layoutHash = result.layout_hash;
      canvas.dataset.product = plan.name;
      if (state) state.textContent = "实时预览";
      onResult?.(section, result, plan);
    } catch (e) {
      fail(e.message);
    }
  }
  function update(changed = sections) {
    revision++;
    changed.forEach((s) => {
      pending.add(s);
      sequences[s] = revision;
    });
    if (frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      const dirty = [...pending];
      pending.clear();
      dirty.forEach((s) => void paint(s));
    });
  }
  // Independent sections must not invalidate an in-flight first render of another section.
  const controller = {
    ...data,
    update,
    destroy() {
      dead = true;
      revision++;
      if (frame !== null) cancelAnimationFrame(frame);
    },
    async cover(crops, canvas) {
      const m = structuredClone(getMember());
      Object.assign(m.cover.crops, crops);
      const plan = plans(m).products.find((p) => p.kind === "cover");
      if (!plan) throw Error("没有可用正面配对");
      return render(null, m, data.assets, plan, { width: 540 });
    },
    async mask(section, version) {
      const m = structuredClone(getMember()),
        products = plans(m).products.filter((p) => p.kind === section),
        groups = [];
      for (const p of products) {
        const [clean, current] = await Promise.all([
          photoPanels(m, data.assets, p, { neutral: true }),
          photoPanels(m, data.assets, p),
        ]);
        groups.push({
          scope: current.layout.scope,
          panels: current.layout.panels.map((panel, i) => {
            const photo = m.photos.find((p) => p.asset_id === panel.asset_id);
            return {
              ...structuredClone(panel),
              image: clean.images[i],
              phase: photo.phase,
              view: photo.view,
            };
          }),
        });
      }
      return {
        groups,
        version,
        section,
        fingerprint: "instant-v1",
        sticker: await data.assets.image(data.mats.sticker.image),
      };
    },
  };
  update();
  return controller;
}
