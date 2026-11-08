import { openMaskEditor } from "./mask-editor.js";
import { mergeSaved, previewPrerequisite } from "./review-state.js";
import { openCrop } from "./crop.js";
import { openCoverAI } from "./cover-ai.js";
import { imageURL, clearMediaCache } from "./media-cache.js";
import { privacyPanel, bindPrivacy, libraryPage, imageSettings } from "./privacy.js";
import { loadFonts, fontLibrary, fontOptions, fontSelect, removeIndexedFonts } from "./fonts.js";
import {
  productTypes as products,
  downloadPlan,
  archiveURL,
} from "./download-options.js";
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
export const escape = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const E = escape;
const state = {
  page: "home",
  job: null,
  review: null,
  member: null,
  preview: null,
  versions: [],
  selectedVersion: null,
  output: false,
  dirty: false,
  dirtyParts: new Set(),
  saving: null,
};
let timer,
  poll,
  previewSeq = 0;
const previewBooks = new Map();
const downloadSelections = new Map();
function previewBook(jid = state.job.id, mid = state.member) {
  const key = jid + "/" + mid;
  if (!previewBooks.has(key))
    previewBooks.set(key, {
      results: {},
      local: new Set(),
      busy: new Set(),
      queued: new Set(),
      sequence: {},
      selectedView: null,
    });
  return previewBooks.get(key);
}
const stages = {
  uploading: "上传中",
  queued: "等待处理",
  processing: "预处理中",
  review: "待人工审核",
  generating: "成品生成中",
  complete: "已完成",
  failed: "处理失败",
  legacy: "旧版历史素材",
};
const kinds = {
  body_scan: "体测图",
  body_report: "体测报告",
  training_report: "阶段报告",
  daily_training: "训练日常",
  life_photo: "生活照",
  testimonial: "会员感言",
  other: "其他",
};
const media = (jid, id) => `/api/jobs/${jid}/media/${id}`;
const member = () => state.review?.members.find((m) => m.id === state.member);
function toast(message, error = false) {
  $("#toast").textContent = message;
  $("#toast").className = error ? "show error" : "show";
  clearTimeout(timer);
  timer = setTimeout(() => ($("#toast").className = ""), 5000);
}
async function api(url, options = {}) {
  const r = await fetch("/api" + url, {
    ...options,
    headers:
      options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json", ...options.headers },
  });
  let data;
  try {
    data = await r.json();
  } catch {
    throw new Error("服务暂时不可用，请稍后重试");
  }
  if (!r.ok) {
    if (r.status === 401 && url != "/session") showLogin();
    throw new Error(data.detail || "请求失败");
  }
  return data;
}
const send = (url, body, method = "POST") =>
  api(url, { method, body: JSON.stringify(body) });
