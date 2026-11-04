const $ = (id) => document.getElementById(id);
let file = null, current = null, timer = null;

const statusText = {queued:"排队中", running:"处理中", completed:"已完成", failed:"失败", interrupted:"已中断"};

function toast(msg){ const d=$("err"); d.textContent=msg; d.classList.remove("hidden"); clearTimeout(d.t); d.t=setTimeout(()=>d.classList.add("hidden"),5000); }

async function api(url, opts={}){
  const r = await fetch(url, opts);
  let v; try{ v = await r.json(); }catch{ v = {detail:"响应异常"}; }
  if(r.status===401 && !url.endsWith("/login")){ $("loginDialog").showModal(); throw new Error("请先输入访问令牌"); }
  if(!r.ok) throw new Error(typeof v.detail==="string"?v.detail:"请求失败");
  return v;
}

$("loginForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  try{
    await api("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:$("token").value.trim()})});
    $("loginDialog").close(); $("who").textContent="已登录"; init();
  }catch(err){ $("loginErr").textContent=err.message; }
});

$("drop").onclick = ()=>$("file").click();
$("file").onchange = (e)=>pick(e.target.files[0]);
["dragover","dragenter"].forEach(ev=>$("drop").addEventListener(ev,e=>{e.preventDefault();$("drop").classList.add("drag")}));
["dragleave","drop"].forEach(ev=>$("drop").addEventListener(ev,e=>{e.preventDefault();$("drop").classList.remove("drag")}));
$("drop").addEventListener("drop",e=>pick(e.dataTransfer.files[0]));

function pick(f){ if(!f) return; file=f; $("fileName").textContent=f.name+" · "+(f.size/1024/1024).toFixed(1)+" MB"; $("startBtn").disabled=false; }

$("startBtn").onclick = async ()=>{
  if(!file) return;
  $("startBtn").disabled=true; $("startBtn").textContent="上传中…";
  try{
    const fd=new FormData(); fd.append("archive",file); fd.append("mode","dryrun");
    const r=await fetch("/api/batches",{method:"POST",body:fd});
    const j=await r.json();
    if(!r.ok) throw new Error(j.detail||"上传失败");
    $("startBtn").textContent="开始体检"; open(j.id);
  }catch(e){ toast(e.message); $("startBtn").disabled=false; $("startBtn").textContent="开始体检"; }
};

async function open(id){ current=id; clearTimeout(timer); $("jobPanel").classList.remove("hidden"); await poll(); }

async function poll(){
  const id=current; if(!id) return;
  try{
    const j=await api("/api/batches/"+id);
    renderJob(j);
    if(["queued","running"].includes(j.status)) timer=setTimeout(poll,1800);
    else renderResult(j);
  }catch(e){ toast(e.message); }
}

function renderJob(j){
  $("jobTitle").textContent=j.name; $("jobBadge").textContent=statusText[j.status]||j.status;
  $("stage").textContent=j.stage||"";
  const total=j.total_images||j.total_files||0, done=j.processed||j.classified||0;
  $("bar").style.width=total?Math.min(100,done/total*100)+"%":"8%";
  const s=j.summary||{};
  $("stats").innerHTML=[["会员",s.members],["图片",s.images],["重复",s.duplicates],["低质",s.dropped],["可出成品",s.outputs_possible],["缺口",s.gaps]]
    .filter(([,v])=>v!=null).map(([k,v])=>`<span>${k}<b>${v}</b></span>`).join("");
  $("err").classList.toggle("hidden",!j.error); if(j.error) $("err").textContent=j.error;
}

