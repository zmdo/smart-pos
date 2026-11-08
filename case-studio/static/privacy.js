const E = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const image = id => `/api/stickers/${encodeURIComponent(id)}/image`;
const fallback = {enabled:true, mask_back:false, mode:"ai", sticker_id:null, status:"unprepared", issues:[]};

export function privacyPanel(member) {
  const p = {...fallback, ...member.privacy};
  return `<div class="privacy-panel"><div class="privacy-heading"><strong>头部隐私保护</strong><p>同一会员使用同一张贴纸，背向头像默认关闭，可单独开启；保留原图已有的完整卡通遮挡。${member.render_settings?.mask_lifestyle?'生活照已开启头像遮挡。':'生活照不添加头像。'}${member.render_settings?.mask_training?'训练照已开启头像遮挡。':'训练照不添加头像。'}可在设置中分别调整。</p></div><div class="privacy-toggles" role="group" aria-label="头部遮挡选项"><label class="privacy-toggle"><input id="privacy-enabled" type="checkbox" ${p.enabled?"checked":""}><span>遮挡头部</span></label><label class="privacy-toggle"><input id="privacy-mask-back" type="checkbox" ${p.mask_back?"checked":""}><span>背向照片显示头像</span></label></div>
    <div class="privacy-controls"><div class="sticker-preview">${p.sticker_id?`<img src="${image(p.sticker_id)}" alt="本会员固定贴纸">`:'<span>待准备头像</span>'}</div><div class="privacy-options"><label>贴纸来源<select id="privacy-mode"><option value="ai" ${p.mode==="ai"?"selected":""}>AI 卡通头像</option><option value="library" ${p.mode==="library"?"selected":""}>贴纸库随机</option></select></label><div class="row-actions"><button type="button" id="privacy-prepare" class="outline-red">${p.status==="ready"?"重新检查头部":"准备头部遮挡"}</button><button type="button" id="privacy-regenerate">${p.mode==="ai"?"重新生成头像":"随机换一张"}</button>${p.mode==="library"?'<button type="button" id="privacy-pick">从图库选择</button>':''}</div><small>${E(p.avatar_source||"AI 头像带小巧装饰与自然表情；优先参考正面照，无参考时使用标准头像。")}</small></div></div>
    <p id="privacy-status" role="status" class="${p.status==="needs_review"?"error-text":"muted"}">${!p.enabled?"已关闭：新生成的成品将使用原照片。":p.status==="ready"?`已准备 · ${p.masked_faces||0} 处面部 · ${p.masked_back_heads||0} 处后脑/隐藏面部 · ${p.preserved_faces||0} 处已有贴纸保留`:p.status==="needs_review"?"部分头部检查需要重试，未检查照片不会直接输出。":"尚未准备。先检查头部并固定本会员的贴纸。"}</p>${p.avatar_issue?`<p class="muted">${E(p.avatar_issue)}</p>`:""}${(p.issues||[]).map(x=>`<p class="error-text">${E(x.asset_id)}：${E(x.reason)}</p>`).join("")}</div>`;
}

export function bindPrivacy({member, job, api, send, flush, version, apply, toast}) {
  const root = document.querySelector(".privacy-panel");
  let p = {...fallback, ...member.privacy};
  const url = `/jobs/${job}/members/${member.id}`;
  function busy(value, text) {
    root.querySelectorAll("button,input,select").forEach(e=>e.disabled=value);
    if(text) root.querySelector("#privacy-status").textContent=text;
  }
  async function save(values) {
    await flush();
    const result=await send(url,{version:version(),member:{privacy:{enabled:p.enabled,mask_back:p.mask_back,mode:p.mode,sticker_id:p.sticker_id,...values}}},"PATCH");
    p={...fallback,...result.members.find(x=>x.id===member.id).privacy};
    apply(result,false);
  }
  async function run(regenerate=false,rescan=false,resume=false) {
    busy(true,"正在检查头部、准备带装饰的透明头像，可离开页面，后台会继续处理…");
    try {
      if(!resume) {
        await flush();
        await send(url+"/privacy",{version:version(),regenerate,rescan});
      }
      for (;;) {
        await new Promise(r=>setTimeout(r,2000));
        const task=await api(url+"/privacy");
        if(task.status==="complete") {
          const review=await api(`/jobs/${job}/review`);
          apply(review,true); toast("头部遮挡准备完成，可更新预览或生成成品"); break;
        }
        if(task.status!=="running") throw new Error(task.error||"准备任务已中断，请重试；已生成的头像会复用");
        if(!root.isConnected) return;
      }
    } catch(e) { if(root.isConnected) {busy(false,e.message);toast(e.message,true);} }
  }
  root.querySelector("#privacy-enabled").onchange=async e=>{
    busy(true);
    try {await save({enabled:e.target.checked});apply(null,true);} catch(error){busy(false);toast(error.message,true);}
  };
  root.querySelector("#privacy-mask-back").onchange=async e=>{
    busy(true);
    try {await save({mask_back:e.target.checked});apply(null,true);} catch(error){busy(false);toast(error.message,true);}
  };
  root.querySelector("#privacy-mode").onchange=async e=>{
    busy(true);
    try {await save({mode:e.target.value,sticker_id:null});await run();}catch(error){busy(false);toast(error.message,true);}
  };
  root.querySelector("#privacy-prepare").onclick=()=>run(false,p.status!=="unprepared");
  root.querySelector("#privacy-regenerate").onclick=()=>run(true,false);
  const pick=root.querySelector("#privacy-pick");
  if(pick) pick.onclick=async()=>{
    try {await chooseSticker(api,member.profile.gender, async id=>{await save({sticker_id:id});if(p.status!=="ready")await run();else apply(null,true);});}
    catch(error){toast(error.message,true);}
  };
  // Resume a task after navigation/reload, without submitting another generation.
  api(url+"/privacy").then(async task=>{
    if(!root.isConnected)return;
    if(task.status==="running") await run(false,false,true);
  }).catch(()=>{});
}