function shell(content, active = state.page) {
  $("#app").innerHTML =
    `<header class="topbar"><a class="wordmark" href="#home"><b>UP<span>↗</span></b><div>会员案例工作台<small>CASE STUDIO</small></div></a><nav>${[
      ["home", "首页"],
      ["history", "历史记录"],
      ["stickers", "贴纸库"],
      ["fonts", "字体库"],
      ["settings", "设置"],
    ]
      .map(
        ([p, t]) =>
          `<a href="#${p}" class="${active === p ? "active" : ""}">${t}</a>`,
      )
      .join(
        "",
      )}</nav><button class="quiet" id="logout">退出工作台 ↗</button></header><main>${content}</main><footer class="site-foot"><span>UP FITNESS · 每一份改变，都值得被记录。</span><span>会员案例制作工作流</span></footer>`;
  $("#logout").onclick = async () => {
    await api("/session", { method: "DELETE" });
    await clearMediaCache();
    previewBooks.clear();
    showLogin();
  };
}
function showLogin() {
  clearInterval(poll);
  clearMediaCache();
  previewBooks.clear();
  $("#modal").innerHTML = "";
  document.body.classList.remove("modal-open");
  $("#app").innerHTML =
    `<div class="login-layout"><div class="login-art"><b>UP↗</b><p>把改变，<br>留在镜头里。</p><small>MEMBER CASE STUDIO / 会员案例工作台</small><div class="art-lines"></div></div><form id="login" class="login-card"><span class="eyebrow">WELCOME BACK</span><h1>开始创作会员案例</h1><p>连接你的素材、审核记录与成品。</p><label>工作台访问码<input name="code" type="password" autocomplete="current-password" required autofocus placeholder="输入访问码"></label><button class="primary">进入工作台 <span>↗</span></button><p id="login-error" class="error-text" role="alert"></p></form></div>`;
  $("#login").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await send("/session", { code: new FormData(e.target).get("code") });
      await route();
    } catch (e) {
      $("#login-error").textContent = e.message;
    }
  };
}
async function route() {
  clearInterval(poll);
  try {
    await flush();
    const [page, jid] = location.hash.slice(1).split("/");
    state.page = ["history", "settings", "stickers", "fonts"].includes(page) ? page : "home";
    await loadFonts(api);
    state.job = null;
    state.review = null;
    state.output = false;
    if (page === "job" && jid) {
      await openJob(jid);
      return;
    }
    if (state.page === "fonts") await fontLibrary({api,shell,toast});
    else if (state.page === "stickers") await libraryPage({api,shell});
    else if (state.page === "settings") await settings();
    else if (state.page === "history") await history();
    else await home();
  } catch (e) {
    toast(e.message, true);
  }
}
async function home() {
  const jobs = await api("/jobs");
  shell(
    `<section class="hero"><div><span class="eyebrow">YOUR NEXT TRANSFORMATION</span><h1>让每一份改变，<br>成为值得分享的案例<span class="red">。</span></h1><p>上传会员素材，完成审核，一次生成整套案例成品。</p></div><div class="hero-stat"><b>${jobs
      .filter((j) => j.status === "complete")
      .length.toString()
      .padStart(
        2,
        "0",
      )}</b><span>已完成批次</span><i>↗</i></div></section><div class="home-grid"><section class="card upload-card"><div class="section-title"><span class="number">01</span><h2>上传一批新素材</h2><span class="pill">ZIP 压缩包</span></div><label class="drop-zone" id="drop" role="button" tabindex="0" aria-label="选择 ZIP 压缩包"><input id="zip" type="file" accept=".zip" hidden><span class="upload-icon">↑</span><h3>拖入压缩包，开始制作</h3><p>或点击选择文件 · 最大 4 GB</p><div class="folder-example">项目文件夹 / xxx店 / 教练-会员 / 图片与报告</div></label><div class="upload-progress" id="upload-progress" hidden><progress max="100"></progress><span></span></div><p class="muted">仅处理「xxx店」目录；参考模板和说明文件自动排除。原始素材会保留。</p></section><aside class="card process-card"><span class="eyebrow">HOW IT WORKS</span><h2>从素材到成品，三步完成</h2>${[
      ["01", "自动预处理", "分类、照片标准化、训练阶段识别"],
      ["02", "人工审核", "确认前后顺序，调整文案、取景与表格"],
      ["03", "生成并下载", "按会员预览，单独或整批打包"],
    ]
      .map(
        ([n, t, d]) =>
          `<div class="process-item"><b>${n}</b><div><h3>${t}</h3><p>${d}</p></div></div>`,
      )
      .join(
        "",
      )}<div class="process-note">可随时回到审核，修改后生成新版本。</div></aside></div><section class="recent"><div class="section-title"><h2>最近的制作记录</h2><a href="#history">查看全部 ↗</a></div>${jobs.length ? jobList(jobs.slice(0, 4)) : '<div class="empty">还没有制作记录，上传第一批会员素材吧。</div>'}</section>`,
  );
  $("#zip").onchange = (e) => upload(e.target.files[0]);
  const d = $("#drop");
  d.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      $("#zip").click();
    }
  };
  d.ondragover = (e) => {
    e.preventDefault();
    d.classList.add("drag");
  };
  d.ondragleave = () => d.classList.remove("drag");
  d.ondrop = (e) => {
    e.preventDefault();
    d.classList.remove("drag");
    upload(e.dataTransfer.files[0]);
  };
}
function jobList(jobs) {
  return `<div class="job-list">${jobs.map((j) => `<a class="job-row" href="#job/${j.id}"><div class="file-symbol">ZIP</div><div class="job-name"><strong>${E(j.name)}</strong><small>${formatDate(j.created_at)} · ${j.member_count || 0} 位会员 · ${j.product_count || 0} 张成品</small></div><span class="status ${j.status}">${stages[j.status] || j.status}</span><span class="arrow">↗</span></a>`).join("")}</div>`;
}
function formatDate(t) {
  return t
    ? new Date(t).toLocaleString("zh-CN", { hour12: false })
    : "历史批次";
}
function upload(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".zip"))
    return toast("请选择 ZIP 压缩包", true);
  const box = $("#upload-progress");
  box.hidden = false;
  box.querySelector("span").textContent = "正在上传…";
  const form = new FormData();
  form.append("file", file);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      box.querySelector("progress").value = (e.loaded / e.total) * 100;
      box.querySelector("span").textContent =
        `正在上传 ${Math.round((e.loaded / e.total) * 100)}%`;
    }
  };
  xhr.onload = () => {
    let d;
    try {
      d = JSON.parse(xhr.responseText);
    } catch {
      return toast("上传失败，请重试", true);
    }
    if (xhr.status < 300) location.hash = "job/" + d.id;
    else {
      box.hidden = true;
      toast(d.detail || "上传失败", true);
    }
  };
  xhr.onerror = () => toast("网络中断，请重新上传", true);
  xhr.send(form);
}
async function history() {
  const [jobs, legacy] = await Promise.all([api("/jobs"), api("/legacy")]);
  shell(
    `<section class="page-head"><span class="eyebrow">YOUR WORKSPACE ARCHIVE</span><h1>历史记录</h1><p>继续未完成的审核，或回看每一版成品。</p></section>${jobList(jobs)}${!jobs.length ? '<div class="empty">新工作台还没有处理记录。</div>' : ""}${legacy.length ? `<details class="card legacy"><summary>旧版历史素材 · ${legacy.length} 个批次</summary><p class="muted">原文件仍保留。导入后将按新工作流预处理，并建立新的审核记录。</p>${legacy.map((l) => `<div class="legacy-row"><span>${E(l.name)}<small>${l.asset_count} 个素材</small></span><button data-import="${E(l.id)}">导入新工作流</button></div>`).join("")}</details>` : ""}`,
  );
  $$("[data-import]").forEach(
    (b) =>
      (b.onclick = async () => {
        b.disabled = true;
        try {
          const j = await send(`/legacy/${b.dataset.import}/import`, {});
          location.hash = "job/" + j.id;
        } catch (e) {
          toast(e.message, true);
          b.disabled = false;
        }
      }),
  );
}
let defaultFontOverrides = {};
const defaultFontFields = {brand_name:'vs.brand_name',address:'vs.address',consent_text:'vs.consent_text',before_text:'vs.before_text',after_text:'vs.after_text',vs_text:'vs.vs_text',title_front:'vs.titles.front',title_side:'vs.titles.side',title_back:'vs.titles.back'};
async function settings() {
  const c = await api("/settings");
  defaultFontOverrides = {...c.font_overrides};
  shell(
    `<section class="page-head"><span class="eyebrow">PREFERENCES</span><h1>工作台设置</h1><p>品牌文案用于新批次；字体、画布与生活照遮挡在下一次预览或生成时生效，历史成品保留。</p></section><form id="settings" class="settings-grid"><section class="card"><div class="section-title"><span class="number">01</span><h2>品牌与成品</h2></div>${input("品牌名称", "brand_name", c.brand_name)}${input("默认地址", "address", c.address)}${input("案例说明", "consent_text", c.consent_text)}<div class="field-grid">${input("标准照片宽度", "display_width", c.display_width, "number")}</div><div class="field-grid">${input("训练前文字", "before_text", c.before_text)}${input("训练后文字", "after_text", c.after_text)}</div>${input("中央文字", "vs_text", c.vs_text)}<div class="field-grid three">${Object.entries(
      c.titles,
    )
      .map(([k, v]) =>
        input(
          { front: "正面标题", side: "侧面标题", back: "背面标题" }[k],
          "title_" + k,
          v,
        ),
      )
      .join(
        "",
      )}</div><label>默认 Logo <input id="logo" type="file" accept="image/png,image/jpeg,image/webp"></label><p class="muted">${c.logo_configured ? "已配置默认 Logo。" : "尚未设置 Logo，默认显示品牌文字。"}上传包内的 logo 目录优先使用。</p></section><section class="card"><div class="section-title"><span class="number">02</span><h2>视觉模型</h2></div>${input("兼容接口 Base URL", "base_url", c.model.base_url)}${input("模型名", "model", c.model.model)}${input(c.model.key_configured ? "API Key · 已配置，留空保留" : "API Key", "api_key", "", "password")}${input("模型并发数（1–4）", "model_workers", c.model_workers, "number")}<label>性别自动采用阈值<input name="gender_confidence_threshold" type="number" min="0.5" max="0.99" step="0.01" value="${c.gender_confidence_threshold}"></label><p class="muted">仅根据报告或文字依据补全，低于阈值保留待确认，不按人物外貌推断。</p><div class="info-panel">照片校正与人物检测在远程 GPU 服务器运行；视觉模型用于分类与语义判断。审核预览和成品生成复用既有结果。</div><button class="primary" type="submit">保存设置 <span>↗</span></button><p class="muted">API Key 仅保存在服务端，不会返回浏览器。</p></section>${imageSettings(c.image_model)}<section class="card"><div class="section-title"><span class="number">04</span><h2>字体与统一画布</h2></div><label>全局默认字体<select name="default_font">${fontOptions(c.default_font,false)}</select></label><p class="muted">文字旁的字体选择优先；未指定的项跟随默认。<a href="#fonts">管理字体库 ↗</a></p><div class="field-grid"><label>统一成品宽度（像素）<input name="output_width" type="number" min="540" max="2160" step="3" value="${c.output_width}" required></label><label>填充背景色<input name="output_background" type="color" value="${E(c.output_background)}"></label></div><p class="info-panel" id="output-size">成品 ${c.output_width} × ${c.output_width*4/3} 像素 · 固定 3:4</p><label class="check"><input name="mask_lifestyle" type="checkbox" ${c.mask_lifestyle?'checked':''}>生活照也使用会员头像遮挡</label><p class="muted">默认保留生活照原图和尺寸。开启后，尚未检查的生活照需在会员审核中重新准备头部遮挡；原图已有的贴纸仍会保留。</p></section></form>`,
  );
  $('#settings [name="output_width"]').oninput = event => {
    const w=Number(event.target.value);$('#output-size').textContent=`成品 ${w} × ${Math.round(w*4/3)} 像素 · 固定 3:4`;
  };
  $("#settings").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target),
      v = Object.fromEntries(f);
    const body = {};
    for (const k of [
      "brand_name",
      "address",
      "consent_text",
      "before_text",
      "after_text",
      "vs_text",
    ])
      body[k] = v[k];
    for (const k of [
      "output_width",
      "display_width",
      "model_workers",
      "gender_confidence_threshold",
    ])
      body[k] = Number(v[k]);
    body.default_font = v.default_font;
    body.output_background = v.output_background;
    body.mask_lifestyle = f.has('mask_lifestyle');
    body.font_overrides = {...c.font_overrides};
    for(const [key,value] of f.entries()) if(key.startsWith('font__')) {
      const path=key.slice(6), aliases=path==='vs.brand_name'?[path,'cover.brand_name','testimonial.brand']:path==='vs.address'?[path,'cover.address']:[path];
      for(const target of aliases) {if(value)body.font_overrides[target]=value;else delete body.font_overrides[target];}
    }
    body.titles = {
      front: v.title_front,
      side: v.title_side,
      back: v.title_back,
    };
    body.model = { base_url: v.base_url, model: v.model, api_key: v.api_key };
    body.image_model = {base_url:v.image_base_url,model:v.image_model,api_key:v.image_api_key,reuse_model_key:f.has("image_reuse_key")};
    try {
      await send("/settings", body, "PUT");
      if ($("#logo").files[0]) {
        const form = new FormData();
        form.append("file", $("#logo").files[0]);
        await api("/settings/logo", { method: "POST", body: form });
      }
      toast("设置已保存");
      await settings();
    } catch (e) {
      toast(e.message, true);
    }
  };
}
function input(label, name, value, type = "text") {
  const path=defaultFontFields[name],picker=path?fontSelect(path,defaultFontOverrides[path],'font__'+path):'';
  return `<label>${E(label)}<span class="font-field">${picker}<input aria-label="${E(label)}" type="${type}" name="${E(name)}" value="${E(value)}" autocomplete="${type === "password" ? "new-password" : "off"}"></span></label>`;
}
async function openJob(jid) {
  clearInterval(poll);
  state.job = await api("/jobs/" + jid);
  state.review = null;
  state.versions = [];
  state.output = false;
  state.selectedVersion = null;
  state.page = "home";
  if (state.job.review_version) {
    state.review = await api(`/jobs/${jid}/review`);
    state.member = state.review.members.some((m) => m.id === state.member)
      ? state.member
      : state.review.members[0]?.id;
    state.versions = await api(`/jobs/${jid}/versions`);
    state.output = state.job.status === "complete";
  }
  renderJob();
  poll = setInterval(refreshJob, 3500);
}
async function refreshJob() {
  if (!state.job) return;
  const jid = state.job.id;
  try {
    const j = await api("/jobs/" + jid);
    // Navigation may finish while an earlier progress request is still pending.
    if (state.job?.id !== jid) return;
    const changed =
      j.status !== state.job.status ||
      j.review_version !== state.job.review_version;
    state.job = j;
    if (changed && !state.dirty && !state.saving) {
      if (
        j.review_version &&
        (!state.review || j.review_version !== state.review.version)
      ) {
        state.review = await api(`/jobs/${j.id}/review`);
        if (!state.review.members.some((m) => m.id === state.member))
          state.member = state.review.members[0]?.id;
      }
      if (j.status === "complete") {
        state.versions = await api(`/jobs/${j.id}/versions`);
        state.output = true;
      }
      renderJob();
    } else if (!state.review) {
      $("#progress-number") &&
        ($("#progress-number").textContent = j.progress + "%");
      $(".progress-large progress") &&
        ($(".progress-large progress").value = j.progress);
      $("#nodes") && ($("#nodes").innerHTML = nodes(j));
      $("#member-progress") &&
        ($("#member-progress").innerHTML = memberProgress(j));
    }
  } catch (e) {
    console.warn(e.message);
  }
}
function stepper(j) {
  const current = state.output ? 3 : state.review ? 2 : 1;
  return `<div class="stepper">${[
    ["01", "预处理"],
    ["02", "人工审核"],
    ["03", "成品生成"],
  ]
    .map(
      ([n, t], i) =>
        `<button ${i === 0 || !state.review || (i === 2 && !state.versions.length) ? "disabled" : ""} data-step="${i + 1}" class="${i + 1 === current ? "selected" : i + 1 < current ? "done" : ""}"><b>${n}</b>${t}<span>${i + 1 < current ? "✓" : ""}</span></button>`,
    )
    .join("")}</div>`;
}
function renderJob() {
  const j = state.job;
  shell(
    `<div class="workspace-head"><div><a href="#history" class="muted">← 返回历史记录</a><h1>${E(j.name)}</h1></div><span class="status ${j.status}">${stages[j.status]}</span></div>${stepper(j)}${state.review ? `<div class="workspace"><aside id="members" class="member-sidebar"></aside><section id="review-main"></section></div>` : progress(j)}`,
  );
  $$("[data-step]").forEach(
    (b) =>
      (b.onclick = () => {
        state.output = b.dataset.step === "3";
        renderJob();
      }),
  );
  if (state.review) {
    sidebar();
    if (state.output) outputs();
    else reviewPanel();
  }
  $("#retry") &&
    ($("#retry").onclick = async () => {
      try {
        await send(`/jobs/${j.id}/retry`, {});
        await openJob(j.id);
      } catch (e) {
        toast(e.message, true);
      }
    });
}
function nodes(j) {
  return j.nodes
    .map(
      (n) =>
        `<div class="node"><span class="node-dot ${n.status}">${n.status === "complete" ? "✓" : n.status === "skipped" ? "—" : n.status === "failed" ? "!" : "↻"}</span><b>${E(n.name)}</b><small>${{ complete: "已完成", running: "处理中", skipped: "无对应素材", failed: "失败" }[n.status]}</small></div>`,
    )
    .join("");
}
function progress(j) {
  return `<section class="card progress-card"><span class="eyebrow">PREPARING YOUR MATERIALS</span><h2>${j.status === "failed" ? "部分处理需要重试" : "正在整理这一批改变"}</h2><p class="muted">可以离开页面，处理会在服务器继续。完成后进入人工审核。</p><div class="progress-large"><b id="progress-number">${j.progress}%</b><progress max="100" value="${j.progress}"></progress></div><div id="nodes">${nodes(j)}</div>${j.error ? `<div class="error-panel">${E(j.error)}<button id="retry">重试未完成会员与节点</button></div>` : ""}<div id="member-progress">${memberProgress(j)}</div></section>`;
}
function memberProgress(j) {
  const info = j.preprocessing;
  if (!info) return "";
  const groups = info.groups || [];
  const lists = [
    ["running", "正在并行预处理", "没有正在处理的会员"],
    ["complete", "已完成预处理", "会员处理完成后会显示在这里"],
    ["queued", "排队中", "没有排队中的会员"],
  ];
  if (groups.some((g) => g.status === "failed"))
    lists.push(["failed", "需要重试", ""]);
  return `<div class="member-progress-head"><div><span class="eyebrow">MEMBER WORKFLOWS</span><h3>按会员并行处理</h3></div><span class="muted">${groups.filter((g) => g.status === "complete").length} / ${groups.length} 已完成 · 最多 ${info.limit} 位同时推进</span></div><div class="member-progress-lists">${lists
    .map(([status, title, empty]) => {
      const items = groups.filter((g) => g.status === status);
      return `<section class="member-progress-list ${status}" aria-label="${title}"><h4>${title}<span>${items.length}</span></h4><ul>${items.length ? items.map((g) => `<li data-member-progress="${E(g.id)}"><div class="member-progress-label"><div><small>${E(g.store)}</small><strong>${E(g.coach || "未填写教练")}-${E(g.member)}</strong></div><span>${g.progress}%</span></div><progress max="100" value="${g.progress}" aria-label="${E(g.member)}预处理进度"></progress><p>${g.image_count} 张图片${status === "complete" ? " · 已准备好审核资料" : status === "queued" ? " · 等待处理名额" : ""}</p>${g.steps.map((n) => `<div class="member-step"><span class="node-dot ${n.status}">${n.status === "waiting" ? "◷" : "↻"}</span>${E(n.name)}${n.status === "waiting" ? `<small>等待 ${n.resource === "gpu" ? "GPU" : "图片处理"} 通道</small>` : ""}</div>`).join("")}${g.error ? `<p class="error-text">${E(g.error)}</p>` : ""}</li>`).join("") : `<li class="member-progress-empty">${empty}</li>`}</ul></section>`;
    })
    .join("")}</div>`;
}
function sidebar() {
  const groups = Object.groupBy
    ? Object.groupBy(state.review.members, (m) => m.store)
    : state.review.members.reduce(
        (a, m) => ((a[m.store] ??= []).push(m), a),
        {},
      );
  $("#members").innerHTML =
    `<div class="sidebar-head">会员目录 <span>${state.review.members.length}</span></div>${Object.entries(
      groups,
    )
      .map(
        ([store, ms]) =>
          `<div class="store-group"><h3>${E(store)}<span>${ms.length}</span></h3>${ms.map((m) => `<button data-member="${m.id}" class="member-link ${m.id === state.member ? "active" : ""}"><span class="avatar">${E(m.profile.name.slice(0, 1))}</span><span><b>${E((m.profile.coach || "未填写教练") + "-" + m.profile.name)}</b><small>${m.photos.length} 张体测图${m.photos.some((p) => !p.confirmed) ? " · 有待审核" : ""}</small></span></button>`).join("")}</div>`,
      )
      .join("")}`;
  $$("[data-member]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          await flush();
          state.member = b.dataset.member;
          state.preview = null;
          sidebar();
          state.output ? outputs() : reviewPanel();
        } catch (e) {
          toast(e.message, true);
        }
      }),
  );
}
function section(n, title, hint, body) {
  return `<section class="card review-section"><div class="section-title"><span class="number">${n}</span><div><h2>${title}</h2><p>${hint}</p></div></div>${body}</section>`;
}
function updateAction(section) {
  return `<div class="preview-actions"><button type="button" class="outline-red" data-refresh="${section}">更新展示效果 ↗</button><span class="muted" data-preview-status="${section}"></span>${section!=="table"?`<button type="button" data-mask-editor="${section}">调整面部遮罩</button>`:""}</div>`;
}
function identitySummary(m) {
  return `<div class="identity-summary">${["gender", "coach"]
    .map((field) => {
      const info = m.identity?.[field];
      if (!info) return "";
      const label = field === "gender" ? "性别" : "教练";
      const status =
        info.status === "manual"
          ? "人工填写"
          : info.status === "adopted"
            ? "自动采用"
            : "待确认";
      return `<details><summary>${label}：${status}${info.status !== "manual" && typeof info.confidence === "number" ? ` · 参考置信度 ${Math.round(info.confidence * 100)}%` : ""}</summary><p>${E(info.reason)}${info.candidate && info.status === "needs_review" ? "；候选：" + E(info.candidate) : ""}</p><p>${E(info.evidence?.source || "暂无文字依据")} ${E(info.evidence?.quote || "")}</p>${field === "gender" ? `<small>自动采用阈值 ${Math.round((info.threshold || 0.9) * 100)}%。置信度为模型参考值，可人工修正。</small>` : ""}</details>`;
    })
    .join("")}</div>`;
}
function field(label, path, value, area = false) {
  const picker=/^(vs|cover|table)\./.test(path)?fontSelect(path,member()?.fonts?.[path]):'';
  return `<label>${E(label)}<span class="font-field ${area?'font-area':''}">${picker}${area ? `<textarea aria-label="${E(label)}" data-field="${path}" rows="4">${E(value)}</textarea>` : `<input aria-label="${E(label)}" data-field="${path}" value="${E(value)}">`}</span></label>`;
}

