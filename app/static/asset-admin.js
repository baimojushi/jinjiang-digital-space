const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function api(path, options={}) {
  const r=await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  const data=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data));
  return data;
}
const labelRights={authorized:"已授权",pending:"待确认",internal:"仅内部",restricted:"受限",expired:"已到期",public_domain_verified:"公版已核验"};
const labelReview={pending:"待审核",approved:"已通过",rejected:"已驳回"};
const labelPublish={draft:"草稿",published:"已发布",archived:"已归档"};
function status(text,type=""){return `<span class="aa-status ${type}">${esc(text)}</span>`}

async function loadSummary(){
  const s=await api("/api/admin/assets/summary");
  const items=[
    ["文化资产",s.total_assets,`${s.artworks}件作品 · ${s.hotel_artifacts}件酒店物件`],
    ["公开推荐池",s.public_pool,"满足授权/审核/发布/封面四项门禁"],
    ["授权待确认",s.rights_pending,"当前禁止公开推荐"],
    ["空间",s.spaces,`${s.spaces_need_enrichment}个需补全主数据`],
    ["媒体",s.media,`${s.hotel_photos_unassigned}张酒店照片待空间确认`],
    ["已发布",s.published,"公开服务可消费资产"],
  ];
  $("#summary").innerHTML=items.map(x=>`<div class="aa-kpi"><span>${x[0]}</span><b>${x[1]}</b><i>${x[2]}</i></div>`).join("");
}
function query(){
  const p=new URLSearchParams();
  if($("#q").value)p.set("q",$("#q").value);
  if($("#collection").value)p.set("collection_code",$("#collection").value);
  if($("#rights").value)p.set("rights_status",$("#rights").value);
  if($("#publish").value)p.set("publish_status",$("#publish").value);
  p.set("page_size","100");
  return p.toString();
}
async function loadAssets(){
  const d=await api("/api/admin/assets?"+query());
  $("#assetBody").innerHTML=d.items.map(a=>{
    const gate=a.publication_gate;
    return `<tr class="aa-row" data-id="${a.id}">
      <td><div class="aa-asset"><img src="${a.cover||""}"><div><b>${esc(a.title)}</b><small>${esc(a.asset_code)} · ${esc(a.author||"作者待补")}</small></div></div></td>
      <td>${esc(a.collection_name||"-")}</td>
      <td>${status(labelRights[a.rights_status]||a.rights_status,a.rights_status==="authorized"?"ok":a.rights_status==="pending"?"block":"warn")}</td>
      <td>${status(labelReview[a.review_status]||a.review_status,a.review_status==="approved"?"ok":"warn")}</td>
      <td>${status(labelPublish[a.publish_status]||a.publish_status,a.publish_status==="published"?"ok":"")}</td>
      <td>${gate.eligible?status("可发布","ok"):status(gate.blocking.join(" / "),"block")}</td>
    </tr>`;
  }).join("");
  document.querySelectorAll(".aa-row").forEach(x=>x.onclick=()=>openAsset(+x.dataset.id));
}
async function loadRights(){
  const d=await api("/api/admin/rights/queue");$("#rightsCount").textContent=d.count;
  $("#rightsQueue").innerHTML=d.items.slice(0,40).map(a=>`<div class="aa-list-item" data-id="${a.id}"><b>${esc(a.asset_code)} · ${esc(a.title)}</b><span>${esc(a.collection_name)}｜${esc(labelRights[a.rights_status]||a.rights_status)}｜${esc(a.source||"来源待补")}</span></div>`).join("");
  document.querySelectorAll("#rightsQueue [data-id]").forEach(x=>x.onclick=()=>openAsset(+x.dataset.id));
}
async function loadQuality(){
  const d=await api("/api/admin/data-quality");
  $("#blockingCount").textContent=d.blocking+" 阻断";$("#warningCount").textContent=d.warning+" 提醒";
  $("#qualityList").innerHTML=d.issues.slice(0,80).map(i=>`<div class="aa-list-item"><b>${status(i.severity==="blocking"?"阻断":"提醒",i.severity==="blocking"?"block":"warn")} ${esc(i.code)} · ${esc(i.field)}</b><span>${esc(i.message)}</span></div>`).join("");
}
async function loadSpaces(){
  const d=await api("/api/admin/spaces");
  $("#spaceGrid").innerHTML=d.items.map(s=>`<div class="aa-space" data-id="${s.id}"><img src="${s.cover||""}"><div><b>${esc(s.space_code)} · ${esc(s.name)}</b><span>${esc(s.building||"楼宇待补")}｜${esc(s.space_type||"类型待补")}｜${s.media_count} 张关联图</span></div></div>`).join("");
  document.querySelectorAll(".aa-space").forEach(x=>x.onclick=()=>openSpace(+x.dataset.id,d.items.find(s=>s.id==+x.dataset.id)));
}
async function loadMedia(){
  const cat=$("#mediaCategory").value;
  const d=await api("/api/admin/media?page_size=120"+(cat?"&category="+encodeURIComponent(cat):""));
  $("#mediaGrid").innerHTML=d.items.map(m=>`<div class="aa-media"><img loading="lazy" src="${m.file_path}"><span>${esc(m.category||m.media_code)}</span></div>`).join("");
}
async function loadBatches(){
  const d=await api("/api/admin/import-batches");
  $("#batchBody").innerHTML=d.items.map(b=>`<tr><td>${esc(b.source_name)}</td><td>${esc(b.source_type)}</td><td>${status(b.status,b.status==="success"?"ok":"warn")}</td><td>${b.total_rows}</td><td>${b.success_rows}</td><td>${b.warning_rows}</td><td>${esc(b.note||"")}</td></tr>`).join("");
}
async function openAsset(id){
  const a=await api("/api/admin/assets/"+id);
  const gate=a.publication_gate;
  $("#assetEditor").innerHTML=`<div class="aa-editor">
    <div class="eyebrow">${esc(a.collection_name)} · ${esc(a.asset_code)}</div>
    <h2>${esc(a.title)}</h2>
    ${a.cover?`<img class="aa-editor-cover" src="${a.cover}">`:""}
    <div class="aa-gate ${gate.eligible?"ok":"block"}"><b>发布门禁：</b>${gate.eligible?"当前满足公开发布条件":esc(gate.blocking.join("；"))}</div>
    <div class="aa-form">
      ${field("title","作品名称",a.title)}
      ${field("author","作者",a.author)}
      ${field("source","来源",a.source)}
      ${field("building","楼宇/业务归属",a.building)}
      ${field("region","地域",a.region)}
      ${field("era","时代",a.era)}
      ${field("dimensions","尺寸",a.dimensions)}
      ${field("style","风格",a.style)}
      <div class="aa-field"><label>授权状态</label><select id="f_rights_status">${opts(labelRights,a.rights_status)}</select></div>
      <div class="aa-field"><label>审核状态</label><select id="f_review_status">${opts(labelReview,a.review_status)}</select></div>
      <div class="aa-field"><label>发布状态</label><select id="f_publish_status">${opts(labelPublish,a.publish_status)}</select></div>
      <div class="aa-field full"><label>标签（逗号分隔）</label><input id="f_tags" value="${esc((a.tags||[]).join(","))}"></div>
      <div class="aa-field full"><label>主题说明</label><textarea id="f_theme_text">${esc(a.theme_text||"")}</textarea></div>
      <div class="aa-field full"><label>作品故事</label><textarea id="f_story">${esc(a.story||"")}</textarea></div>
    </div>
    <div class="aa-editor-actions"><button class="aa-btn primary" id="saveAsset">保存主数据</button><button class="aa-btn" id="publishAsset" ${gate.eligible?"":"disabled"}>进入公开推荐池</button></div>
  </div>`;
  $("#drawer").classList.remove("hidden");
  $("#saveAsset").onclick=async()=>{
    const payload={};
    ["title","author","source","building","region","era","dimensions","style","theme_text","story","rights_status","review_status","publish_status"].forEach(k=>payload[k]=$("#f_"+k)?.value??null);
    payload.tags=$("#f_tags").value.split(",").map(x=>x.trim()).filter(Boolean);
    try{await api("/api/admin/assets/"+id,{method:"PUT",body:JSON.stringify(payload)});await refreshAll();await openAsset(id)}
    catch(e){alert("保存失败："+e.message)}
  };
  $("#publishAsset").onclick=async()=>{try{await api("/api/admin/assets/"+id+"/publish",{method:"POST",body:"{}"});await refreshAll();await openAsset(id)}catch(e){alert("发布失败："+e.message)}};
}
function field(id,label,val){return `<div class="aa-field"><label>${label}</label><input id="f_${id}" value="${esc(val||"")}"></div>`}
function opts(map,current){return Object.entries(map).map(([k,v])=>`<option value="${k}" ${k===current?"selected":""}>${v}</option>`).join("")}
function openSpace(id,s){
  $("#assetEditor").innerHTML=`<div class="aa-editor"><div class="eyebrow">Space · ${esc(s.space_code)}</div><h2>${esc(s.name)}</h2>${s.cover?`<img class="aa-editor-cover" src="${s.cover}">`:""}
    <div class="aa-gate block"><b>空间适配状态：</b>${s.status==="needs_enrichment"?"主数据待补齐，精确空间匹配被阻断":"可参与空间匹配"}</div>
    <div class="aa-form">
      ${field("s_name","空间名称",s.name)}${field("s_building","楼宇",s.building)}${field("s_floor","楼层",s.floor)}
      ${field("s_space_type","空间类型",s.space_type)}${field("s_function","功能",s.function)}${field("s_style","风格",s.style)}
      ${field("s_display_type","展陈方式",s.display_type)}${field("s_wall_size","可用墙面/尺寸",s.wall_size)}
      ${field("s_light_condition","光照条件",s.light_condition)}${field("s_visitor_access","访客权限",s.visitor_access)}
      <div class="aa-field"><label>可展陈</label><select id="f_s_display_available"><option value="">待确认</option><option value="true" ${s.display_available===1?"selected":""}>是</option><option value="false" ${s.display_available===0?"selected":""}>否</option></select></div>
      <div class="aa-field"><label>状态</label><select id="f_s_status"><option value="needs_enrichment" ${s.status==="needs_enrichment"?"selected":""}>待补充</option><option value="active" ${s.status==="active"?"selected":""}>可使用</option></select></div>
    </div><div class="aa-editor-actions"><button class="aa-btn primary" id="saveSpace">保存空间主数据</button></div></div>`;
  $("#drawer").classList.remove("hidden");
  $("#saveSpace").onclick=async()=>{
    const val=$("#f_s_display_available").value;
    const payload={
      name:$("#f_s_name").value,building:$("#f_s_building").value,floor:$("#f_s_floor").value,
      space_type:$("#f_s_space_type").value,function:$("#f_s_function").value,style:$("#f_s_style").value,
      display_type:$("#f_s_display_type").value,wall_size:$("#f_s_wall_size").value,light_condition:$("#f_s_light_condition").value,
      visitor_access:$("#f_s_visitor_access").value,display_available:val===""?null:val==="true",status:$("#f_s_status").value
    };
    try{await api("/api/admin/spaces/"+id,{method:"PUT",body:JSON.stringify(payload)});$("#drawer").classList.add("hidden");await refreshAll()}catch(e){alert("保存失败："+e.message)}
  };
}
async function refreshAll(){await Promise.all([loadSummary(),loadAssets(),loadRights(),loadQuality(),loadSpaces(),loadMedia(),loadBatches()])}
["q","collection","rights","publish"].forEach(id=>$("#"+id).addEventListener(id==="q"?"input":"change",()=>loadAssets()));
$("#mediaCategory").onchange=loadMedia;
$("#drawerClose").onclick=()=>$("#drawer").classList.add("hidden");
$("#recompute").onclick=async()=>{const b=$("#recompute");b.disabled=true;b.textContent="计算中…";try{const r=await api("/api/admin/recompute-space-matches",{method:"POST",body:"{}"});alert(r.message)}finally{b.disabled=false;b.textContent="重算空间匹配"}};
refreshAll();