function renderResult(j){
  const root=$("results"); root.innerHTML="";
  if(!j.members){ return; }
  const head=document.createElement("div");
  head.className="panel-head";
  head.innerHTML=`<h2>2 · 体检结果</h2><a class="hint" href="/api/batches/${j.id}/report.md" target="_blank">查看报告.md</a>`;
  root.appendChild(head);
  const byStore={};
  j.members.forEach(m=>{ (byStore[m.store]=byStore[m.store]||[]).push(m); });
  const assetsById={}; (j.assets||[]).forEach(a=>assetsById[a.id]=a);
  const memberAssets={}; (j.assets||[]).forEach(a=>{ const k=a.store+"|"+a.member; (memberAssets[k]=memberAssets[k]||[]).push(a); });
  Object.keys(byStore).sort().forEach(store=>{
    byStore[store].forEach(m=>{
      const el=document.createElement("article"); el.className="member";
      const outs=m.outputs.filter(o=>o.ok).map(o=>o.label);
      const c=m.counts;
      el.innerHTML=`<h3>${store} · ${esc(m.name)}</h3>
        <div class="sub">能出 <b>${m.produced_count}</b> 张 · 缺口 ${m.gaps.length} 项 · 待确认 ${m.review.length} 项${m.facts.warnings.length?" · ⚠️ 数据校验 "+m.facts.warnings.length+" 条":""}</div>
        <div class="kv">
          <span>体测图<b>${c.body_scan}</b></span><span>体测报告<b>${c.body_report}</b></span>
          <span>成果报告<b>${c.training_report}</b></span><span>训练图<b>${c.daily_training}</b></span>
          <span>生活照<b>${c.life_photo}</b></span><span>感言<b>${c.testimonial}</b></span>
          ${c.video_deferred?`<span>视频(跳过)<b>${c.video_deferred}</b></span>`:""}
        </div>
        <div class="outs"><b class="ok">可出：</b>${outs.length?outs.join("、"):"—"}</div>
        ${m.gaps.length?`<ul class="gaps">${m.gaps.map(g=>`<li><b>${esc(g.label)}</b> — ${esc(g.reason)}</li>`).join("")}</ul>`:""}
        ${m.review.length?`<ul class="review">${m.review.map(r=>`<li>待确认：${esc(r.id)} ${esc(r.reason)}</li>`).join("")}</ul>`:""}
        ${m.facts.warnings.length?`<ul class="review">${m.facts.warnings.map(w=>`<li>⚠️ ${esc(w)}</li>`).join("")}</ul>`:""}
        <div class="asset-grid">${(memberAssets[store+"|"+m.name]||[]).filter(a=>a.thumb).slice(0,18)
          .map(a=>`<div class="asset"><img loading="lazy" src="/api/batches/${j.id}/thumb/${a.id}"><i>${esc(kindShort(a.class))}</i></div>`).join("")}</div>`;
      root.appendChild(el);
    });
  });
}

function kindShort(c){
  if(!c) return "?";
  const map={body_scan:"体测",body_report:"体测报告",training_report:"成果报告",daily_training:"训练",life_photo:"生活照",testimonial:"感言",other:"其他",unknown:"未知"};
  const v=c.view?({front:"正",side:"侧",side_left:"侧左",side_right:"侧右",back:"背"}[c.view]||""):"";
  const bg=c.background?({grid_board:"网格",white_wall:"白墙",wood:"木墙",mirror:"镜面",outdoor:"户外",other:"其他"}[c.background]||""):"";
  const split=(c.phase==="both")?"·对比图":"";
  return (map[c.kind]||c.kind)+(v?("·"+v):"")+(bg?("/"+bg):"")+split;
}
function esc(s){ return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

$("historyBtn").onclick = async ()=>{
  try{
    const list=await api("/api/batches");
    $("historyList").innerHTML=list.length?list.map(b=>`<div class="hlist"><b>${esc(b.name)}</b><span class="grow">${statusText[b.status]||b.status} · ${b.summary?("可出"+b.summary.outputs_possible+"张"):""}</span><button class="ghost" data-id="${b.id}">查看</button></div>`).join(""):"暂无记录";
    $("historyList").querySelectorAll("[data-id]").forEach(btn=>btn.onclick=()=>{$("historyDialog").close();open(btn.dataset.id)});
    $("historyDialog").showModal();
  }catch(e){ toast(e.message); }
};
$("closeHist").onclick=()=>$("historyDialog").close();

(async function init(){
  const hash=new URLSearchParams(location.hash.slice(1));
  const tk=hash.get("token");
  if(tk){
    history.replaceState(null,"",location.pathname+location.search);
    try{ await api("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:tk})}); }catch(e){}
  }
  try{ await api("/api/batches"); $("who").textContent="已登录"; }
  catch{ $("loginDialog").showModal(); }
  const id=new URLSearchParams(location.search).get("batch"); if(id) open(id);
})();