function bindFonts(root=document) {
  root.querySelectorAll('[data-font]').forEach(el=>el.onchange=()=>{
    const m=member(),key=el.dataset.font;m.fonts??={};
    if(el.value)m.fonts[key]=el.value;else delete m.fonts[key];
    dirty('fonts',[key.split('.')[0]]);
  });
}
function reviewPanel() {
  const m = member();
  if (!m) return;
  const j = state.job;
  $("#review-main").innerHTML =
    `<div class="review-heading"><div><span class="eyebrow">MEMBER REVIEW</span><h2>${E(m.profile.name)}的案例</h2></div><span id="save-status" class="muted">所有修改已保存</span></div>${j.error ? `<div class="error-panel">${E(j.error)}<button id="regen">重新生成</button></div>` : ""}
${section(
  "01",
  "会员基础信息",
  "报告信息优先。会员名与性别会同步更新成品称呼。",
  `${privacyPanel(m)}<div class="field-grid three">${field("会员姓名", "profile.name", m.profile.name)}<label>会员性别<select data-field="profile.gender">${[
    ["", "未设置"],
    ["男", "男"],
    ["女", "女"],
  ]
    .map(
      ([v, t]) =>
        `<option value="${v}" ${m.profile.gender === v ? "selected" : ""}>${t}</option>`,
    )
    .join(
      "",
    )}</select></label>${field("教练姓名", "profile.coach", m.profile.coach)}</div>${identitySummary(m)}<details class="extra-fonts"><summary>其他成品字体</summary><div class="field-grid">${[['testimonial.title','会员感言标题'],['testimonial.brand','感言品牌文字']].map(([key,label])=>`<label>${label}${fontSelect(key,m.fonts?.[key])}</label>`).join('')}</div><p class="muted">更改后在下一次成品生成时生效。</p></details>`,
)}
${section("02", "体测图训练阶段", "拖动照片调整前后顺序；同朝向多张时，可选择首选图用于对比与封面。", `<div class="phase-boards" id="boards"></div><div class="row-actions"><button id="confirm-photos">确认本会员所有阶段标记</button><span class="muted">推断与待审结果会保留在下载包的审核说明中。</span></div>`)}
${section("02B", "审核完整六图", "训练前后各一组正面、侧面、背面；六个头像可分别调整。", `${updateAction("three_views")}<div class="six-preview" id="three_views-preview"><div class="empty">点击更新展示效果查看六图拼图，或直接调整面部遮罩。</div></div>`)}
${section(
  "03",
  "审核同朝向对比图",
  "修改会自动保存；点击更新展示效果后刷新本区域图片。",
  `${updateAction("vs")}<div class="edit-with-preview"><div><div class="field-grid">${field("会员称呼", "vs.nickname", m.vs.nickname)}${field("品牌名称", "vs.brand_name", m.vs.brand_name)}</div>${field("地址", "vs.address", m.vs.address)}${field("案例说明", "vs.consent_text", m.vs.consent_text)}<div class="field-grid three">${field("训练前", "vs.before_text", m.vs.before_text)}${field("训练后", "vs.after_text", m.vs.after_text)}${field("中央文字", "vs.vs_text", m.vs.vs_text)}</div><div class="field-grid three">${Object.keys(
    m.vs.titles,
  )
    .map((v) =>
      field(
        { front: "正面标题", side: "侧面标题", back: "背面标题" }[v],
        "vs.titles." + v,
        m.vs.titles[v],
      ),
    )
    .join(
      "",
    )}</div><label>底部指标文字</label><div id="metrics"></div><button class="small" id="add-metric">＋ 添加一项</button></div><div class="preview-pane" id="vs-preview"><div class="empty">正在准备成品预览…</div></div></div>`,
)}
${section("04", "审核会员案例封面", "封面独立取景：从正面原图选取头部至胯部，保持人物比例。", `${updateAction("cover")}<div class="row-actions"><button id="cover-ai" class="outline-red">AI生成 ✦</button><span class="muted">选择生成项与资料，套用你的提示词模板。</span></div><div class="edit-with-preview"><div><div class="field-grid">${field("主标题", "cover.title", m.cover.title)}${field("角标", "cover.badge", m.cover.badge)}</div>${field("副标题", "cover.subtitle", m.cover.subtitle)}${field("成果标题", "cover.headline", m.cover.headline)}${field("内容介绍", "cover.story", m.cover.story, true)}<div class="field-grid">${field("品牌名称", "cover.brand_name", m.cover.brand_name)}${field("地址", "cover.address", m.cover.address)}</div>${field("地址第二行 / 门店", "cover.store_text", m.cover.store_text)}<button id="crop" class="outline-red">调整左右照片取景 ↗</button><p class="muted">也可点击右侧封面。左右取景框独立调整，可即时查看组合效果。</p></div><div class="preview-pane cover-preview" id="cover-preview"><div class="empty">正在准备封面预览…</div></div></div>`)}
${section("05", "审核体测对比表", "原始体测数据优先，汇总表补充缺项。可修改五列内容、增加或删除行。", `${updateAction("table")}<div class="field-grid">${field("表格标题", "table.table_title", m.table.table_title)}${field("报告标题", "table.report_title", m.table.report_title)}</div><div class="field-grid">${field("报告左标签", "table.before_label", m.table.before_label)}${field("报告右标签", "table.after_label", m.table.after_label)}</div><div id="table-editor" class="table-scroll"></div><button id="add-row" class="small">＋ 增加一行</button><div class="table-preview" id="table-preview"></div>`)}
<details class="card sources"><summary>查看原始素材分类与跳过信息 · ${m.sources.length} 张</summary><div class="source-grid">${m.sources.map((s) => `<figure><a href="${media(j.id, s.media)}" target="_blank"><img loading="lazy" src="${media(j.id, s.media)}"></a><figcaption><b>${kinds[s.kind] || s.kind}</b><small>${E(s.reason)}</small></figcaption></figure>`).join("")}</div><div id="gaps"></div></details><div class="review-bottom"><div><b>确认这一批案例</b><small>共 ${state.review.members.length} 位会员 · 可以保留待审标记生成，之后再修正</small></div><button id="generate" class="primary" ${["queued", "processing", "generating"].includes(j.status) ? "disabled" : ""}>${j.status === "generating" ? "正在生成…" : "生成整批成品"} ↗</button></div>`;
  renderBoards();
  renderMetrics();
  renderTable();
  bindFonts();
  bindPrivacy({member:m,job:j.id,api,send,flush,version:()=>state.review.version,toast,
    apply:(result,redraw)=>{
      if(state.job?.id!==j.id||state.member!==m.id)return;
      if(state.dirty||state.saving)throw new Error("审核内容正在修改，请保存后刷新查看遮挡结果");
      if(result){state.review=result;state.job.review_version=result.version;}
      if(redraw)reviewPanel();
    }});
  $$("[data-field]").forEach(
    (el) =>
      (el.oninput = () => {
        const parts = el.dataset.field.split(".");
        let obj = m;
        for (const p of parts.slice(0, -1)) obj = obj[p];
        obj[parts.at(-1)] = el.value;
        dirty(parts[0]);
        if (parts[0] === "profile") sidebar();
      }),
  );
  $("#confirm-photos").onclick = () => {
    m.photos.forEach((p) => (p.confirmed = true));
    dirty("photos");
    renderBoards();
  };
  $("#add-row").onclick = () => {
    if (m.table.rows.length >= 20) return toast("最多 20 行", true);
    m.table.rows.push({
      type: "新指标",
      key: "custom_" + Date.now(),
      before: "",
      after: "",
      delta: "",
      unit: "",
    });
    renderTable();
    dirty("table");
  };
  $("#add-metric").onclick = () => {
    if (m.vs.metrics.length >= 6) return toast("最多 6 项", true);
    m.vs.metrics.push({ text: "", key: "custom" });
    renderMetrics();
    dirty("vs");
  };
  $$("[data-mask-editor]").forEach(b=>b.onclick=()=>editMasks(b.dataset.maskEditor));
  $("#crop").onclick = crop;
  $("#cover-ai").onclick = aiCover;
  $$("[data-refresh]").forEach(
    (b) => (b.onclick = () => updatePreview(b.dataset.refresh)),
  );
  $("#generate").onclick = generate;
  $("#regen") && ($("#regen").onclick = generate);
  loadPreviews();
}
function renderBoards() {
  const m = member();
  $("#boards").innerHTML = ["before", "after"]
    .map(
      (phase) =>
        `<div class="phase-board" data-phase="${phase}"><div class="board-title"><h3>${phase === "before" ? "训练前" : "训练后"} <span>${m.photos.filter((p) => p.phase === phase).length}</span></h3><small>${phase === "before" ? "BEFORE" : "AFTER"}</small></div><div class="photo-grid">${
          m.photos
            .filter((p) => p.phase === phase)
            .map(
              (p) =>
                `<article draggable="true" data-photo="${p.asset_id}" class="photo-card ${!p.confirmed ? "needs-review" : ""}"><img draggable="false" loading="lazy" src="${media(state.job.id, p.media)}"><span class="photo-label">${E(p.asset_id)}</span><div class="photo-controls"><select data-view="${p.asset_id}" aria-label="照片朝向">${[
                  ["front", "正面"],
                  ["side_left", "左侧"],
                  ["side_right", "右侧"],
                  ["side", "侧面"],
                  ["back", "背面"],
                ]
                  .map(
                    ([v, t]) =>
                      `<option value="${v}" ${p.view === v ? "selected" : ""}>${t}</option>`,
                  )
                  .join(
                    "",
                  )}</select><button data-move="${p.asset_id}" title="移动到另一阶段">⇄</button></div><label class="check"><input type="checkbox" data-prefer="${p.asset_id}" ${p.preferred ? "checked" : ""}> 设为首选</label><small class="photo-flag">${p.confirmed ? "已确认" : p.label_kind === "inferred" ? "推断 · 请核对" : "待审 · 请核对"}</small></article>`,
            )
            .join("") || '<div class="empty drop-empty">将照片拖到这里</div>'
        }</div></div>`,
    )
    .join("");
  $$("[data-photo]").forEach(
    (c) =>
      (c.ondragstart = (e) => {
        e.dataTransfer.setData("text/plain", c.dataset.photo);
      }),
  );
  $$("[data-phase]").forEach((b) => {
    b.ondragover = (e) => {
      e.preventDefault();
      b.classList.add("over");
    };
    b.ondragleave = () => b.classList.remove("over");
    b.ondrop = (e) => {
      e.preventDefault();
      b.classList.remove("over");
      move(e.dataTransfer.getData("text/plain"), b.dataset.phase);
    };
  });
  $$("[data-move]").forEach(
    (b) =>
      (b.onclick = () => {
        const p = m.photos.find((p) => p.asset_id === b.dataset.move);
        move(p.asset_id, p.phase === "before" ? "after" : "before");
      }),
  );
  $$("[data-view]").forEach(
    (s) =>
      (s.onchange = () => {
        const p = m.photos.find((p) => p.asset_id === s.dataset.view);
        p.view = s.value;
        p.confirmed = true;
        p.preferred = false;
        dirty("photos");
      }),
  );
  $$("[data-prefer]").forEach(
    (b) =>
      (b.onchange = () => {
        const p = m.photos.find((p) => p.asset_id === b.dataset.prefer);
        if (b.checked)
          m.photos.forEach((x) => {
            if (
              x.phase === p.phase &&
              (x.view.startsWith("side") ? "side" : x.view) ===
                (p.view.startsWith("side") ? "side" : p.view)
            )
              x.preferred = false;
          });
        p.preferred = b.checked;
        renderBoards();
        dirty("photos");
      }),
  );
}
function move(id, phase) {
  const p = member().photos.find((p) => p.asset_id === id);
  if (!p) return;
  p.phase = phase;
  p.confirmed = true;
  p.preferred = false;
  renderBoards();
  sidebar();
  dirty("photos");
}
function renderMetrics() {
  $("#metrics").innerHTML = member()
    .vs.metrics.map(
      (m, i) =>
        `<div class="metric-row">${fontSelect('vs.metrics.'+i,member().fonts?.['vs.metrics.'+i])}<input data-metric="${i}" value="${E(m.text)}"><button data-remove-metric="${i}" aria-label="删除指标">×</button></div>`,
    )
    .join("");
  bindFonts($('#metrics'));
  $$("[data-metric]").forEach(
    (el) =>
      (el.oninput = () => {
        member().vs.metrics[el.dataset.metric].text = el.value;
        dirty("vs");
      }),
  );
  $$("[data-remove-metric]").forEach(
    (el) =>
      (el.onclick = () => {
        member().fonts=removeIndexedFonts(member().fonts,'vs.metrics',+el.dataset.removeMetric);
        dirty('fonts',['vs']);
        member().vs.metrics.splice(+el.dataset.removeMetric, 1);
        renderMetrics();
        dirty("vs");
      }),
  );
}
function renderTable() {
  const t = member().table;
  $("#table-editor").innerHTML =
    `<table class="edit-table"><thead><tr>${t.headers.map((v, i) => `<th>${fontSelect('table.headers.'+i,member().fonts?.['table.headers.'+i])}<input data-header="${i}" value="${E(v)}"></th>`).join("")}<th></th></tr></thead><tbody>${t.rows.map((r, i) => `<tr>${["type", "before", "after", "delta", "unit"].map((k) => `<td>${fontSelect(`table.rows.${i}.${k}`,member().fonts?.[`table.rows.${i}.${k}`])}<input data-cell="${i}:${k}" value="${E(r[k])}" aria-label="${E(r.type)} ${k}"></td>`).join("")}<td><button data-remove-row="${i}" title="删除行">×</button></td></tr>`).join("")}</tbody></table>`;
  bindFonts($('#table-editor'));
  $$("[data-cell]").forEach(
    (el) =>
      (el.oninput = () => {
        const [i, k] = el.dataset.cell.split(":");
        t.rows[i][k] = el.value;
        dirty("table");
      }),
  );
  $$("[data-header]").forEach(
    (el) =>
      (el.oninput = () => {
        t.headers[el.dataset.header] = el.value;
        dirty("table");
      }),
  );
  $$("[data-remove-row]").forEach(
    (b) =>
      (b.onclick = () => {
        member().fonts=removeIndexedFonts(member().fonts,'table.rows',+b.dataset.removeRow);
        dirty('fonts',['table']);
        t.rows.splice(+b.dataset.removeRow, 1);
        renderTable();
        dirty("table");
      }),
  );
}
let saveTimer;
function dirty(part, affected) {
  state.dirtyParts.add(part || "cover");
  const sections = affected || (
    part === "profile" || part === "photos"
      ? ["vs", "cover", "three_views"]
      : [part || "cover"]);
  sections.forEach((s) => previewBook().local.add(s));
  previewButtons();
  state.dirty = true;
  $("#save-status") && ($("#save-status").textContent = "尚未保存…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(
    () => flush().catch((e) => toast(e.message, true)),
    800,
  );
}
async function flush() {
  clearTimeout(saveTimer);
  if (state.saving) await state.saving;
  if (!state.dirty || !state.review) return;
  const m = member(), before = structuredClone(m), parts = [...state.dirtyParts];
  const available = {
    profile: m.profile,
    photos: m.photos.map((p) =>
      Object.fromEntries(
        ["asset_id", "phase", "view", "confirmed", "preferred"].map((k) => [
          k,
          p[k],
        ]),
      ),
    ),
    vs: m.vs,
    cover: m.cover,
    table: m.table,
    fonts: m.fonts || {},
  };
  const payload = Object.fromEntries(parts.map(part => [part, available[part]]));
  state.saving = send(
    `/jobs/${state.job.id}/members/${m.id}?compact=true`,
    { version: state.review.version, member: payload },
    "PATCH",
  );
  try {
    const r = await state.saving;
    state.review.version = r.version;
    state.job.review_version = r.version;
    for (const part of parts) {
      if (JSON.stringify(m[part]) === JSON.stringify(before[part])) state.dirtyParts.delete(part);
    }
    mergeSaved(m, r.member, before);
    state.dirty = state.dirtyParts.size > 0;
    if (!state.dirty) {
      previewBook().local.clear();
      $("#save-status") && ($("#save-status").textContent = "所有修改已保存");
      for (const path of [
        "vs.nickname",
        "cover.title",
        "cover.subtitle",
        "cover.headline",
        "cover.story",
      ]) {
        const [group, key] = path.split("."),
          input = $(`[data-field="${path}"]`);
        if (input && input.value !== m[group][key]) input.value = m[group][key];
      }
      const identity = $(".identity-summary");
      if (identity) identity.outerHTML = identitySummary(m);
    }
    sidebar();
    previewButtons();
  } finally {
    state.saving = null;
  }
  if (state.dirty) await flush();
}
function previewButtons() {
  if (!member() || state.output) return;
  const b = previewBook(),
    m = member();
  for (const section of ["vs", "cover", "table", "three_views"]) {
    const button = $(`[data-refresh="${section}"]`),
      label = $(`[data-preview-status="${section}"]`);
    if (!button) continue;
    const pending =
      b.local.has(section) ||
      !b.results[section] ||
      b.results[section].fingerprint !== m.preview_keys?.[section];
    const prerequisite = previewPrerequisite(m, section);
    button.disabled = b.busy.has(section) || !pending || !!prerequisite;
    button.textContent = b.busy.has(section) ? "正在更新…" : "更新展示效果 ↗";
    if (label)
      label.textContent = prerequisite || (b.busy.has(section)
        ? "正在生成本区域预览"
        : pending
          ? "展示效果待更新"
          : "展示效果已更新");
  }
}
function mergePreview() {
  const results = previewBook().results;
  state.preview = {
    products: Object.values(results).flatMap((r) => r.products),
    cover_sources: results.cover?.cover_sources || [],
  };
}
function showPreview(section, result, jid, mid) {
  if (state.job?.id !== jid || state.member !== mid || state.output) return;
  const b = previewBook(),
    target = $(`#${section}-preview`);
  if (!target) return;
  async function showImage(img, product) {
    img.dataset.media = product.media;
    try {
      const url = await imageURL(media(jid, product.media));
      if (img.isConnected && img.dataset.media === product.media) img.src = url;
    } catch (e) {
      if (img.isConnected) toast(e.message, true);
    }
  }
  if (section === "vs") {
    const items = result.products.filter((p) => p.kind === "vs");
    target.innerHTML = items.length
      ? `<div class="preview-tabs">${items.map((v, i) => `<button data-vstab="${i}">${E(v.name.replace("对比图.jpg", ""))}</button>`).join("")}</div><img id="vs-image" alt="同朝向对比图预览">`
      : '<div class="empty">需要同朝向的训练前后照片，才能生成对比图。</div>';
    if (items.length) {
      const select = (i) => {
        b.selectedView = items[i].view || items[i].name;
        showImage($("#vs-image"), items[i]);
        $$("[data-vstab]").forEach((el) =>
          el.classList.toggle("active", +el.dataset.vstab === i),
        );
      };
      $$("[data-vstab]").forEach(
        (el) => (el.onclick = () => select(+el.dataset.vstab)),
      );
      select(
        Math.max(
          0,
          items.findIndex((p) => (p.view || p.name) === b.selectedView),
        ),
      );
      items.forEach((p) => imageURL(media(jid, p.media)).catch(() => {}));
    }
  } else if (section === "three_views") {
    const product=result.products.find(p=>p.kind==="three_views");
    target.innerHTML=product?'<img alt="完整六图预览">':'<div class="empty">缺少完整的训练前后正面、侧面、背面配对，暂不能生成六图。</div>';
    if(product)showImage(target.querySelector('img'),product);
  } else {
    const product = result.products.find(
      (p) => p.kind === (section === "table" ? "report" : "cover"),
    );
    target.innerHTML = product
      ? section === "cover"
        ? '<button class="image-button" id="open-cover"><img alt="会员案例封面预览"><span>点击调整照片取景 ↗</span></button>'
        : '<img alt="体测对比表预览">'
      : `<div class="empty">${section === "cover" ? "暂无可用封面，需要正面前后配对与可靠肩胯标定。" : "没有表格数据时，不生成体测报告成品。"}</div>`;
    if (product) showImage(target.querySelector("img"), product);
    if (section === "cover" && $("#open-cover"))
      $("#open-cover").onclick = crop;
  }
  mergePreview();
  previewButtons();
}
async function loadPreviews() {
  const jid = state.job.id,
    mid = state.member,
    b = previewBook(jid, mid);
  previewSeq++;
  for (const [section, result] of Object.entries(b.results))
    showPreview(section, result, jid, mid);
  previewButtons();
  try {
    const summary = await api(`/jobs/${jid}/previews/${mid}`);
    if (state.job?.id !== jid || state.member !== mid || state.output) return;
    for (const section of ["vs", "cover", "table", "three_views"]) {
      const result = summary.sections[section];
      if (
        result &&
        (!b.results[section] ||
          result.review_version >= b.results[section].review_version)
      ) {
        b.results[section] = result;
        showPreview(section, result, jid, mid);
      }
    }
    // Only the first ever preview is automatic. Existing images stay visible until explicitly updated.
    for (const section of ["vs", "cover", "table", "three_views"]) {
      if(section==="three_views")continue;
      const privacy = member()?.privacy;
      if(section!=="table" && privacy?.enabled!==false && privacy?.status!=="ready") {
        if(!b.results[section]) $(`#${section}-preview`).innerHTML='<div class="empty">请先在会员信息顶部准备面部遮挡。</div>';
        continue;
      }
      if (!b.results[section] && !b.local.has(section) && !state.dirty)
        updatePreview(section, true);
    }
    previewButtons();
  } catch (e) {
    toast(e.message, true);
  }
}
async function updatePreview(section, initial = false) {
  const jid = state.job.id,
    mid = state.member,
    b = previewBook(jid, mid);
  if (b.busy.has(section)) {
    if (!initial) b.queued.add(section);
    return;
  }
  if (initial && (b.local.has(section) || state.dirty)) return;
  b.busy.add(section);
  previewButtons();
  const seq = (b.sequence[section] || 0) + 1;
  b.sequence[section] = seq;
  try {
    await flush();
    if (
      state.job?.id !== jid ||
      state.member !== mid ||
      (initial && b.local.has(section))
    )
      return;
    const result = await send(`/jobs/${jid}/preview/${mid}`, {
      version: state.review.version,
      section,
    });
    if (seq !== b.sequence[section]) return;
    if (!b.queued.has(section)) {
      b.results[section] = result;
      showPreview(section, result, jid, mid);
    }
    if (!initial && !b.queued.has(section) && !b.local.has(section) &&
        state.member === mid && state.job?.id === jid &&
        member()?.preview_keys?.[section] === result.fingerprint)
      toast("展示效果已更新");
  } catch (e) {
    if (state.member === mid && state.job?.id === jid) toast(e.message, true);
  } finally {
    b.busy.delete(section);
    const again = b.queued.delete(section);
    if (state.member === mid && state.job?.id === jid) {
      previewButtons();
      if (again) void updatePreview(section);
    }
  }
}
async function editMasks(section) {
  try {
    await flush();
    const jid=state.job.id, mid=state.member;
    await openMaskEditor({job:jid,member:member(),section,version:state.review.version,send,
      onSave:async result=>{
        if(state.job?.id!==jid||state.member!==mid)return;
        const current=member();
        mergeSaved(current,result.members.find(m=>m.id===mid),structuredClone(current));
        state.review.version=result.version;state.job.review_version=result.version;
        previewButtons();
        void updatePreview(section);
        toast("面部遮罩调整已保存，预览正在后台更新");
      }});
  }catch(e){toast(e.message,true);}
}

