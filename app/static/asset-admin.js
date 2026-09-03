const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// API_BASE 推断：公网 /jinjiang/* 取 /jinjiang，本地 / 取空。不依赖 <base href> 解析
const _baseEl = document.querySelector('base[href]');
let _baseFromTag = _baseEl ? _baseEl.getAttribute('href') : '';
if (!_baseFromTag) {
  const m = window.location.pathname.match(/^(\/[^\/]+)(\/|$)/);
  _baseFromTag = (m && m[1] !== '/') ? m[1] : '';
}
const API_BASE = _baseFromTag.replace(/\/$/, '');
function apiPath(p){if(!p.startsWith('/'))return p;return API_BASE+p;}
function url(p){if(!p)return p;if(/^https?:/i.test(p))return p;return API_BASE+(p.startsWith('/')?p:'/'+p);}

async function api(path,options={}){const r=await fetch(apiPath(path),{headers:{"Content-Type":"application/json"},...options});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:JSON.stringify(d.detail||d));return d}
const rights={authorized:"已授权",pending:"待确认",internal:"仅内部",restricted:"受限",expired:"已到期",public_domain_verified:"公版已核验"};
const review={pending:"待审核",approved:"已通过",rejected:"已驳回"};
const publish={draft:"草稿",published:"已发布",archived:"已归档"};
function status(t,type=""){return `<span class="aa-status ${type}">${esc(t)}</span>`}
function yes(v){return v===1?status("是","ok"):v===0?status("否",""):status("待确认","warn")}
function boolOptions(v){return `<option value="" ${v==null?"selected":""}>待确认</option><option value="true" ${v===1?"selected":""}>是</option><option value="false" ${v===0?"selected":""}>否</option>`}
function getBool(id){const v=$("#"+id).value;return v===""?null:v==="true"}

async function loadSummary(){
 const s=await api("/api/admin/assets/summary");
 const data=[
  ["文化资产",s.total_assets,`${s.artworks}件作品 · ${s.hotel_artifacts}件酒店物件`],
  ["公开推荐池",s.public_pool,"同时通过授权/审核/发布/媒体门禁"],
  ["空间",s.spaces,`${s.spaces_need_enrichment}个待补主数据`],
  ["媒体",s.media,`${s.hotel_photos_unassigned}张酒店照片待空间确认`],
 ];
 $("#summary").innerHTML=data.map(x=>`<div class="aa-kpi"><span>${x[0]}</span><b>${x[1]}</b><i>${x[2]}</i></div>`).join("");
}
function qs(){const p=new URLSearchParams({page_size:"100"});if($("#q").value)p.set("q",$("#q").value);if($("#collection").value)p.set("collection_code",$("#collection").value);if($("#rights").value)p.set("rights_status",$("#rights").value);if($("#publish").value)p.set("publish_status",$("#publish").value);return p}
async function loadAssets(){
 const d=await api("/api/admin/assets?"+qs());
 $("#assetBody").innerHTML=d.items.map(a=>`<tr class="aa-row" data-id="${a.id}">
 <td><div class="aa-asset"><img src="${url(a.cover)||""}"><div><b>${esc(a.title)}</b><small>${esc(a.asset_code)} · ${esc(a.author||"作者待补")}</small></div></div></td>
 <td>${esc(a.collection_name||"-")}</td>
 <td>${status(rights[a.rights_status]||a.rights_status,a.rights_status==="authorized"?"ok":a.rights_status==="pending"?"warn":"")}</td>
 <td>${status(review[a.review_status]||a.review_status,a.review_status==="approved"?"ok":"warn")} ${status(publish[a.publish_status]||a.publish_status,a.publish_status==="published"?"ok":"")}</td>
 <td>${a.publication_gate.eligible?status("可进入C端","ok"):status(a.publication_gate.blocking.join(" / "),"block")}</td></tr>`).join("");
 document.querySelectorAll(".aa-row").forEach(x=>x.onclick=()=>openAsset(+x.dataset.id));
}
async function loadRights(){const d=await api("/api/admin/rights/queue");$("#rightsCount").textContent=d.count;$("#rightsQueue").innerHTML=d.items.slice(0,50).map(a=>`<div class="aa-list-item" data-id="${a.id}"><b>${esc(a.asset_code)} · ${esc(a.title)}</b><span>${esc(a.collection_name||"")}｜${esc(rights[a.rights_status]||a.rights_status)}</span></div>`).join("");document.querySelectorAll("#rightsQueue [data-id]").forEach(x=>x.onclick=()=>openAsset(+x.dataset.id))}
async function loadQuality(){const d=await api("/api/admin/data-quality");$("#blockingCount").textContent=d.blocking+" 阻断";$("#warningCount").textContent=d.warning+" 提醒";$("#qualityList").innerHTML=d.issues.slice(0,100).map(i=>`<div class="aa-list-item"><b>${status(i.severity==="blocking"?"阻断":"提醒",i.severity==="blocking"?"block":"warn")} ${esc(i.code)}</b><span>${esc(i.message)}</span></div>`).join("")}
async function loadSpaces(){const d=await api("/api/admin/spaces");$("#spaceGrid").innerHTML=d.items.map(s=>`<div class="aa-space" data-id="${s.id}"><img src="${url(s.cover)||""}"><div><b>${esc(s.space_code)} · ${esc(s.name)}</b><span>${esc(s.building||"楼宇待补")}｜${esc(s.space_type||"类型待补")}｜${s.media_count}张关联图</span></div></div>`).join("");document.querySelectorAll(".aa-space").forEach(x=>x.onclick=()=>openSpace(+x.dataset.id,d.items.find(s=>s.id==+x.dataset.id)))}
async function loadMedia(){const cat=$("#mediaCategory").value;const d=await api("/api/admin/media?page_size=120"+(cat?"&category="+encodeURIComponent(cat):""));$("#mediaGrid").innerHTML=d.items.map(m=>`<div class="aa-media"><img loading="lazy" src="${url(m.file_path)}"><span>${esc(m.category||m.media_code)}</span></div>`).join("")}
async function loadBatches(){const d=await api("/api/admin/import-batches");$("#batchBody").innerHTML=d.items.map(b=>`<tr><td>${esc(b.source_name)}</td><td>${esc(b.source_type)}</td><td>${status(b.status,b.status==="success"?"ok":"warn")}</td><td>${b.total_rows}</td><td>${b.success_rows}</td><td>${b.warning_rows}</td><td>${esc(b.note||"")}</td></tr>`).join("")}
function field(id,label,val){return `<div class="aa-field"><label>${label}</label><input id="f_${id}" value="${esc(val||"")}"></div>`}
function options(map,current){return Object.entries(map).map(([k,v])=>`<option value="${k}" ${k===current?"selected":""}>${v}</option>`).join("")}

