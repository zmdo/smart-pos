'use strict';
const DATA = JSON.parse(document.getElementById('gallery-data').textContent);
const VIEWS = {front:'正面',side:'侧面',back:'背面'};
const KINDS = {human:'人工确认',rule:'位置／文字规则',inferred:'推断',pending:'待审'};
const TAB_NAMES = {three_views:'完整三视图',vs:'同朝向对比',single:'单张体测图'};
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const family = view => view.startsWith('side') ? 'side' : view;
let selected = DATA.default_case, category = 'three_views', store = '', query = '';
let activeZoom = null;
const stage = document.getElementById('stage');
const dialog = document.getElementById('lightbox');

function currentCase() { return DATA.cases.find(c => c.group_id === selected); }
function visibleCases() { return DATA.cases.filter(c => (!store || c.store === store) && `${c.store} ${c.member}`.includes(query)); }
function updateHash() {
  if (selected) history.replaceState(null,'',`#${selected}/${category}`);
}
function caseStatus(c) {
  return c.review_count ? `<span class="status review">${c.review_count} 张需审核</span>` : '<span class="status">6 张规则标记</span>';
}
function filters() {
  const stores = ['',...new Set(DATA.cases.map(c => c.store))];
  const host = document.getElementById('store-filters'); host.replaceChildren();
  for (const name of stores) {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = name || '全部'; button.setAttribute('aria-pressed',String(store === name));
    button.onclick = () => { store = name; refresh(); };
    host.append(button);
  }
}
function sidebar(cases) {
  document.getElementById('case-count').textContent = `${cases.length} / ${DATA.counts.cases}`;
  const host = document.getElementById('case-list'); host.replaceChildren();
  if (!cases.length) {
    const empty = document.createElement('p'); empty.className = 'empty-search'; empty.textContent = '没有匹配的案例'; host.append(empty); return;
  }
  let lastStore = '';
  for (const c of cases) {
    if (c.store !== lastStore) {
      const heading = document.createElement('h3'); heading.className = 'store-heading'; heading.textContent = c.store; host.append(heading); lastStore = c.store;
    }
    const button = document.createElement('button'); button.type = 'button'; button.className = 'case-button';
    button.setAttribute('aria-pressed',String(selected === c.group_id));
    button.innerHTML = `<img class="case-thumb" src="${c.grid.file}" alt="" loading="lazy"><span><span class="case-name">${esc(c.member)}</span><span class="case-sub">${esc(c.store)} · 6 图完整</span></span><span class="case-arrow" aria-hidden="true">↗</span>`;
    button.onclick = () => { selected = c.group_id; refresh(); };
    host.append(button);
  }
}
function zoomButton(product, title, hero = false) {
  return `<button class="zoom-trigger" data-zoom="${product.product_id}" aria-label="放大查看${esc(title)}"><img src="${product.file}" alt="${esc(title)}" width="${product.width}" height="${product.height}" ${hero ? 'fetchpriority="high"' : 'loading="lazy"'}></button>`;
}
function productCard(c, p, index, single = false) {
  const row = single ? c.slots[index] : null;
  const heading = VIEWS[family(single ? row.view : p.view)];
  const badge = row ? `<span class="status ${row.requires_review ? 'review' : ''}">${esc(row.label)}</span>`
    : `<span class="status ${p.requires_review ? 'review' : ''}">${p.requires_review ? '含需审核图片' : '位置／文字规则'}</span>`;
  const name = `${c.member} · ${heading}${single ? ' · '+row.label : '前后对比'}`;
  return `<article class="product-card"><div class="image-wrap">${zoomButton(p,name)}</div><div class="product-caption"><h3>${heading}${single ? '' : ' · 前后对比'}</h3>${badge}${row ? `<p class="asset-id">${esc(row.asset_id)}</p>` : ''}<a href="${p.file}" download="${esc(name)}.jpg">下载原图 ↗</a></div></article>`;
}
function renderStage(c) {
  if (!c) {
    document.getElementById('case-heading').replaceChildren();
    document.getElementById('review-note').textContent = '';
    stage.innerHTML = '<div class="empty-stage">没有匹配的案例，请调整搜索或门店筛选。</div>'; return;
  }
  document.getElementById('case-heading').innerHTML = `<h2><span>${esc(c.store)} /</span>${esc(c.member)}</h2>${caseStatus(c)}`;
  if (category === 'three_views') {
    const p = c.grid;
    const diagram = ['训练前','训练后'].map(phase => ['正面','侧面','背面'].map(view => `<span>${view}<small>${phase}</small></span>`).join('')).join('');
    const labels = Object.entries(KINDS).filter(([kind]) => c.label_counts[kind]).map(([kind,label]) => `<span>${label}</span><strong>${c.label_counts[kind]} 张</strong>`).join('');
    stage.innerHTML = `<div class="hero-layout"><div class="artwork"><div class="artwork-canvas">${zoomButton(p,`${c.member}完整三视图`,true)}</div><div class="artwork-toolbar"><span>2 × 3 · 当前拼图</span><button class="text-button" data-zoom="${p.product_id}">放大查看 ⤢</button><a class="download" href="${p.file}" download="${esc(c.member)}-当前三视图.jpg">下载原图 ↗</a></div></div><aside class="info-panel" aria-label="当前版式说明"><h3>六张照片，一组对比</h3><div class="layout-map" aria-label="上排训练前，下排训练后；每排正面、侧面、背面">${diagram}</div><ul class="design-notes"><li>上排训练前，下排训练后</li><li>每列对应同一个朝向</li><li>红色标签条标注朝向与阶段</li></ul><hr class="info-divider"><h3>本例阶段标记</h3><div class="label-list">${labels}</div><p class="info-callout">${c.review_count ? '带“推断”或“待审”的图片保留原有标记，方便查看样式时同时核对。' : '这套案例六张图均沿用位置或文字规则，可作为当前样式的完整参考。'}</p><details class="source-slots"><summary>查看六张素材编号</summary><ul>${c.slots.map(row => `<li>${esc(row.asset_id)} · ${VIEWS[family(row.view)]} · ${row.phase === 'before' ? '前' : '后'}</li>`).join('')}</ul></details></aside></div>`;
  } else if (category === 'vs') {
    stage.innerHTML = `<div class="product-grid">${c.comparisons.map((p,i) => productCard(c,p,i)).join('')}</div>`;
  } else {
    stage.innerHTML = ['训练前','训练后'].map((phase,line) => `<h3 class="phase-heading">${phase} <span aria-hidden="true">／</span> 正面 · 侧面 · 背面</h3><div class="product-grid">${c.singles.slice(line*3,line*3+3).map((p,i) => productCard(c,p,line*3+i,true)).join('')}</div>`).join('');
  }
  for (const trigger of stage.querySelectorAll('[data-zoom]')) trigger.onclick = () => openZoom(trigger.dataset.zoom,trigger);
  document.getElementById('review-note').textContent = c.review_count ? '“（推断）”和“（待审）”均沿用现有标签，尚待人工核对；本页只用于成品样式预览。' : '图片直接来自已有成品。切换分类可查看同一套六张照片的其他输出形式。';
}
function openZoom(id, trigger) {
  const c = currentCase(), product = [c.grid,...c.comparisons,...c.singles].find(p => p.product_id === id);
  const title = `${c.store} / ${c.member} · ${product.kind === 'three_views' ? '完整三视图' : VIEWS[family(product.view)]+(product.kind === 'vs' ? '前后对比' : '单张体测图')}`;
  const image = document.getElementById('lightbox-image'); image.src = product.file; image.alt = title;
  document.getElementById('lightbox-title').textContent = title;
  const download = document.getElementById('lightbox-download'); download.href = product.file; download.download = title.replaceAll('/','-')+'.jpg';
  activeZoom = trigger; dialog.showModal();
}
function refresh() {
  const cases = visibleCases();
  if (!cases.some(c => c.group_id === selected)) selected = cases[0]?.group_id || null;
  filters(); sidebar(cases);
  for (const button of document.querySelectorAll('[data-tab]')) {
    const active = category === button.dataset.tab;
    button.setAttribute('aria-selected',String(active)); button.tabIndex = active ? 0 : -1;
  }
  stage.setAttribute('aria-labelledby',`tab-${category}`);
  renderStage(currentCase()); updateHash();
}
document.getElementById('search').addEventListener('input',event => { query = event.target.value.trim(); refresh(); });
for (const tab of document.querySelectorAll('[data-tab]')) {
  tab.onclick = () => { category = tab.dataset.tab; refresh(); };
  tab.onkeydown = event => {
    const tabs = [...document.querySelectorAll('[data-tab]')], index = tabs.indexOf(tab);
    const next = {ArrowRight:(index+1)%3,ArrowLeft:(index+2)%3,Home:0,End:2}[event.key];
    if (next !== undefined) { event.preventDefault(); category = tabs[next].dataset.tab; refresh(); tabs[next].focus(); }
  };
}
document.getElementById('close-lightbox').onclick = () => dialog.close();
dialog.addEventListener('click',event => { if (event.target === dialog) dialog.close(); });
dialog.addEventListener('close',() => { activeZoom?.focus(); activeZoom = null; });
function readHash() {
  const [id,tab] = location.hash.slice(1).split('/');
  if (DATA.cases.some(c => c.group_id === id)) selected = id;
  if (Object.hasOwn(TAB_NAMES,tab)) category = tab;
}
window.addEventListener('hashchange',() => { readHash(); refresh(); });
readHash(); refresh();
