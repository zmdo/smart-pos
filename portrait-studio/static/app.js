const $=id=>document.getElementById(id);
const directionNames={front:"前",back:"后",left:"左",right:"右",unknown:"待确认"};
const statusNames={queued:"排队中",running:"处理中",completed:"已完成",partial:"部分完成",empty:"无可用人物",failed:"失败",cancelled:"已停止",interrupted:"已中断"};
let archiveFile=null,stickerFile=null,currentJob=null,pollTimer=null,jobs=[],busy=false,maskObjectUrl=null;
const escapeHTML=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(text){$("toast").textContent=text;$("toast").classList.remove("hidden");clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").classList.add("hidden"),4500)}
async function api(url,options={}){
 const response=await fetch(url,options);let value;try{value=await response.json()}catch{value={detail:"服务响应异常"}}
 if(response.status===401&&!url.endsWith("/login")){if(!$("authDialog").open)$("authDialog").showModal();throw new Error("请先输入访问码")}
 if(!response.ok)throw new Error(typeof value.detail==="string"?value.detail:"请求失败，请检查输入");
 return value;
}
function jsonRequest(method,value){return{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(value)}}
function figure(direction){
 const side=direction==="left"||direction==="right",flip=direction==="right"?' transform="translate(60 0) scale(-1 1)"':"";
 return '<svg viewBox="0 0 60 90" fill="none" aria-hidden="true"><g'+flip+'>'+
 (side?'<path d="M31 10c-5 0-9 4-9 9v3l-4 5h4v4c0 3 3 5 6 5h2v6h9V30c3-3 4-7 3-11-1-6-5-9-11-9Z" fill="#b8c2a8"/><path d="M28 39c-7 3-10 12-10 24l3 20h20l-1-31c0-6-4-11-9-13Z" fill="#c4cdb6"/><path d="m29 47-5 23 4 13" stroke="#aab89a" stroke-width="3" stroke-linecap="round"/>':
 '<ellipse cx="30" cy="23" rx="11" ry="14" fill="#b8c2a8"/><path d="M24 34v7h12v-7M20 42c-10 2-14 12-15 31l8 2 3-20v28h28V55l3 20 8-2c-1-19-5-29-15-31Z" fill="#c4cdb6"/>'+
 (direction==="front"?'<path d="m22 43 8 8 8-8" stroke="#aab89a" stroke-width="2"/><circle cx="26" cy="23" r="1" fill="#849574"/><circle cx="34" cy="23" r="1" fill="#849574"/><path d="M27 29h6" stroke="#8fa07d"/>':'<path d="M30 44v35M18 47l12 7 12-7" stroke="#aab89a" stroke-width="1.5"/>'))+'</g></svg>';
}
$("viewGrid").innerHTML=["front","back","left","right"].map((d,i)=>'<div class="view-card"><span class="view-number">0'+(i+1)+'</span>'+figure(d)+'<span>'+directionNames[d]+' / '+d.toUpperCase()+'</span></div>').join("");
function updateStart(){ $("startBtn").disabled=!archiveFile||busy; $("startHint").textContent=busy?"上传中，请保持页面打开":archiveFile?"素材已就绪 · 由远程 GPU 完成处理":"选择一个压缩包，开始整理你的素材"; }
function selectFile(file){
 if(!file)return;
 if(!/\.(zip|tar|gz|tgz)$/i.test(file.name)){toast("请选择 ZIP、TAR 或 TAR.GZ 压缩包");return}
 if(file.size>1024**3){toast("压缩包不可超过 1 GB");return}
 archiveFile=file;$("selectedFile").classList.remove("hidden");$("fileName").textContent=file.name;
 $("fileSize").textContent=(file.size/1024/1024).toFixed(2)+" MB · 已准备上传";
 $("uploadTitle").textContent="素材已就绪";$("uploadSubtitle").innerHTML="拖入新压缩包，或 <em>点击更换</em>";updateStart();
}
$("dropzone").onclick=()=>$("archiveInput").click();
$("archiveInput").onchange=e=>selectFile(e.target.files[0]);
for(const event of ["dragenter","dragover"])$("dropzone").addEventListener(event,e=>{e.preventDefault();$("dropzone").classList.add("dragging")});
for(const event of ["dragleave","drop"])$("dropzone").addEventListener(event,e=>{e.preventDefault();$("dropzone").classList.remove("dragging")});
$("dropzone").addEventListener("drop",e=>selectFile(e.dataTransfer.files[0]));
$("removeFile").onclick=()=>{archiveFile=null;$("archiveInput").value="";$("selectedFile").classList.add("hidden");$("uploadTitle").textContent="将压缩包拖到这里";$("uploadSubtitle").innerHTML="或 <em>点击选择文件</em>";updateStart()};
function dimensions(){ $("dimensionSummary").textContent=$("width").value+" × "+$("height").value+" px / 张";document.querySelectorAll("[data-size]").forEach(b=>b.classList.toggle("active",b.dataset.size===$("width").value+","+$("height").value)) }
document.querySelectorAll("[data-size]").forEach(b=>b.onclick=()=>{const[w,h]=b.dataset.size.split(",");$("width").value=w;$("height").value=h;dimensions()});
$("width").oninput=dimensions;$("height").oninput=dimensions;
$("padding").oninput=()=>$("paddingValue").textContent=$("padding").value+"%";
$("maskEnabled").onchange=()=>$("maskOptions").classList.toggle("disabled",!$("maskEnabled").checked);
function syncMaskScale(){$("maskScale").disabled=!$("maskScaled").checked;$("maskFitNote").textContent=$("maskScaled").checked?"遮罩图缩放到面部框大小，再乘以下方覆盖倍率":"默认不缩放：遮罩图保持原始像素，中心对齐面部框"}
$("maskScaled").onchange=syncMaskScale;syncMaskScale();
function defaultMask(){stickerFile=null;$("stickerInput").value="";$("defaultMask").classList.add("active");$("customMask").classList.remove("active");$("customMaskArt").textContent="+";$("maskFilename").textContent="上传 PNG / JPG";if(maskObjectUrl){URL.revokeObjectURL(maskObjectUrl);maskObjectUrl=null}}
$("defaultMask").onclick=defaultMask;$("customMask").onclick=()=>$("stickerInput").click();
$("stickerInput").onchange=e=>{const file=e.target.files[0];if(!file)return;if(file.size>10*1024*1024){toast("遮罩图片不可超过 10 MB");return}stickerFile=file;$("defaultMask").classList.remove("active");$("customMask").classList.add("active");$("maskFilename").textContent=file.name;if(maskObjectUrl)URL.revokeObjectURL(maskObjectUrl);maskObjectUrl=URL.createObjectURL(file);const img=new Image();img.src=maskObjectUrl;img.alt="自定义遮罩";$("customMaskArt").replaceChildren(img)};
$("resetBtn").onclick=()=>{for(const[k,v]of Object.entries({width:512,height:768,padding:8,gap:12,confidence:.35,maskScale:1.35,background:"#f2f0eb"}))$(k).value=v;$("maskEnabled").checked=true;$("maskScaled").checked=false;$("maskOptions").classList.remove("disabled");syncMaskScale();$("padding").oninput();dimensions();defaultMask();toast("已恢复默认设置")};
function getOptions(){
 for(const id of ["width","height","gap","confidence","maskScale"])if(!$(id).reportValidity())throw new Error("请检查处理参数");
 return{width:Number($("width").value),height:Number($("height").value),padding:Number($("padding").value),gap:Number($("gap").value),confidence:Number($("confidence").value),mask_scale:Number($("maskScale").value),mask_scaled:$("maskScaled").checked,background:$("background").value,mask_enabled:$("maskEnabled").checked}
}
function upload(form){
 return new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open("POST","/api/jobs");xhr.timeout=20*60*1000;
 xhr.upload.onprogress=e=>{if(e.lengthComputable){const percent=Math.round(e.loaded/e.total*100);$("startBtn").firstElementChild.textContent=percent===100?"正在创建任务…":"上传中 "+percent+"%"}};
 xhr.onerror=()=>reject(new Error("上传失败，请检查网络"));xhr.ontimeout=()=>reject(new Error("上传超时，请重试"));
 xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText)}catch{reject(new Error("上传失败，服务返回异常"));return}if(xhr.status>=200&&xhr.status<300)resolve(data);else reject(new Error(data.detail||"上传失败"))};xhr.send(form);
 });
}
$("startBtn").onclick=async()=>{if(!archiveFile||busy)return;try{const opts=getOptions();busy=true;updateStart();const form=new FormData();form.append("archive",archiveFile);form.append("options",JSON.stringify(opts));if(stickerFile&&opts.mask_enabled)form.append("sticker",stickerFile);const job=await upload(form);toast("已提交任务，关闭页面后仍会继续处理");await openJob(job.id);await refreshHistory()}catch(e){toast(e.message)}finally{busy=false;$("startBtn").firstElementChild.textContent="开始处理";updateStart()}};
function fileUrl(jobId,name,download=false){return "/api/jobs/"+jobId+"/files/"+encodeURIComponent(name)+(download?"?download=true":"")}
async function openJob(id,scroll=true){currentJob=id;localStorage.setItem("portraitJob",id);if(location.search!=="?job="+id)history.replaceState(null,"","?job="+id);clearTimeout(pollTimer);await pollJob();if(scroll)$("taskPanel").scrollIntoView({behavior:"smooth",block:"start"})}
async function pollJob(){
 const requested=currentJob;
 try{const job=await api("/api/jobs/"+requested);if(currentJob!==requested)return;renderJob(job);if(["queued","running"].includes(job.status))pollTimer=setTimeout(pollJob,2200);else refreshHistory()}
 catch(e){if(currentJob!==requested)return;if(e.message==="任务不存在"){localStorage.removeItem("portraitJob");currentJob=null;$("taskPanel").classList.add("hidden")}else{toast(e.message);pollTimer=setTimeout(pollJob,5000)}}
}
function renderJob(job){
 $("taskPanel").classList.remove("hidden");$("taskBadge").textContent=statusNames[job.status]||job.status;
 $("taskTitle").textContent=job.name;$("stageText").textContent=job.stage;
 $("currentFile").textContent=job.current_file||"扫描压缩包中的图片目录";
 $("progressText").textContent=(job.processed||0)+" / "+(job.total||"—");
 const active=["queued","running"].includes(job.status);
 const percent=job.total?(job.processed/job.total*100):0;
 $("progressBar").style.width=(active?percent:100)+"%";
 $("cancelBtn").classList.toggle("hidden",!active);$("cancelBtn").disabled=!!job.cancel_requested;
 $("cancelBtn").textContent=job.cancel_requested?"正在停止…":"停止任务";
 const stats=job.stats||{};
 $("stats").innerHTML=[["已处理",job.processed||0],["成功",stats.done||0],["无人跳过",stats.skipped||0],["待检查",stats.review||0],["失败",stats.error||0],["忽略非图片",job.ignored_files||0]].map(([a,b])=>"<span>"+a+"<strong>"+b+"</strong></span>").join("");
 let note=job.error||"";
 if(job.status==="empty")note=(stats.review||0)?"图片需要人工检查，暂未生成拼图。请查看逐张记录。":"未检测到可输出的人物，本任务已结束。";
 if(job.status==="interrupted")note="服务器重启中断了任务，请重新上传素材。";
 $("taskError").textContent=note;$("taskError").classList.toggle("hidden",!note);
 const hasResults=job.sheets&&job.sheets.length;
 $("results").classList.toggle("hidden",!hasResults);
 if(hasResults){
 $("downloadAll").href="/api/jobs/"+job.id+"/download";
 const signature=JSON.stringify(job.sheets)+job.id;
 if($("sheets").dataset.signature!==signature){$("sheets").dataset.signature=signature;$("sheets").innerHTML=job.sheets.map(s=>{
 const missing=Object.entries(s.counts).filter(([,n])=>!n).map(([d])=>directionNames[d]).join("、");
 return '<article class="sheet"><div class="sheet-top"><div><strong>'+escapeHTML(s.directory==="."?"根目录":s.directory)+'</strong><small>'+s.width+' × '+s.height+' px</small></div><a class="text-button" href="'+fileUrl(job.id,s.file,true)+'" download>↓ 下载 PNG</a></div><div class="sheet-directions">'+["front","back","left","right"].map(d=>"<span>"+directionNames[d]+" · "+s.counts[d]+"</span>").join("")+'</div><a href="'+fileUrl(job.id,s.file)+'" target="_blank" rel="noopener"><img src="'+fileUrl(job.id,s.preview)+'" alt="'+escapeHTML(s.directory)+' 的前后左右拼图" loading="lazy"></a><div class="sheet-note">'+(missing?"缺少"+missing+"朝向，已保留空位。":"四向已齐全。")+" 下载包包含单张图片、分割掩码及坐标 JSON。</div></article>"
 }).join("")}
 }
 $("recordCount").textContent="("+((job.records||[]).length)+")";
 $("recordRows").innerHTML=(job.records||[]).map(r=>"<tr><td>"+escapeHTML(r.source)+'</td><td class="record-'+r.status+'">'+({done:"完成",skipped:"跳过",review:"待检查",error:"失败"}[r.status]||r.status)+"</td><td>"+(directionNames[r.orientation]||"—")+(r.orientation_confidence!=null?" "+Math.round(r.orientation_confidence*100)+"%":"")+"</td><td>"+(r.face_detection==="skipped_back"?"背面跳过":r.face_bbox?({detector:"检测器",vision:"视觉模型"}[r.face_source]||"已定位"):"—")+(r.face_mask?'<span class="badge-sam">SAM 2</span>':"")+"</td><td>"+escapeHTML(r.reason||r.warning||r.orientation_reason||"")+"</td></tr>").join("");
}
$("cancelBtn").onclick=async()=>{try{await api("/api/jobs/"+currentJob+"/cancel",{method:"POST"});$("cancelBtn").disabled=true;toast("将在当前模型调用结束后停止")}catch(e){toast(e.message)}};
async function refreshHistory(){try{jobs=await api("/api/jobs");$("historyCount").textContent=jobs.length;if($("historyDialog").open)renderHistory()}catch{}}
function renderHistory(){
 $("historyList").innerHTML=jobs.length?jobs.map(j=>'<div class="history-row"><div><strong>'+escapeHTML(j.name)+'</strong><small>'+new Date(j.created_at*1000).toLocaleString("zh-CN")+' · '+(statusNames[j.status]||j.status)+' · '+(j.processed||0)+' 张</small></div><button class="secondary-button" data-open="'+j.id+'">查看</button>'+(!["running","queued"].includes(j.status)?'<button class="icon-button" data-delete="'+j.id+'" aria-label="删除任务">×</button>':"")+"</div>").join(""):'<div class="history-empty">还没有处理记录<br><small>上传你的第一组素材，结果会保存在这里。</small></div>';
 $("historyList").querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>{$("historyDialog").close();openJob(b.dataset.open)});
 $("historyList").querySelectorAll("[data-delete]").forEach(b=>b.onclick=async()=>{if(!confirm("删除此任务及其上传素材、处理结果？"))return;try{await api("/api/jobs/"+b.dataset.delete,{method:"DELETE"});if(currentJob===b.dataset.delete){clearTimeout(pollTimer);currentJob=null;localStorage.removeItem("portraitJob");$("taskPanel").classList.add("hidden")}await refreshHistory();toast("任务已删除")}catch(e){toast(e.message)}});
}
$("historyBtn").onclick=async()=>{await refreshHistory();renderHistory();$("historyDialog").showModal()};
$("workspaceBtn").onclick=()=>window.scrollTo({top:0,behavior:"smooth"});
document.querySelectorAll(".close-dialog").forEach(b=>b.onclick=()=>b.closest("dialog").close());
$("settingsBtn").onclick=async()=>{try{const s=await api("/api/settings");$("baseUrl").value=s.base_url;$("modelName").value=s.model;$("apiKey").value="";$("apiKey").placeholder=s.api_key_configured?"已配置 · 留空保持不变":"请输入 API Key";$("settingsMessage").textContent="";$("settingsDialog").showModal()}catch(e){toast(e.message)}};
$("settingsForm").onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{await api("/api/settings",jsonRequest("PUT",{base_url:$("baseUrl").value.trim(),model:$("modelName").value.trim(),api_key:$("apiKey").value.trim()}));$("apiKey").value="";$("settingsMessage").textContent="已保存。新任务将使用这些设置。";toast("模型设置已保存")}catch(err){$("settingsMessage").textContent=err.message}finally{button.disabled=false}};
$("testApiBtn").onclick=async()=>{$("testApiBtn").disabled=true;$("settingsMessage").textContent="正在连接模型服务…";try{const r=await api("/api/settings/test",{method:"POST"});$("settingsMessage").textContent=r.model_available?"连接成功，已找到配置的模型。":"连接成功，但模型列表未包含配置的模型名，请核对。"}catch(e){$("settingsMessage").textContent=e.message}finally{$("testApiBtn").disabled=false}};
$("authDialog").addEventListener("cancel",e=>e.preventDefault());
$("authForm").onsubmit=async e=>{e.preventDefault();e.submitter.disabled=true;try{await api("/api/login",jsonRequest("POST",{code:$("accessCode").value.trim()}));$("accessCode").value="";$("authDialog").close();await initialize()}catch(err){$("authMessage").textContent=err.message}finally{e.submitter.disabled=false}};
async function initialize(){
 try{const s=await api("/api/settings");await refreshHistory();const shared=new URLSearchParams(location.search).get("job");const id=shared||localStorage.getItem("portraitJob")||(jobs.find(j=>["running","queued"].includes(j.status))||{}).id;if(id)await openJob(id,false);if(!s.api_key_configured)toast("请先在模型设置中配置 API Key")}
 catch(e){if(!$("authDialog").open)$("authDialog").showModal()}
}
(async()=>{const params=new URLSearchParams(location.hash.slice(1));const access=params.get("access");if(access){history.replaceState(null,"",location.pathname+location.search);try{await api("/api/login",jsonRequest("POST",{code:access}))}catch{}}await initialize()})();