async function openAsset(id){
 const a=await api("/api/admin/assets/"+id),gate=a.publication_gate;
 $("#assetEditor").innerHTML=`<div class="aa-editor"><div class="eyebrow">${esc(a.collection_name)} · ${esc(a.asset_code)}</div><h2>${esc(a.title)}</h2>
 ${a.cover?`<img class="aa-editor-cover" src="${url(a.cover)}">`:""}
 <div class="aa-gate ${gate.eligible?"ok":"block"}"><b>数字公开门禁：</b>${gate.eligible?"当前满足C端公开条件":esc(gate.blocking.join("；"))}</div>
 <div class="aa-form">
 ${field("title","作品名称",a.title)}${field("author","作者",a.author)}${field("source","来源",a.source)}${field("building","楼宇/业务归属",a.building)}
 ${field("region","地域",a.region)}${field("era","时代",a.era)}${field("dimensions","尺寸",a.dimensions)}${field("style","风格",a.style)}
 <div class="aa-field"><label>授权状态</label><select id="f_rights_status">${options(rights,a.rights_status)}</select></div>
 <div class="aa-field"><label>审核状态</label><select id="f_review_status">${options(review,a.review_status)}</select></div>
 <div class="aa-field"><label>发布状态</label><select id="f_publish_status">${options(publish,a.publish_status)}</select></div>
 <div class="aa-field full"><label>标签（逗号分隔）</label><input id="f_tags" value="${esc((a.tags||[]).join(","))}"></div>
 <div class="aa-field full"><label>主题说明</label><textarea id="f_theme_text">${esc(a.theme_text||"")}</textarea></div>
 <div class="aa-field full"><label>作品故事</label><textarea id="f_story">${esc(a.story||"")}</textarea></div></div>
 <div class="aa-editor-actions"><button class="aa-btn primary" id="saveAsset">保存维护数据</button><button class="aa-btn" id="publishAsset" ${gate.eligible?"":"disabled"}>校验公开状态</button></div></div>`;
 $("#drawer").classList.remove("hidden");
 $("#saveAsset").onclick=async()=>{
  const payload={};
  ["title","author","source","building","region","era","dimensions","style","theme_text","story","rights_status","review_status","publish_status"].forEach(k=>payload[k]=$("#f_"+k)?.value??null);
  payload.tags=$("#f_tags").value.split(",").map(x=>x.trim()).filter(Boolean);
  try{await api("/api/admin/assets/"+id,{method:"PUT",body:JSON.stringify(payload)});await refreshAll();await openAsset(id)}catch(e){alert("保存失败："+e.message)}
 };
 $("#publishAsset").onclick=async()=>{try{await api("/api/admin/assets/"+id+"/publish",{method:"POST",body:"{}"});await refreshAll();await openAsset(id)}catch(e){alert("校验失败："+e.message)}};
}
function openSpace(id,s){
 $("#assetEditor").innerHTML=`<div class="aa-editor"><div class="eyebrow">SPACE · ${esc(s.space_code)}</div><h2>${esc(s.name)}</h2>${s.cover?`<img class="aa-editor-cover" src="${url(s.cover)}">`:""}
 <div class="aa-gate ${s.status==="active"?"ok":"block"}"><b>空间状态：</b>${s.status==="active"?"可进入空间策展匹配":"主数据待补齐，具体Space匹配保持阻断"}</div>
 <div class="aa-form">${field("s_name","空间名称",s.name)}${field("s_building","楼宇",s.building)}${field("s_floor","楼层",s.floor)}${field("s_space_type","空间类型",s.space_type)}${field("s_function","功能",s.function)}${field("s_style","风格",s.style)}${field("s_display_type","展陈方式",s.display_type)}${field("s_wall_size","可用墙面/尺寸",s.wall_size)}${field("s_light_condition","光照条件",s.light_condition)}${field("s_visitor_access","访客权限",s.visitor_access)}
 <div class="aa-field"><label>可展陈</label><select id="f_s_display_available">${boolOptions(s.display_available)}</select></div><div class="aa-field"><label>状态</label><select id="f_s_status"><option value="needs_enrichment" ${s.status==="needs_enrichment"?"selected":""}>待补充</option><option value="active" ${s.status==="active"?"selected":""}>可使用</option></select></div></div>
 <div class="aa-editor-actions"><button class="aa-btn primary" id="saveSpace">保存空间主数据</button></div></div>`;
 $("#drawer").classList.remove("hidden");
 $("#saveSpace").onclick=async()=>{const payload={name:$("#f_s_name").value,building:$("#f_s_building").value,floor:$("#f_s_floor").value,space_type:$("#f_s_space_type").value,function:$("#f_s_function").value,style:$("#f_s_style").value,display_type:$("#f_s_display_type").value,wall_size:$("#f_s_wall_size").value,light_condition:$("#f_s_light_condition").value,visitor_access:$("#f_s_visitor_access").value,display_available:getBool("f_s_display_available"),status:$("#f_s_status").value};try{await api("/api/admin/spaces/"+id,{method:"PUT",body:JSON.stringify(payload)});$("#drawer").classList.add("hidden");await refreshAll()}catch(e){alert("保存失败："+e.message)}};
}
async function refreshAll(){await Promise.all([loadSummary(),loadAssets(),loadRights(),loadQuality(),loadSpaces(),loadMedia(),loadBatches()])}
["q","collection","rights","publish"].forEach(id=>$("#"+id).addEventListener(id==="q"?"input":"change",loadAssets));
$("#mediaCategory").onchange=loadMedia;$("#drawerClose").onclick=()=>$("#drawer").classList.add("hidden");
$("#recompute").onclick=async()=>{const b=$("#recompute");b.disabled=true;try{const r=await api("/api/admin/recompute-space-matches",{method:"POST",body:"{}"});alert(r.message)}finally{b.disabled=false}};
refreshAll();

// 背景锦江酒店 logo 视差：滚动量 ×0.5，比第一层慢 50%
// 方向与滚动相反（向下滚时 logo 向上走），叠加原本的居中偏移
(() => {
  const wm = document.getElementById("brandWatermark");
  if (!wm) return;
  let ticking = false;
  const update = () => {
    wm.style.transform = `translateY(calc(-50% - ${window.scrollY * 0.5}px))`;
    ticking = false;
  };
  window.addEventListener("scroll", () => {
    if (!ticking) {
      requestAnimationFrame(update);
      ticking = true;
    }
  }, { passive: true });
  update();
})();
