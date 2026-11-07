const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

export async function openCoverAI({
  api,
  send,
  job,
  member,
  getVersion,
  apply,
}) {
  let config = await api("/cover-ai/templates"),
    closed = false;
  const host = document.querySelector("#modal");
  const fields = config.fields,
    injections = config.injections;
  host.innerHTML = `<div class="modal-backdrop"><section class="ai-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-title"><div class="section-title"><div><span class="eyebrow">COVER COPYWRITER</span><h2 id="ai-title">AI 生成封面文案</h2><p>为 ${esc(member.profile.name)} 生成所选文字，已有其他内容保持不变。</p></div><button type="button" id="ai-close" aria-label="关闭 AI 面板">×</button></div><form id="ai-form"><fieldset><legend>生成哪些内容</legend><div class="ai-checks">${Object.entries(
    fields,
  )
    .map(
      ([key, title]) =>
        `<label class="check"><input type="checkbox" name="field" value="${key}">${title}</label>`,
    )
    .join(
      "",
    )}</div></fieldset><label>已保存的提示词模板<select id="ai-template"><option value="">默认提示词</option></select></label><label>生成提示词<textarea id="ai-prompt" rows="5" maxlength="6000"></textarea></label><fieldset><legend>注入当前会员的资料</legend><div class="ai-checks">${Object.entries(
    injections,
  )
    .map(
      ([key, title]) =>
        `<label class="check"><input type="checkbox" name="injection" value="${key}">${title}</label>`,
    )
    .join(
      "",
    )}</div><p class="muted">仅发送勾选的资料。未填写的性别或教练不会被编造；数据来自当前已保存的审核内容。</p></fieldset><details class="ai-template-save"><summary>保存与管理模板</summary><label>模板名称<input id="ai-template-name" maxlength="60" placeholder="例如：增肌成果 · 简洁版"></label><div class="row-actions"><button type="button" id="ai-save-new">另存为模板</button><button type="button" id="ai-save-existing" disabled>保存模板修改</button><button type="button" id="ai-delete" disabled>删除模板</button></div><p class="muted">模板保存提示词、字段和注入选项，不保存会员数据。</p></details><p id="ai-message" role="status"></p><div class="modal-actions"><button type="button" id="ai-cancel">取消</button><button class="primary" id="ai-generate" type="submit">生成并填入所选字段 ↗</button></div></form></section></div>`;
  document.body.classList.add("modal-open");
  const $ = (s) => host.querySelector(s),
    $$ = (s) => [...host.querySelectorAll(s)];
  const close = () => {
    closed = true;
    host.innerHTML = "";
    document.body.classList.remove("modal-open");
    window.removeEventListener("keydown", escape);
  };
  const escape = (e) => {
    if (e.key === "Escape") close();
  };
  window.addEventListener("keydown", escape);
  $("#ai-close").onclick = $("#ai-cancel").onclick = close;
  const message = (value, error = false) => {
    if (!closed) {
      $("#ai-message").textContent = value;
      $("#ai-message").className = error ? "error-text" : "muted";
    }
  };
  function fill(template) {
    $("#ai-prompt").value = template.prompt;
    $("#ai-template-name").value = template.name || "";
    $$("[name=field]").forEach(
      (e) => (e.checked = template.fields.includes(e.value)),
    );
    $$("[name=injection]").forEach(
      (e) => (e.checked = template.injections.includes(e.value)),
    );
    $("#ai-save-existing").disabled = $("#ai-delete").disabled = !template.id;
  }
  function list(selected = "") {
    $("#ai-template").innerHTML =
      '<option value="">默认提示词</option>' +
      config.templates
        .map((t) => `<option value="${t.id}">${esc(t.name)}</option>`)
        .join("");
    $("#ai-template").value = selected;
  }
  function values() {
    return {
      prompt: $("#ai-prompt").value,
      fields: $$("[name=field]:checked").map((e) => e.value),
      injections: $$("[name=injection]:checked").map((e) => e.value),
    };
  }
  list();
  fill(config.defaults);
  $("#ai-template").onchange = () =>
    fill(
      config.templates.find((t) => t.id === $("#ai-template").value) ||
        config.defaults,
    );
  async function save(existing) {
    try {
      const id = existing ? $("#ai-template").value : "";
      const saved = await send(
        "/cover-ai/templates" + (id ? "/" + id : ""),
        { ...values(), name: $("#ai-template-name").value },
        id ? "PUT" : "POST",
      );
      config = await api("/cover-ai/templates");
      if (closed) return;
      list(saved.id);
      fill(saved);
      message("模板已保存，可用于其他会员。");
    } catch (e) {
      message(e.message, true);
    }
  }
  $("#ai-save-new").onclick = () => save(false);
  $("#ai-save-existing").onclick = () => save(true);
  $("#ai-delete").onclick = async () => {
    try {
      const id = $("#ai-template").value;
      await api("/cover-ai/templates/" + id, { method: "DELETE" });
      config = await api("/cover-ai/templates");
      if (closed) return;
      list();
      fill(config.defaults);
      message("模板已删除。");
    } catch (e) {
      message(e.message, true);
    }
  };
  $("#ai-form").onsubmit = async (e) => {
    e.preventDefault();
    const input = values();
    if (!input.fields.length || !input.prompt.trim())
      return message("请选择生成项并填写提示词。", true);
    const controls = $$(
      "input, textarea, select, #ai-generate, #ai-save-new, #ai-save-existing, #ai-delete",
    );
    const disabled = controls.map((c) => c.disabled);
    controls.forEach((c) => (c.disabled = true));
    $("#ai-generate").textContent = "正在生成…";
    message("正在根据所选资料生成，关闭面板可放弃本次回填。");
    try {
      const result = await send(`/jobs/${job}/members/${member.id}/cover-ai`, {
        ...input,
        version: getVersion(),
      });
      if (closed) return;
      await apply(result);
      close();
    } catch (error) {
      message(error.message, true);
    } finally {
      if (!closed) {
        controls.forEach((c, i) => (c.disabled = disabled[i]));
        $("#ai-generate").textContent = "生成并填入所选字段 ↗";
      }
    }
  };
}
