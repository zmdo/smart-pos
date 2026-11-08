const E = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let items = [];
export async function loadFonts(api, force=false) {
  if (force || !items.length) items = await api('/fonts');
  return items;
}
export function fontOptions(selected='', inherit=true) {
  return (inherit ? '<option value="">跟随全局默认</option>' : '') + items
    .filter(f=>f.active || f.id===selected)
    .map(f=>`<option value="${E(f.id)}" ${f.id===selected?'selected':''} ${f.active?'':'disabled'}>${E(f.name)}${f.active?'':'（已停用）'}</option>`).join('');
}
export function fontSelect(path, selected='', name='') {
  return `<select class="font-select" aria-label="${E(path)} 字体" ${name?`name="${E(name)}"`:`data-font="${E(path)}"`}>${fontOptions(selected)}</select>`;
}
export function removeIndexedFonts(fonts, prefix, removed) {
  const result={};
  for (const [key,value] of Object.entries(fonts || {})) {
    if (!key.startsWith(prefix+'.')) {result[key]=value;continue;}
    const tail=key.slice(prefix.length+1), [index,...rest]=tail.split('.');
    const n=Number(index);
    if (n===removed) continue;
    result[[prefix,n>removed?n-1:n,...rest].join('.')]=value;
  }
  return result;
}
export async function fontLibrary({api,shell,toast}) {
  const catalog=await loadFonts(api,true);
  shell(`<section class="page-head"><span class="eyebrow">FONT LIBRARY</span><h1>字体库</h1><p>为案例选择一种声音。上传字体后，即可在审核文字旁使用。</p></section>
    <section class="card font-upload"><form id="upload-font"><label>字体名称（可选）<input name="name" maxlength="80" placeholder="使用字体自带名称"></label><label>字体文件<input name="font" type="file" accept=".ttf,.otf" required></label><button class="primary" type="submit">上传字体 ↑</button></form><p class="muted">支持 TTF / OTF，单个文件不超过 32 MB。英文专用字体适合 Before / After 等英文文案。</p></section>
    <div class="font-grid">${catalog.map(f=>`<article class="card font-card"><div class="font-card-head"><h2>${E(f.name)}</h2><span class="pill">${f.builtin?'预置字体':f.active?'已上传':'已停用'}</span></div><img loading="lazy" src="/api/fonts/${encodeURIComponent(f.id)}/preview" alt="${E(f.name)} 字体样张"><div class="font-card-foot"><small>${E(f.license)}</small>${f.builtin?`<a href="/api/fonts/${encodeURIComponent(f.id)}/license" target="_blank">字体许可 ↗</a>`:f.active?`<button data-disable-font="${E(f.id)}" class="quiet">停用</button>`:'<small>重新上传同一字体即可启用</small>'}</div></article>`).join('')}</div>
    <p class="muted">停用仅将字体移出新选择，历史审核和成品仍可使用。预置字体来自 <a href="https://github.com/google/fonts" target="_blank" rel="noreferrer">Google Fonts</a>。</p>`, 'fonts');
  document.querySelector('#upload-font').onsubmit=async event=>{
    event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
    try {
      const form=new FormData(event.target), payload=new FormData();
      payload.append('file',form.get('font'));payload.append('name',form.get('name'));
      await api('/fonts',{method:'POST',body:payload});toast('字体已加入图库');await fontLibrary({api,shell,toast});
    } catch(error) {toast(error.message,true);button.disabled=false;}
  };
  document.querySelectorAll('[data-disable-font]').forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    try {await api('/fonts/'+encodeURIComponent(button.dataset.disableFont),{method:'DELETE'});await fontLibrary({api,shell,toast});}
    catch(error){toast(error.message,true);button.disabled=false;}
  });
}
