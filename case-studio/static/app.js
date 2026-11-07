import { openCrop } from "./crop.js";
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
  saving: null,
};
let timer,
  poll,
  previewSeq = 0;
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
const products = {
  three_views: "完整三视图",
  vs: "同朝向对比图",
  single: "朝向单图",
  cover: "会员案例封面",
  report: "体测报告对比",
  training: "会员训练日常",
  testimonial: "会员感言",
  life: "会员生活照",
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
    showLogin();
  };
}
function showLogin() {
  clearInterval(poll);
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
    state.page = ["history", "settings"].includes(page) ? page : "home";
    state.job = null;
    state.review = null;
    state.output = false;
    if (page === "job" && jid) {
      await openJob(jid);
      return;
    }
    if (state.page === "settings") await settings();
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
async function settings() {
  const c = await api("/settings");
  shell(
    `<section class="page-head"><span class="eyebrow">PREFERENCES</span><h1>工作台设置</h1><p>新上传批次使用这里的默认设置，已有审核内容保持独立。</p></section><form id="settings" class="settings-grid"><section class="card"><div class="section-title"><span class="number">01</span><h2>品牌与成品</h2></div>${input("品牌名称", "brand_name", c.brand_name)}${input("默认地址", "address", c.address)}${input("案例说明", "consent_text", c.consent_text)}<div class="field-grid">${input("对比图宽度（像素）", "width", c.width, "number")}${input("标准照片宽度", "display_width", c.display_width, "number")}</div><div class="field-grid">${input("训练前文字", "before_text", c.before_text)}${input("训练后文字", "after_text", c.after_text)}</div>${input("中央文字", "vs_text", c.vs_text)}<div class="field-grid three">${Object.entries(
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
      )}</div><label>默认 Logo <input id="logo" type="file" accept="image/png,image/jpeg,image/webp"></label><p class="muted">${c.logo_configured ? "已配置默认 Logo。" : "尚未设置 Logo，默认显示品牌文字。"}上传包内的 logo 目录优先使用。</p></section><section class="card"><div class="section-title"><span class="number">02</span><h2>视觉模型</h2></div>${input("兼容接口 Base URL", "base_url", c.model.base_url)}${input("模型名", "model", c.model.model)}${input(c.model.key_configured ? "API Key · 已配置，留空保留" : "API Key", "api_key", "", "password")}${input("模型并发数（1–4）", "model_workers", c.model_workers, "number")}<div class="info-panel">照片校正与人物检测在远程 GPU 服务器运行；视觉模型用于分类与语义判断。审核预览和成品生成复用既有结果。</div><button class="primary" type="submit">保存设置 <span>↗</span></button><p class="muted">API Key 仅保存在服务端，不会返回浏览器。</p></section></form>`,
  );
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
    for (const k of ["width", "display_width", "model_workers"])
      body[k] = Number(v[k]);
    body.titles = {
      front: v.title_front,
      side: v.title_side,
      back: v.title_back,
    };
    body.model = { base_url: v.base_url, model: v.model, api_key: v.api_key };
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
  return `<label>${E(label)}<input type="${type}" name="${E(name)}" value="${E(value)}" autocomplete="${type === "password" ? "new-password" : "off"}"></label>`;
}
async function openJob(jid) {
  state.job = await api("/jobs/" + jid);
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
  try {
    const j = await api("/jobs/" + state.job.id);
    const changed =
      j.status !== state.job.status ||
      j.review_version !== state.job.review_version;
    state.job = j;
    if (changed && !state.dirty && !state.saving) {
      if (j.review_version && !state.review) {
        state.review = await api(`/jobs/${j.id}/review`);
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
  return `<section class="card progress-card"><span class="eyebrow">PREPARING YOUR MATERIALS</span><h2>${j.status === "failed" ? "处理暂时中断" : "正在整理这一批改变"}</h2><p class="muted">可以离开页面，处理会在服务器继续。完成后进入人工审核。</p><div class="progress-large"><b id="progress-number">${j.progress}%</b><progress max="100" value="${j.progress}"></progress></div><div id="nodes">${nodes(j)}</div>${j.error ? `<div class="error-panel">${E(j.error)}<button id="retry">重试未完成节点</button></div>` : ""}</section>`;
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
function field(label, path, value, area = false) {
  return `<label>${E(label)}${area ? `<textarea data-field="${path}" rows="4">${E(value)}</textarea>` : `<input data-field="${path}" value="${E(value)}">`}</label>`;
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
  `<div class="field-grid three">${field("会员姓名", "profile.name", m.profile.name)}<label>会员性别<select data-field="profile.gender">${[
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
    )}</select></label>${field("教练姓名", "profile.coach", m.profile.coach)}</div>`,
)}
${section("02", "体测图训练阶段", "拖动照片调整前后顺序；同朝向多张时，可选择首选图用于对比与封面。", `<div class="phase-boards" id="boards"></div><div class="row-actions"><button id="confirm-photos">确认本会员所有阶段标记</button><span class="muted">推断与待审结果会保留在下载包的审核说明中。</span></div>`)}
${section(
  "03",
  "审核同朝向对比图",
  "所有文字都可编辑。保存后使用实际成品渲染器更新预览。",
  `<div class="edit-with-preview"><div><div class="field-grid">${field("会员称呼", "vs.nickname", m.vs.nickname)}${field("品牌名称", "vs.brand_name", m.vs.brand_name)}</div>${field("地址", "vs.address", m.vs.address)}${field("案例说明", "vs.consent_text", m.vs.consent_text)}<div class="field-grid three">${field("训练前", "vs.before_text", m.vs.before_text)}${field("训练后", "vs.after_text", m.vs.after_text)}${field("中央文字", "vs.vs_text", m.vs.vs_text)}</div><div class="field-grid three">${Object.keys(
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
${section("04", "审核会员案例封面", "封面独立取景：从正面原图选取头部至胯部，保持人物比例。", `<div class="edit-with-preview"><div><div class="field-grid">${field("主标题", "cover.title", m.cover.title)}${field("角标", "cover.badge", m.cover.badge)}</div>${field("副标题", "cover.subtitle", m.cover.subtitle)}${field("成果标题", "cover.headline", m.cover.headline)}${field("内容介绍", "cover.story", m.cover.story, true)}<div class="field-grid">${field("品牌名称", "cover.brand_name", m.cover.brand_name)}${field("地址", "cover.address", m.cover.address)}</div>${field("地址第二行 / 门店", "cover.store_text", m.cover.store_text)}<button id="crop" class="outline-red">调整左右照片取景 ↗</button><p class="muted">也可点击右侧封面。左右取景框独立调整，可即时查看组合效果。</p></div><div class="preview-pane cover-preview" id="cover-preview"><div class="empty">正在准备封面预览…</div></div></div>`)}
${section("05", "审核体测对比表", "原始体测数据优先，汇总表补充缺项。可修改五列内容、增加或删除行。", `<div class="field-grid">${field("表格标题", "table.table_title", m.table.table_title)}${field("报告标题", "table.report_title", m.table.report_title)}</div><div class="field-grid">${field("报告左标签", "table.before_label", m.table.before_label)}${field("报告右标签", "table.after_label", m.table.after_label)}</div><div id="table-editor" class="table-scroll"></div><button id="add-row" class="small">＋ 增加一行</button><div class="table-preview" id="table-preview"></div>`)}
<details class="card sources"><summary>查看原始素材分类与跳过信息 · ${m.sources.length} 张</summary><div class="source-grid">${m.sources.map((s) => `<figure><a href="${media(j.id, s.media)}" target="_blank"><img loading="lazy" src="${media(j.id, s.media)}"></a><figcaption><b>${kinds[s.kind] || s.kind}</b><small>${E(s.reason)}</small></figcaption></figure>`).join("")}</div><div id="gaps"></div></details><div class="review-bottom"><div><b>确认这一批案例</b><small>共 ${state.review.members.length} 位会员 · 可以保留待审标记生成，之后再修正</small></div><button id="generate" class="primary" ${["queued", "processing", "generating"].includes(j.status) ? "disabled" : ""}>${j.status === "generating" ? "正在生成…" : "生成整批成品"} ↗</button></div>`;
  renderBoards();
  renderMetrics();
  renderTable();
  $$("[data-field]").forEach(
    (el) =>
      (el.oninput = () => {
        const parts = el.dataset.field.split(".");
        let obj = m;
        for (const p of parts.slice(0, -1)) obj = obj[p];
        obj[parts.at(-1)] = el.value;
        dirty();
        if (parts[0] === "profile") sidebar();
      }),
  );
  $("#confirm-photos").onclick = () => {
    m.photos.forEach((p) => (p.confirmed = true));
    dirty();
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
    dirty();
  };
  $("#add-metric").onclick = () => {
    if (m.vs.metrics.length >= 6) return toast("最多 6 项", true);
    m.vs.metrics.push({ text: "", key: "custom" });
    renderMetrics();
    dirty();
  };
  $("#crop").onclick = crop;
  $("#generate").onclick = generate;
  $("#regen") && ($("#regen").onclick = generate);
  loadPreview();
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
        dirty();
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
        dirty();
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
  dirty();
}
function renderMetrics() {
  $("#metrics").innerHTML = member()
    .vs.metrics.map(
      (m, i) =>
        `<div class="metric-row"><input data-metric="${i}" value="${E(m.text)}"><button data-remove-metric="${i}" aria-label="删除指标">×</button></div>`,
    )
    .join("");
  $$("[data-metric]").forEach(
    (el) =>
      (el.oninput = () => {
        member().vs.metrics[el.dataset.metric].text = el.value;
        dirty();
      }),
  );
  $$("[data-remove-metric]").forEach(
    (el) =>
      (el.onclick = () => {
        member().vs.metrics.splice(+el.dataset.removeMetric, 1);
        renderMetrics();
        dirty();
      }),
  );
}
function renderTable() {
  const t = member().table;
  $("#table-editor").innerHTML =
    `<table class="edit-table"><thead><tr>${t.headers.map((v, i) => `<th><input data-header="${i}" value="${E(v)}"></th>`).join("")}<th></th></tr></thead><tbody>${t.rows.map((r, i) => `<tr>${["type", "before", "after", "delta", "unit"].map((k) => `<td><input data-cell="${i}:${k}" value="${E(r[k])}" aria-label="${E(r.type)} ${k}"></td>`).join("")}<td><button data-remove-row="${i}" title="删除行">×</button></td></tr>`).join("")}</tbody></table>`;
  $$("[data-cell]").forEach(
    (el) =>
      (el.oninput = () => {
        const [i, k] = el.dataset.cell.split(":");
        t.rows[i][k] = el.value;
        dirty();
      }),
  );
  $$("[data-header]").forEach(
    (el) =>
      (el.oninput = () => {
        t.headers[el.dataset.header] = el.value;
        dirty();
      }),
  );
  $$("[data-remove-row]").forEach(
    (b) =>
      (b.onclick = () => {
        t.rows.splice(+b.dataset.removeRow, 1);
        renderTable();
        dirty();
      }),
  );
}
let saveTimer;
function dirty() {
  state.dirty = true;
  $("#save-status") && ($("#save-status").textContent = "尚未保存…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(
    () =>
      flush()
        .then(() => loadPreview())
        .catch((e) => toast(e.message, true)),
    800,
  );
}
async function flush() {
  clearTimeout(saveTimer);
  if (state.saving) await state.saving;
  if (!state.dirty || !state.review) return;
  const m = member(),
    stamp = JSON.stringify(m);
  const payload = {
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
  };
  state.saving = send(
    `/jobs/${state.job.id}/members/${m.id}`,
    { version: state.review.version, member: payload },
    "PATCH",
  );
  try {
    const r = await state.saving;
    state.review.version = r.version;
    state.job.review_version = r.version;
    if (JSON.stringify(m) === stamp) {
      state.dirty = false;
      const updated = r.members.find((x) => x.id === m.id);
      Object.assign(m, updated);
      $("#save-status") && ($("#save-status").textContent = "所有修改已保存");
      $$('[data-field="vs.nickname"]').forEach(
        (e) => (e.value = m.vs.nickname),
      );
    }
    sidebar();
  } finally {
    state.saving = null;
  }
  if (state.dirty) await flush();
}
async function loadPreview(strict = false) {
  if (state.output || !state.review) return;
  const mid = state.member,
    seq = ++previewSeq;
  try {
    await flush();
    const p = await send(`/jobs/${state.job.id}/preview/${mid}`, {
      version: state.review.version,
    });
    if (mid !== state.member || seq !== previewSeq || state.output) return;
    state.preview = p;
    const vs = p.products.filter((p) => p.kind === "vs");
    $("#vs-preview").innerHTML = vs.length
      ? `<div class="preview-tabs">${vs.map((v, i) => `<button data-vstab="${i}" class="${i === 0 ? "active" : ""}">${E(v.name.replace("对比图.jpg", ""))}</button>`).join("")}</div><img id="vs-image" src="${media(state.job.id, vs[0].media)}">`
      : '<div class="empty">需要同朝向的训练前后照片，才能生成对比图。</div>';
    $$("[data-vstab]").forEach(
      (b) =>
        (b.onclick = () => {
          $("#vs-image").src = media(state.job.id, vs[+b.dataset.vstab].media);
          $$("[data-vstab]").forEach((x) =>
            x.classList.toggle("active", x === b),
          );
        }),
    );
    const cover = p.products.find((p) => p.kind === "cover");
    $("#cover-preview").innerHTML = cover
      ? `<button class="image-button" id="open-cover"><img src="${media(state.job.id, cover.media)}"><span>点击调整照片取景 ↗</span></button>`
      : '<div class="empty">暂无可用封面。需要正面前后配对和可靠的肩胯标定。</div>';
    $("#open-cover") && ($("#open-cover").onclick = crop);
    const table = p.products.find((p) => p.kind === "report");
    $("#table-preview").innerHTML = table
      ? `<img loading="lazy" src="${media(state.job.id, table.media)}">`
      : '<p class="muted">没有表格数据时，不生成体测报告成品。</p>';
    $("#gaps").innerHTML = p.gaps.length
      ? `<h3>暂未生成的项目</h3>${p.gaps.map((g) => `<p class="muted">${E(products[g.product] || g.product)}：${E(g.reason)}</p>`).join("")}`
      : "所有可用素材已纳入成品。";
  } catch (e) {
    if (mid === state.member && seq === previewSeq) {
      toast(e.message, true);
      $("#save-status") &&
        ($("#save-status").textContent = "预览未更新，请检查后重试");
      $("#vs-preview") &&
        ($("#vs-preview").innerHTML =
          `<div class="empty">${E(e.message)}<button id="retry-preview">重试预览</button></div>`);
      $("#retry-preview") && ($("#retry-preview").onclick = loadPreview);
    }
    if (strict === true) throw e;
  }
}
async function crop() {
  try {
    await flush();
    if (!state.preview) await loadPreview();
    const ids = state.preview?.cover_sources?.map((c) => c.asset_id) || [];
    const m = member();
    let pics = ids.map((id) => m.photos.find((p) => p.asset_id === id));
    if (pics.length !== 2) {
      pics = ["before", "after"].map((phase) =>
        m.photos.find(
          (p) => p.phase === phase && p.view === "front" && p.cover_media,
        ),
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
        dirty();
        await flush();
        await loadPreview(true);
      },
      state.preview?.products.find((p) => p.kind === "cover")
        ? media(
            state.job.id,
            state.preview.products.find((p) => p.kind === "cover").media,
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
    `<div class="review-heading"><div><span class="eyebrow">READY TO SHARE</span><h2>${E(m.profile.name)}的成品</h2><p class="muted">${m.products.length} 张成品 · ${formatDate(v.created_at)} · 审核版本 ${v.review_version}</p></div><button id="back-review">返回审核 ↶</button></div><div class="download-bar"><div><b>案例成品已就绪</b><small>${m.review_required.length ? "有 " + m.review_required.length + " 张阶段标记仍需核对，审核说明已随包附带。" : "本会员的阶段标记已确认。"}</small></div><a class="button" href="/api/jobs/${state.job.id}/download/${encodeURIComponent(v.id)}?member=${m.member_id}">下载本会员 ZIP ↓</a><a class="button primary" href="/api/jobs/${state.job.id}/download/${encodeURIComponent(v.id)}">整批打包下载 ↓</a></div><div class="version-bar"><label>成品版本 <select id="version">${state.versions.map((x) => `<option value="${E(x.id)}" ${x.id === v.id ? "selected" : ""}>${formatDate(x.created_at)} · 审核 v${x.review_version}</option>`).join("")}</select></label><span class="muted">修改审核内容后，生成新的成品版本。</span></div>${Object.entries(
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