function cards(items, choose=false) {
  return items.map(s=>`<${choose?"button":"article"} class="sticker-card" ${choose?`type="button" data-sticker="${E(s.id)}"`:""}><div><img loading="lazy" src="${image(s.id)}" alt="${E(s.name)}"></div><strong>${E(s.name)}</strong><small>${s.tags.map(E).join(" · ")}</small></${choose?"button":"article"}>`).join("");
}

export async function libraryPage({api,shell}) {
  const items=await api("/stickers");
  shell(`<section class="page-head"><span class="eyebrow">STICKER LIBRARY</span><h1>贴纸库</h1><p>${items.length} 张透明贴纸 · 按标签挑选，会员审核中可随机匹配或手动选择。</p></section><section class="card"><div class="sticker-filters"><input id="sticker-search" placeholder="搜索名称或标签，如：动物、开心、AI头像" aria-label="搜索贴纸"><select id="sticker-gender" aria-label="贴纸性别"><option value="">全部</option><option value="male">男性及通用</option><option value="female">女性及通用</option><option value="neutral">通用</option></select></div><div class="sticker-grid" id="sticker-grid">${cards(items)}</div><p class="muted sticker-credit">表情图形来自 <a href="https://github.com/jdecked/twemoji" target="_blank" rel="noreferrer">Twemoji</a>，按 CC BY 4.0 授权；标准卡通头像由 Qwen API 生成。</p></section>`,"stickers");
  function filter(){const q=document.querySelector("#sticker-search").value.toLowerCase(),g=document.querySelector("#sticker-gender").value;document.querySelector("#sticker-grid").innerHTML=cards(items.filter(s=>(!g||s.gender==="neutral"||s.gender===g)&&(s.name+" "+s.tags.join(" ")).toLowerCase().includes(q)));}
  document.querySelector("#sticker-search").oninput=filter;
  document.querySelector("#sticker-gender").onchange=filter;
}

async function chooseSticker(api,gender,select) {
  const g={"男":"male","女":"female"}[gender]||"neutral";
  const items=(await api("/stickers")).filter(s=>s.gender==="neutral"||s.gender===g);
  const modal=document.querySelector("#modal");
  modal.innerHTML=`<div class="modal-backdrop"><section class="sticker-dialog" role="dialog" aria-modal="true" aria-labelledby="sticker-title"><div class="section-title"><h2 id="sticker-title">选择本会员的贴纸</h2><button id="sticker-close" aria-label="关闭">×</button></div><p class="muted">本会员所有新增遮挡统一使用这一张贴纸。</p><div class="sticker-grid">${cards(items,true)}</div><p id="sticker-error" class="error-text"></p></section></div>`;
  document.body.classList.add("modal-open");
  const close=()=>{modal.innerHTML="";document.body.classList.remove("modal-open");};
  modal.querySelector("#sticker-close").onclick=close;
  modal.querySelectorAll("[data-sticker]").forEach(b=>b.onclick=async()=>{b.disabled=true;try{await select(b.dataset.sticker);close();}catch(e){modal.querySelector("#sticker-error").textContent=e.message;b.disabled=false;}});
}

export function imageSettings(c) {
  return `<section class="card"><div class="section-title"><span class="number">03</span><h2>AI 透明头像</h2></div><label>生图 API Base URL<input name="image_base_url" value="${E(c.base_url)}"></label><label>透明头像模型<select name="image_model">${["qwen-image-2.1-pro","qwen-image-2.1-turbo"].map(v=>`<option ${v===c.model?"selected":""}>${v}</option>`).join("")}</select></label><label class="check"><input name="image_reuse_key" type="checkbox" ${c.reuse_model_key?"checked":""}>共用同域视觉模型的 API Key</label><label>独立生图 Key${c.key_configured?" · 已配置，留空保留":""}<input name="image_api_key" type="password" autocomplete="new-password"></label><p class="muted">头像使用远程 API 生成，不额外占服务器 GPU 显存。每位会员生成一次并复用，主动重新生成时才更换。</p></section>`;
}
