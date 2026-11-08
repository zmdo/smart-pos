import { imageURL } from './media-cache.js';
import { movedPosition, stickerRect, editorEdits } from './mask-editor-model.js';
const E=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const views={front:'正面',side:'侧面',side_left:'左侧',side_right:'右侧',back:'背面'};
const label=scope=>scope.startsWith('three_views:')?'完整六图':scope.startsWith('cover:')?'会员案例封面':(views[scope.split(':')[1]]||'')+'对比图';

export async function openMaskEditor({job,member,section,version,send,onSave}) {
  const host=document.querySelector('#modal');
  let closed=false,saving=false,manifest,sticker;
  host.innerHTML=`<div class="modal-backdrop"><section class="mask-dialog" role="dialog" aria-modal="true" aria-labelledby="mask-title"><div class="section-title"><div><span class="eyebrow">AVATAR PLACEMENT</span><h2 id="mask-title">调整面部遮罩</h2><p>拖动头像调整位置，或使用方向按钮微调。每张照片独立保存，可删除或恢复。六图编辑聚焦头肩，点击照片选择头像。</p></div><button id="mask-close" aria-label="关闭面部遮罩调整">×</button></div><p class="muted">${E(member.profile.name)} · 只调整系统添加的头像，原图已有贴纸保持原样。</p><p id="mask-loading" role="status">正在准备取景照片和头像位置…</p><div id="mask-tabs" class="preview-tabs" role="tablist" aria-label="遮罩成品类型"></div><div id="mask-groups"></div><p id="mask-error" class="error-text" role="alert"></p><div class="modal-actions"><button id="mask-cancel">取消</button><button id="mask-save" class="primary" disabled>应用并更新展示效果 ↗</button></div></section></div>`;
  document.body.classList.add('modal-open');
  const dialog=host.querySelector('.mask-dialog');
  const close=()=>{if(saving)return;closed=true;host.innerHTML='';document.body.classList.remove('modal-open');window.removeEventListener('keydown',key);};
  const key=e=>{
    if(e.key==='Escape'){e.preventDefault();close();}
    if(e.key==='Tab'){
      const items=[...dialog.querySelectorAll('button:not(:disabled),select:not(:disabled),canvas')].filter(el=>el.getClientRects().length);
      const first=items[0],last=items.at(-1);
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
    }
  };
  window.addEventListener('keydown',key);
  host.querySelector('#mask-close').onclick=host.querySelector('#mask-cancel').onclick=close;
  host.querySelector('#mask-close').focus();
  try {
    manifest=await send(`/jobs/${job}/members/${member.id}/mask-editor`,{version,section});
    if(closed)return;
    const media=id=>`/api/jobs/${job}/media/${id}`;
    async function load(id){const im=new Image();im.src=await imageURL(media(id));await im.decode();return im;}
    const panels=manifest.groups.flatMap(g=>g.panels);
    const images=await Promise.all([load(manifest.sticker_media),...panels.map(p=>load(p.media))]);
    if(closed)return;
    sticker=images.shift();panels.forEach((p,i)=>p.image=images[i]);
    host.querySelector('#mask-loading').hidden=true;
    host.querySelector('#mask-tabs').innerHTML=manifest.groups.map((g,i)=>`<button role="tab" id="mask-tab-${i}" aria-controls="mask-group-${i}" aria-selected="${i===0}" data-mask-tab="${i}" class="${i===0?'active':''}">${E(label(g.scope))}</button>`).join('');
    host.querySelector('#mask-groups').innerHTML=manifest.groups.map((g,i)=>`<div role="tabpanel" aria-labelledby="mask-tab-${i}" id="mask-group-${i}" class="mask-grid ${g.scope.startsWith('three_views:')?'six':''}" ${i?'hidden':''}>${g.panels.map((p,j)=>`<article class="mask-card" id="mask-card-${i}-${j}"><h3>${p.phase==='before'?'训练前':'训练后'} · ${E(views[p.view]||p.view)}</h3><canvas tabindex="0" aria-label="${p.phase==='before'?'训练前':'训练后'}${E(views[p.view]||p.view)}头像位置"></canvas><div class="mask-tools"><label>头像<select aria-label="选择头像">${p.faces.map((f,k)=>`<option value="${k}">${f.shared?'主体头像':'背景人物 '+(k+1)}</option>`).join('')}</select></label><p class="mask-note muted" role="status"></p><div class="mask-nudges"><button data-dx="-1" aria-label="头像向左">←</button><button data-dy="-1" aria-label="头像向上">↑</button><button data-dy="1" aria-label="头像向下">↓</button><button data-dx="1" aria-label="头像向右">→</button></div><div class="row-actions"><button data-delete>删除此头像</button><button data-reset>恢复自动位置</button>${g.scope.startsWith('three_views:')?'<button data-full>查看全图</button>':''}</div></div></article>`).join('')}</div>`).join('');
    if(!manifest.groups.length)host.querySelector('#mask-groups').innerHTML='<p class="empty">当前没有可用的成品配对。完整六图需要训练前后各一组正面、侧面、背面照片。</p>';
    manifest.groups.forEach((g,i)=>g.panels.forEach((p,j)=>bindPanel(p,host.querySelector(`#mask-card-${i}-${j}`),g.scope.startsWith('three_views:'),j===0)));
    host.querySelectorAll('[data-mask-tab]').forEach(b=>b.onclick=()=>{
      host.querySelectorAll('[data-mask-tab]').forEach(el=>{const active=el===b;el.classList.toggle('active',active);el.setAttribute('aria-selected',String(active));});
      manifest.groups.forEach((_,i)=>host.querySelector(`#mask-group-${i}`).hidden=i!==Number(b.dataset.maskTab));
    });
    host.querySelector('#mask-save').disabled=!panels.some(p=>p.faces.length);
    host.querySelector('#mask-save').onclick=async()=>{
      saving=true;dialog.querySelectorAll('button,select').forEach(b=>b.disabled=true);
      host.querySelector('#mask-save').textContent='正在保存…';
      try{
        const result=await send(`/jobs/${job}/members/${member.id}/mask-editor`,{version:manifest.version,section,fingerprint:manifest.fingerprint,edits:editorEdits(manifest.groups)},'PATCH');
        await onSave(result);saving=false;close();
      }catch(e){saving=false;host.querySelector('#mask-error').textContent=e.message;dialog.querySelectorAll('button,select').forEach(b=>b.disabled=false);host.querySelector('#mask-save').textContent='应用并更新展示效果 ↗';}
    };
  }catch(e){if(!closed){host.querySelector('#mask-loading').hidden=true;host.querySelector('#mask-error').textContent=e.message;}}

  function bindPanel(p,card,compact=false,first=false){
    const canvas=card.querySelector('canvas'),c=canvas.getContext('2d'),select=card.querySelector('select');
    let scale,top=0,viewHeight=p.size[1],full=!compact;
    if(compact&&first)card.classList.add('selected');
    function viewport(){
      top=full?0:Math.max(0,Math.min(...p.faces.map(f=>f.default_rect[1]),p.size[1]*.1)-p.size[0]*.08);
      viewHeight=full?p.size[1]:Math.min(p.size[1]-top,p.size[0]*.9);
      scale=Math.min(440/p.size[0],480/viewHeight);
      canvas.width=Math.round(p.size[0]*scale);canvas.height=Math.round(viewHeight*scale);
    }
    viewport();
    function activate(){if(compact){card.parentElement.querySelectorAll('.mask-card').forEach(el=>el.classList.toggle('selected',el===card));}}
    canvas.onfocus=activate;
    let chosen=Math.max(0,p.faces.findIndex(f=>f.shared)),drag;
    select.value=chosen;
    const current=()=>p.faces[chosen];
    function draw(){
      const sampleScale=p.image.height/p.size[1];
      c.clearRect(0,0,canvas.width,canvas.height);c.drawImage(p.image,0,top*sampleScale,p.image.width,viewHeight*sampleScale,0,0,canvas.width,canvas.height);
      p.faces.forEach((f,k)=>{
        const [x,y,w,h]=stickerRect(p,f);
        if(!f.deleted&&!f.back_disabled)c.drawImage(sticker,x*scale,(y-top)*scale,w*scale,h*scale);
        if(k===chosen){c.strokeStyle=f.deleted||f.back_disabled?'#72746f':'#e70012';c.lineWidth=2;c.setLineDash(f.deleted||f.back_disabled?[5,4]:[]);c.strokeRect(x*scale,(y-top)*scale,w*scale,h*scale);c.setLineDash([]);}
      });
      const f=current();
      card.querySelector('.mask-note').textContent=!f?'没有可调整的新增头像':f.back_disabled?'背向头像已关闭，可在会员基础设置中开启':f.deleted?'此头像已删除，可恢复自动位置':f.manual_position?'已手动调整位置':'自动位置 · 可拖动或用方向键微调';
      card.querySelectorAll('[data-dx],[data-dy],[data-delete]').forEach(b=>b.disabled=saving||!f||f.deleted||f.back_disabled);
      card.querySelector('[data-reset]').disabled=saving||!f;
      select.disabled=saving||!f;
    }
    function move(dx,dy){const f=current();if(saving||!f||f.deleted||f.back_disabled)return;f.manual_position=movedPosition(p,f,dx,dy);draw();}
    select.onchange=()=>{chosen=Number(select.value);draw();};
    card.querySelectorAll('[data-dx],[data-dy]').forEach(b=>b.onclick=()=>move(Number(b.dataset.dx||0)*.005,Number(b.dataset.dy||0)*.005));
    card.querySelector('[data-delete]').onclick=()=>{if(current()){current().deleted=true;draw();}};
    card.querySelector('[data-reset]').onclick=()=>{if(current()){current().deleted=false;current().manual_position=null;draw();}};
    if(compact)card.querySelector('[data-full]').onclick=()=>{full=!full;card.querySelector('[data-full]').textContent=full?'聚焦头肩':'查看全图';viewport();draw();};
    const point=e=>{const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)/r.width*p.size[0],top+(e.clientY-r.top)/r.height*viewHeight];};
    canvas.onpointerdown=e=>{
      if(saving)return;activate();const [x,y]=point(e);
      for(let k=p.faces.length-1;k>=0;k--){const f=p.faces[k],[rx,ry,w,h]=stickerRect(p,f);if(!f.deleted&&!f.back_disabled&&x>=rx&&x<=rx+w&&y>=ry&&y<=ry+h){chosen=k;select.value=k;drag={point:[x,y],position:f.manual_position?[...f.manual_position]:null};canvas.setPointerCapture(e.pointerId);canvas.focus();draw();e.preventDefault();break;}}
    };
    canvas.onpointermove=e=>{if(!drag||saving)return;const [x,y]=point(e),f=current();f.manual_position=drag.position;f.manual_position=movedPosition(p,f,(x-drag.point[0])/p.size[0],(y-drag.point[1])/p.size[1]);draw();};
    canvas.onpointerup=canvas.onpointercancel=()=>drag=null;
    canvas.onkeydown=e=>{const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(delta){e.preventDefault();move(delta[0]*.005,delta[1]*.005);}else if(e.key==='Delete'&&current()&&!saving){e.preventDefault();current().deleted=true;draw();}};
    draw();
  }
}
