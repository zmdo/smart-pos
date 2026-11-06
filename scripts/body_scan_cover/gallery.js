'use strict';
const DATA=JSON.parse(document.getElementById('cover-data').textContent);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let selected=DATA.cases.some(c=>c.group_id===location.hash.slice(1))?location.hash.slice(1):DATA.default_case;
let filter='all',query='';
const form=document.getElementById('copy-form');
function current(){return DATA.cases.find(c=>c.group_id===selected)}
function fillForm(c){
  for(const k of ['title','subtitle','headline','coach','story'])form.elements[k].value=c.copy[k]||'';
  form.elements.address.value=c.copy.address||'UP 健身私教馆';
  form.elements.highlights.value=c.copy.segments.filter(s=>s.emphasis).map(s=>s.text).join('\n');
  document.getElementById('edit-status').textContent='';
}
function show(c){
  if(!c)return;
  document.getElementById('member-heading').innerHTML=`<span>${esc(c.store)} /</span> ${esc(c.member)}`;
  const badge=document.getElementById('report-badge');badge.textContent=c.report_available?'体测数据已核验':'等待补充报告';badge.classList.toggle('ready',c.report_available);
  const im=document.getElementById('cover');im.src=c.file;im.alt=c.member+'会员案例封面';im.width=1080;im.height=1440;
  const download=document.getElementById('download');download.href=c.file;download.download=c.store+'-'+c.member+'-会员案例封面.jpg';
  const facts=[['体测报告',c.copy.report_id||'未匹配'],['教练',c.copy.coach||'未提供'],['照片状态',c.requires_review?'训练阶段待复核':'规则／人工标签'],['文案',c.copy.copy_origin==='user_override'?'用户自定义':'根据报告自动编写']];
  document.getElementById('facts').innerHTML=facts.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  document.getElementById('notes').innerHTML=c.notes.map(n=>`<p>${esc(n)}</p>`).join('');
  document.getElementById('framing').innerHTML=c.framing.map((f,i)=>`<p>${i?'训练后':'训练前'} · ${esc(c.asset_ids[i])}<br>${f.mode==='full_body_to_upper_body'?'全身照上半身取景':'可用上半身取景'} · 等比缩放 ${f.scale.toFixed(3)}<br>${f.head_already_incomplete?'输入头部已不完整':'保留输入头部'}</p>`).join('');
  fillForm(c);history.replaceState(null,'','#'+c.group_id);
}
function refresh(){
  const visible=DATA.cases.filter(c=>(filter==='all'||(filter==='report')===c.report_available)&&`${c.store} ${c.member}`.includes(query));
  if(visible.length&&!visible.some(c=>c.group_id===selected))selected=visible[0].group_id;
  const list=document.getElementById('case-list');list.innerHTML='';let store='';
  for(const c of visible){
    if(store!==c.store){const s=document.createElement('p');s.className='store-name';s.textContent=c.store;list.append(s);store=c.store}
    const b=document.createElement('button');b.className='case';b.setAttribute('aria-pressed',String(c.group_id===selected));
    b.innerHTML=`<span class="initial">${esc(c.member.slice(0,1))}</span><span><strong>${esc(c.member)}</strong><small>${c.report_available?'数据故事封面':'待补报告'}</small></span><span class="arrow">↗</span>`;
    b.onclick=()=>{selected=c.group_id;refresh()};list.append(b);
  }
  document.querySelector('.stage').hidden=!visible.length;
  document.getElementById('report-badge').hidden=!visible.length;
  if(!visible.length){list.textContent='没有匹配案例';document.getElementById('member-heading').textContent='没有匹配的会员，请调整筛选';}
  document.getElementById('total').textContent=visible.length+' / '+DATA.cases.length;
  for(const b of document.querySelectorAll('[data-filter]'))b.setAttribute('aria-pressed',String(b.dataset.filter===filter));
  if(visible.length)show(current());
}
document.getElementById('search').oninput=e=>{query=e.target.value.trim();refresh()};
for(const b of document.querySelectorAll('[data-filter]'))b.onclick=()=>{filter=b.dataset.filter;refresh()};
document.getElementById('reset').onclick=()=>fillForm(current());
form.onsubmit=e=>{
  e.preventDefault();const c=current(),values={};
  for(const k of ['title','subtitle','headline','coach','address','story'])values[k]=form.elements[k].value.trim();
  values.highlights=form.elements.highlights.value.split('\n').map(s=>s.trim()).filter(Boolean);
  const config={default_case:c.group_id,members:{[c.store+'/'+c.member]:values}};
  const url=URL.createObjectURL(new Blob([JSON.stringify(config,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=c.group_id+'-cover-config.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  document.getElementById('edit-status').textContent='配置已导出；重新生成后更新图片。当前预览尚未改动。';
};
const dialog=document.getElementById('lightbox');
document.getElementById('zoom').onclick=()=>{const c=current();document.getElementById('large-cover').src=c.file;document.getElementById('large-cover').alt=c.member+'封面';document.getElementById('dialog-title').textContent=c.store+' / '+c.member;dialog.showModal()};
document.getElementById('close').onclick=()=>dialog.close();
dialog.onclick=e=>{if(e.target===dialog)dialog.close()};
document.getElementById('gaps').innerHTML=DATA.gaps.map(g=>`<p>${esc(g.store)} / ${esc(g.member)}<br>${esc(g.reason)}</p>`).join('')||'全部已生成';
window.addEventListener('hashchange',()=>{if(DATA.cases.some(c=>c.group_id===location.hash.slice(1))){selected=location.hash.slice(1);filter='all';query='';document.getElementById('search').value='';refresh()}});
refresh();