async function aiCover() {
  try {
    await flush();
    const jid = state.job.id,
      m = member();
    await openCoverAI({
      api,
      send,
      job: jid,
      member: m,
      getVersion: () => state.review.version,
      apply: async (result) => {
        if (
          state.job?.id !== jid ||
          state.member !== m.id ||
          result.review_version !== state.review.version ||
          state.dirty
        )
          throw new Error("审核内容已变化，请重新生成");
        Object.assign(m.cover, result.fields);
        for (const [key, value] of Object.entries(result.fields)) {
          const input = $(`[data-field="cover.${key}"]`);
          if (input) input.value = value;
        }
        dirty("cover");
        await flush();
        toast("AI 文案已填入，点击更新展示效果查看封面");
      },
    });
  } catch (e) {
    toast(e.message, true);
  }
}
async function crop() {
  try {
    await flush();
    if (!state.preview) await loadPreviews();
    const ids = state.preview?.cover_sources?.map((c) => c.asset_id) || [];
    const m = member();
    let pics = ids.map((id) => m.photos.find((p) => p.asset_id === id));
    if (
      pics.length !== 2 ||
      pics.some(
        (p, i) =>
          !p || p.view !== "front" || p.phase !== (i ? "after" : "before"),
      )
    ) {
      pics = ["before", "after"].map(
        (phase) =>
          m.photos
            .filter(
              (p) => p.phase === phase && p.view === "front" && p.cover_media,
            )
            .sort((a, b) => Number(b.preferred) - Number(a.preferred))[0],
      );
    }
    if (pics.some((p) => !p)) return toast("需要两张可取景的正面照片", true);
    await openCrop(
      pics.map((p) => ({
        ...p,
        url: media(state.job.id, p.cover_media),
        crop:
          m.cover.crops[p.asset_id] ||
          state.preview?.cover_sources.find((s) => s.asset_id === p.asset_id)
            ?.crop ||
          p.default_crop,
      })),
      async (crops) => {
        Object.assign(m.cover.crops, crops);
        dirty("cover");
        await flush();
        toast("取景已保存，点击更新展示效果查看最新封面");
      },
      state.preview?.products.find((p) => p.kind === "cover")
        ? await imageURL(
            media(
              state.job.id,
              state.preview.products.find((p) => p.kind === "cover").media,
            ),
          )
        : null,
    );
  } catch (e) {
    toast(e.message, true);
  }
}
async function generate() {
  try {
    await flush();
    await send(`/jobs/${state.job.id}/generate`, {
      version: state.review.version,
    });
    state.job = await api("/jobs/" + state.job.id);
    toast("正在生成整批成品，可继续查看审核内容");
    renderJob();
  } catch (e) {
    toast(e.message, true);
  }
}
function downloadPicker(version) {
  const key = state.job.id + "/" + version.id;
  const plan = downloadPlan(version, downloadSelections.get(key) ?? null);
  return `<fieldset class="download-options"><legend>下载成品类型</legend><div class="download-options-head"><span class="muted">默认全部下载，适用于本会员与整批打包。</span><div><button type="button" class="quiet" id="download-all">全选</button><button type="button" class="quiet" id="download-clear">清空</button></div></div><div class="download-types">${plan.available.map((kind) => `<label><input type="checkbox" name="download-type" value="${E(kind)}" ${plan.selected.includes(kind) ? "checked" : ""}><span>${E(products[kind])}</span><small>${plan.counts[kind]} 张</small></label>`).join("")}</div><p id="download-count" class="muted" aria-live="polite"></p></fieldset>`;
}
function bindDownloads(version, member) {
  const key = state.job.id + "/" + version.id;
  const boxes = $$('.download-types input[name="download-type"]');
  function update() {
    const selected = boxes.filter((box) => box.checked).map((box) => box.value);
    downloadSelections.set(key, selected);
    const plan = downloadPlan(version, selected);
    $("#download-count").textContent = selected.length
      ? `已选 ${selected.length} 类 · 本会员 ${plan.byMember[member.member_id]} 张 · 整批 ${plan.total} 张`
      : "请至少选择一种成品图类型。";
    for (const [id, mid, count] of [
      ["download-member", member.member_id, plan.byMember[member.member_id]],
      ["download-batch", null, plan.total],
    ]) {
      const link = $("#" + id);
      link.setAttribute("aria-disabled", String(!count));
      link.tabIndex = count ? 0 : -1;
      if (count)
        link.href = archiveURL(state.job.id, version.id, mid, plan.queryTypes);
      else link.removeAttribute("href");
      link.title = count
        ? `下载 ${count} 张成品图`
        : "当前范围内没有所选类型的成品图";
      link.onclick = (event) => {
        if (!count) event.preventDefault();
      };
    }
  }
  for (const box of boxes) box.onchange = update;
  for (const [id, checked] of [
    ["download-all", true],
    ["download-clear", false],
  ]) {
    $("#" + id).onclick = () => {
      for (const box of boxes) box.checked = checked;
      update();
    };
  }
  update();
}
function outputs() {
  const v =
    state.versions.find(
      (v) => v.id === (state.selectedVersion || state.job.current_version),
    ) || state.versions[0];
  const m = v?.members.find((m) => m.member_id === state.member);
  if (!m) {
    $("#review-main").innerHTML =
      '<div class="empty">此会员暂无成品版本。</div>';
    return;
  }
  $("#review-main").innerHTML =
    `<div class="review-heading"><div><span class="eyebrow">READY TO SHARE</span><h2>${E(m.profile.name)}的成品</h2><p class="muted">${m.products.length} 张成品 · ${formatDate(v.created_at)} · 审核版本 ${v.review_version}</p></div><button id="back-review">返回审核 ↶</button></div><div class="download-bar"><div><b>案例成品已就绪</b><small>${m.review_required.length ? "有 " + m.review_required.length + " 张阶段标记仍需核对，审核说明已随包附带。" : "本会员的阶段标记已确认。"}</small></div><a class="button" id="download-member">下载本会员 ZIP ↓</a><a class="button primary" id="download-batch">整批打包下载 ↓</a></div>${downloadPicker(v)}<div class="version-bar"><label>成品版本 <select id="version">${state.versions.map((x) => `<option value="${E(x.id)}" ${x.id === v.id ? "selected" : ""}>${formatDate(x.created_at)} · 审核 v${x.review_version}</option>`).join("")}</select></label><span class="muted">修改审核内容后，生成新的成品版本。</span></div>${Object.entries(
      products,
    )
      .map(([kind, title]) => {
        const items = m.products.filter((p) => p.kind === kind);
        return items.length
          ? `<section class="product-section"><div class="section-title"><h3>${title}</h3><span class="pill">${items.length}</span></div><div class="product-grid ${kind === "single" ? "singles" : ""}">${items.map((p) => `<figure><a target="_blank" href="${media(state.job.id, p.media)}"><img loading="lazy" src="${media(state.job.id, p.media)}"></a><figcaption>${E(p.name)}<small>${p.size.join(" × ")}</small><a download="${E(p.name)}" href="${media(state.job.id, p.media)}">下载原图 ↓</a></figcaption></figure>`).join("")}</div></section>`
          : "";
      })
      .join(
        "",
      )}${m.gaps.length ? `<details class="card"><summary>素材缺项与未生成原因 · ${m.gaps.length}</summary>${m.gaps.map((g) => `<p>${E(products[g.product] || g.product)}：${E(g.reason)}</p>`).join("")}</details>` : ""}`;
  bindDownloads(v, m);
  $("#back-review").onclick = () => {
    state.output = false;
    renderJob();
  };
  $("#version").onchange = (e) => {
    state.selectedVersion = e.target.value;
    outputs();
  };
}
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
api("/session")
  .then((s) => (s.authenticated ? route() : showLogin()))
  .catch((e) => toast(e.message, true));
