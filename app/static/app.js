const USER = "demo-user";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const SOURCE = new URLSearchParams(location.search).get("source") || "direct";
const SESSION_KEY = "jinjiang_session_v32";
const makeId = () => (globalThis.crypto?.randomUUID ? crypto.randomUUID().replaceAll("-","") : (Date.now().toString(36)+Math.random().toString(36).slice(2)));
const SESSION = localStorage.getItem(SESSION_KEY) || ("sess-web-" + makeId().slice(0,16));
localStorage.setItem(SESSION_KEY, SESSION);

// API_BASE 推断：公网 /jinjiang/* 时取 /jinjiang，本地 / 时取空
// 不依赖 <base href> 解析（某些代理会丢 base）
// 优先用 <base>，fallback 用 pathname 推断
const _baseEl = document.querySelector('base[href]');
let _baseFromTag = _baseEl ? _baseEl.getAttribute('href') : '';
if (!_baseFromTag) {
  // pathname like /jinjiang/ or /jinjiang/foo -> /jinjiang
  const p = window.location.pathname;
  const m = p.match(/^(\/[^\/]+)(\/|$)/);
  _baseFromTag = (m && m[1] !== '/') ? m[1] : '';
}
const API_BASE = _baseFromTag.replace(/\/$/, '');

function apiPath(p) {
  if (!p.startsWith('/')) return p;
  return API_BASE + p;
}

let current = null;
let currentRecommendation = null;
let currentSession = SESSION;
let loading = false;

const AI_EXPERIENCE_KEY = "jinjiang_ai_experience_v1";
const aiState = {
  serviceEnabled:false, file:null, fileUrl:null, intentCode:"harmonize",
  intentLabel:"希望作品自然融入空间", experienceId:null, artworkId:null,
  candidateSetId:null, candidates:[], status:"idle", pollTimer:null,
  traced:new Set(), resultViewed:false, selectedCandidateId:null,
  maxAssetBytes:25*1024*1024, acceptedMimeTypes:["image/jpeg","image/png","image/webp"]
};
const recommendationImpressions=new Set();
const reasonOpens=new Set();

async function api(path, options={}) {
  const r = await fetch(apiPath(path),{headers:{"Content-Type":"application/json"},...options});
  const data = await r.json().catch(()=>({}));
  if(!r.ok){
    const detail=data.detail;
    const msg=typeof detail==="string"?detail:(detail?.message||data.error?.message||JSON.stringify(detail||data));
    throw new Error(msg);
  }
  return data;
}
async function apiForm(path, formData) {
  const r=await fetch(apiPath(path),{method:"POST",body:formData});
  const data=await r.json().catch(()=>({}));
  if(!r.ok){
    const detail=data.detail;
    const msg=typeof detail==="string"?detail:(detail?.message||data.error?.message||JSON.stringify(detail||data));
    throw new Error(msg);
  }
  return data;
}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function toast(msg){const el=$("#toast");el.textContent=msg;el.classList.add("on");clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove("on"),1800)}
// 图片 URL — 后端给的是 /static/... 绝对路径，浏览器会绕过 <base> 落到 Funnel 根，必须加 API_BASE 前缀
function url(p){if(!p)return p;if(/^https?:/i.test(p))return p;return API_BASE+(p.startsWith('/')?p:'/'+p);}
function currentRecommendationSnapshot(){
  if(!current?.id||!currentRecommendation)return null;
  return {
    recommendationId:currentRecommendation, artworkId:current.id,
    sessionId:currentSession, sourceCode:SOURCE
  };
}
async function commitRecommendationImpression(snapshot=currentRecommendationSnapshot()){
  if(!snapshot?.artworkId||!snapshot.recommendationId||recommendationImpressions.has(snapshot.recommendationId))return;
  await api("/recommendations/impression",{method:"POST",body:JSON.stringify({
    recommendation_id:snapshot.recommendationId,user_id:USER,artwork_id:snapshot.artworkId,
    session_id:snapshot.sessionId,source_code:snapshot.sourceCode||SOURCE,metadata:{surface:"today.hero"}
  })});
  recommendationImpressions.add(snapshot.recommendationId);
}
async function sendArtworkEventSnapshot(event,snapshot,metadata={}){
  if(!snapshot?.artworkId)return;
  if(snapshot.recommendationId)await commitRecommendationImpression(snapshot).catch(()=>{});
  return api("/user-event",{method:"POST",body:JSON.stringify({
    user_id:USER,event,artwork_id:snapshot.artworkId,recommendation_id:snapshot.recommendationId||null,
    session_id:snapshot.sessionId||currentSession,source_code:snapshot.sourceCode||SOURCE,metadata
  })}).catch(()=>{});
}
async function sendEvent(event,id=current?.id,metadata={}) {
  if(!id)return;
  const snapshot=(current?.id===id)?currentRecommendationSnapshot():{
    recommendationId:null,artworkId:id,sessionId:currentSession,sourceCode:SOURCE
  };
  return sendArtworkEventSnapshot(event,snapshot,metadata);
}
function sendTelemetry(event,entityType,entityId,metadata={}){
  return api("/user-event",{method:"POST",body:JSON.stringify({
    user_id:USER,event,artwork_id:null,recommendation_id:null,session_id:currentSession,
    source_code:SOURCE,entity_type:entityType,entity_id:String(entityId),metadata
  })}).catch(()=>{});
}
function observeRecommendationEngagement(){
  const snapshot=currentRecommendationSnapshot();
  if(!snapshot)return;
  const recId=snapshot.recommendationId;
  const hero=$("#plate"),reason=$("#reasonCard");
  const onHero=()=>commitRecommendationImpression(snapshot).catch(()=>{});
  const onReason=()=>{
    if(reasonOpens.has(recId))return;
    reasonOpens.add(recId);
    sendArtworkEventSnapshot("reason_open",snapshot,{surface:"today.reason"});
  };
  if(!("IntersectionObserver" in window)){onHero();onReason();return}
  const io=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting||entry.intersectionRatio<.45)continue;if(entry.target===hero)onHero();if(entry.target===reason)onReason();io.unobserve(entry.target)}},{threshold:[.45]});
  if(hero)io.observe(hero);if(reason)io.observe(reason);
}
function workGrid(items){
  if(!items?.length) return `<div class="quiet">还没有记录。</div>`;
  return items.map(x=>`<div class="mini-work"><img src="${url(x.cover)||""}" alt="${esc(x.title)}"><span>${esc(x.title)}</span></div>`).join("");
}

async function loadRecommendation(exclude){
  if(loading)return;loading=true;
  try{
    const q=new URLSearchParams({user_id:USER,session_id:currentSession,source:SOURCE});
    if(exclude)q.set("exclude",exclude);
    const d=await api("/daily-recommendation?"+q.toString());
    current=d.artwork;currentRecommendation=d.recommendation_id;currentSession=d.session_id||currentSession;
    $("#sourceChip").textContent=d.source?.name||"今日锦江";
    $("#plateImg").src=url(current.cover);$("#plateImg").alt=current.title;
    $("#relevanceLabel").textContent=d.relevance_label||current.theme;
    $("#workTitle").textContent=current.title;
    $("#workLead").textContent=current.theme_text||"从作品进入今天的锦江文化线索。";
    $("#metaAuthor").textContent=current.author||"作者待补";
    $("#metaOrigin").textContent=[current.region,current.era].filter(Boolean).join(" · ");
    $("#reasonList").innerHTML=d.reason.map(x=>`<li>${esc(x)}</li>`).join("");
    $("#workStory").textContent=current.story||current.theme_text||"";
    $("#workTags").innerHTML=(current.tags||[]).slice(0,8).map(t=>`<span class="pill">${esc(t)}</span>`).join("");
    $("#curateIdle").classList.remove("hidden");$("#curateDone").classList.add("hidden");
    $("#curateNote").textContent=d.curation_state?.votes?`已有 ${d.curation_state.votes} 次共创选择支持这件作品。你的选择也会进入酒店端。`:"你的选择会进入酒店端的共创策展候选，成为下一场文化内容的真实用户信号。";
    ["btnLike","btnFav","btnDislike"].forEach(id=>$("#"+id).classList.remove("on"));
    const detail=await api("/artworks/"+current.id+"?user_id="+encodeURIComponent(USER));
    $("#relatedList").innerHTML=(detail.related||[]).map(r=>`<figure data-open="${r.id}"><img src="${url(r.cover)}" alt="${esc(r.title)}"><figcaption>${esc(r.title)}</figcaption></figure>`).join("");
    syncAiForCurrentArtwork();
    observeRecommendationEngagement();
  }catch(e){toast("推荐服务暂时不可用");console.error(e)}
  finally{loading=false}
}

$("#btnLike").onclick=async()=>{await sendEvent("like");$("#btnLike").classList.add("on");$("#btnDislike").classList.remove("on");toast("已记住你的喜欢")}
$("#btnFav").onclick=async()=>{await sendEvent("favorite",current?.id,aiState.resultViewed?{ai_experience_id:aiState.experienceId}:{});$("#btnFav").classList.add("on");await sendAiOutcome("saved");toast("已收藏")}
$("#btnDislike").onclick=async()=>{await sendEvent("dislike");$("#btnDislike").classList.add("on");$("#btnLike").classList.remove("on");toast("已记录，下次会少一些类似内容")}
$("#btnChange").onclick=async()=>{if(!current)return;const old=current.id;if(aiState.experienceId&&aiState.artworkId===old&&!aiState.selectedCandidateId&&(aiState.status!=="completed"||aiState.resultViewed))await traceAI("decision.abandoned",{reason:"artwork_changed"},"final");await sendEvent("change",old);await loadRecommendation(old);toast("换了一条新的文化线索")}
$("#btnCurate").onclick=async()=>{
  if(!current)return;
  const r=await api("/curation-vote",{method:"POST",body:JSON.stringify({
    user_id:USER,artwork_id:current.id,vote:1,recommendation_id:currentRecommendation,
    session_id:currentSession,source_code:SOURCE,metadata:aiState.resultViewed?{ai_experience_id:aiState.experienceId}:{}
  })});
  $("#curateIdle").classList.add("hidden");$("#curateDone").classList.remove("hidden");
  $("#curateMeta").textContent=`这件作品目前累计 ${r.votes} 次共创选择。酒店端已经收到新的用户信号。`;
  await sendAiOutcome("curation_supported",r.vote_id?`curation_vote_${r.vote_id}`:null);
  toast("已加入锦江共创策展");
};

async function openSheet(id){
  await sendEvent("detail",id);
  const a=await api("/artworks/"+id+"?user_id="+encodeURIComponent(USER));
  $("#sheetImg").src=url(a.cover);$("#sheetImg").alt=a.title;
  $("#sheetTheme").textContent=a.relevance_label||a.theme;$("#sheetTitle").textContent=a.title;
  $("#sheetMeta").textContent=[a.author,a.region,a.era,a.source].filter(Boolean).join(" · ");
  $("#sheetStory").textContent=a.story||a.theme_text||"";
  $("#sheetReasons").innerHTML=(a.reason||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  $("#sheet").classList.remove("hidden");
}
$("#plate").onclick=e=>{if(e.target.closest("button"))return;current&&openSheet(current.id)}
$("#relatedList").onclick=e=>{const x=e.target.closest("[data-open]");if(x)openSheet(+x.dataset.open)}
$("#sheetClose").onclick=()=>$("#sheet").classList.add("hidden");
$("#sheet").onclick=e=>{if(e.target.id==="sheet")$("#sheet").classList.add("hidden")};


function aiPersist(){
  if(aiState.experienceId&&aiState.artworkId){
    localStorage.setItem(AI_EXPERIENCE_KEY,JSON.stringify({experienceId:aiState.experienceId,artworkId:aiState.artworkId}));
  }else localStorage.removeItem(AI_EXPERIENCE_KEY);
}
function aiStored(){try{return JSON.parse(localStorage.getItem(AI_EXPERIENCE_KEY)||"null")}catch{return null}}
function aiClearPoll(){if(aiState.pollTimer){clearTimeout(aiState.pollTimer);aiState.pollTimer=null}}
function aiSetPane(name){
  $("#aiIdle").classList.toggle("hidden",name!=="idle");
  $("#aiProcessing").classList.toggle("hidden",name!=="processing");
  $("#aiResult").classList.toggle("hidden",name!=="result");
}
function aiUpdateStartEnabled(){
  $("#aiStart").disabled=!(aiState.serviceEnabled&&aiState.file&&$("#aiConsent").checked);
}
function aiReset({keepService=true}={}){
  aiClearPoll();
  if(aiState.fileUrl)URL.revokeObjectURL(aiState.fileUrl);
  const enabled=aiState.serviceEnabled;
  Object.assign(aiState,{serviceEnabled:keepService?enabled:false,file:null,fileUrl:null,intentCode:"harmonize",intentLabel:"希望作品自然融入空间",experienceId:null,artworkId:null,candidateSetId:null,candidates:[],status:"idle",pollTimer:null,traced:new Set(),resultViewed:false,selectedCandidateId:null});
  $("#aiSpaceInput").value="";$("#aiConsent").checked=false;
  $(".ai-upload").classList.remove("hidden");
  $("#aiSpacePreviewWrap").classList.add("hidden");$("#aiSpacePreview").removeAttribute("src");
  $$("#aiIntentList .ai-intent").forEach((b,i)=>b.classList.toggle("on",i===0));
  $("#aiCandidateGrid").innerHTML="";$("#aiNoSolution").classList.add("hidden");
  aiSetPane("idle");aiUpdateStartEnabled();aiPersist();
}
async function loadAiService(){
  try{
    const s=await api("/ai/space-preview/service");
    aiState.serviceEnabled=!!s.enabled;
    const c=s.constraints||{};
    aiState.maxAssetBytes=Number(c.max_asset_bytes)||25*1024*1024;
    aiState.acceptedMimeTypes=Array.isArray(c.accepted_mime_types)&&c.accepted_mime_types.length?c.accepted_mime_types.map(x=>String(x).toLowerCase()):["image/jpeg","image/png","image/webp"];
    $("#aiUnavailable").classList.toggle("hidden",!!s.enabled);
    if(!s.enabled)$("#aiUnavailable").textContent=s.reason||"AI 空间体验当前暂不可用。";
  }catch(e){aiState.serviceEnabled=false;$("#aiUnavailable").classList.remove("hidden");$("#aiUnavailable").textContent="AI 空间体验当前暂不可用。"}
  aiUpdateStartEnabled();
}
function currentSupportsAiSpacePreview(){return !!current?.capabilities?.ai_space_preview}
function syncAiForCurrentArtwork(){
  if(!current)return;
  const eligible=currentSupportsAiSpacePreview();
  $("#aiSpaceCard").classList.toggle("hidden",!eligible);
  if(!eligible){
    if(aiState.experienceId&&aiState.artworkId!==current.id)aiReset();
    return;
  }
  $("#aiArtworkThumb").src=url(current.cover)||"";$("#aiArtworkThumb").alt=current.title;
  $("#aiArtworkTitle").textContent=current.title;$("#aiArtworkSize").textContent=current.dimensions||"作品尺寸待补";
  const saved=aiStored();
  if(saved&&saved.artworkId===current.id&&saved.experienceId){
    aiState.experienceId=saved.experienceId;aiState.artworkId=current.id;aiState.status="processing";aiSetPane("processing");pollAiExperience(true);
  }else if((saved&&saved.artworkId!==current.id)||(aiState.artworkId&&aiState.artworkId!==current.id)){
    aiReset();
  }
}
async function traceAI(eventType,payload={},phase="post_preview",candidateSetId=aiState.candidateSetId){
  if(!aiState.experienceId)return;
  const key=eventType+":"+(payload.candidate_id||payload.outcome_type||payload.presentation_id||"")+":"+(candidateSetId||"");
  if(["candidate_set.exposed","preview.viewed","candidate.selected","decision.committed","outcome.recorded"].includes(eventType)&&aiState.traced.has(key))return;
  try{
    await api(`/ai/space-preview/${encodeURIComponent(aiState.experienceId)}/trace?user_id=${encodeURIComponent(USER)}`,{method:"POST",body:JSON.stringify({event_type:eventType,phase,candidate_set_id:candidateSetId,payload})});
    aiState.traced.add(key);
    if(eventType==="preview.viewed")aiState.resultViewed=true;
  }catch(e){console.warn("AI trace queued/failed",e)}
}
async function sendAiOutcome(type,externalOutcomeId=null){
  if(!aiState.experienceId||!aiState.resultViewed||aiState.artworkId!==current?.id)return;
  await traceAI("outcome.recorded",{outcome_type:type,external_outcome_id:externalOutcomeId,external_content_id:current.asset_code||String(current.id),candidate_id:aiState.selectedCandidateId||null},"post_decision");
}
function aiProgress(d){
  const p=d.progress||{};let pct=Number(p.percent);
  if(!Number.isFinite(pct))pct=d.status==="running"?35:5;
  pct=Math.max(2,Math.min(100,pct));
  $("#aiProgressPct").textContent=Math.round(pct)+"%";$("#aiProgressBar").style.width=pct+"%";
  $("#aiProgressMessage").textContent=p.message||({queued:"任务已进入处理队列",running:"AI 正在分析空间并生成效果"}[d.status]||"正在处理");
}
function aiCandidateHtml(c,i){
  const art=(c.artifacts||[]).find(a=>a.production_usable)||c.artifacts?.[0];
  if(!art)return "";
  const risk=c.safety?.risk_level?`风险 ${esc(c.safety.risk_level)}`:(art.production_usable?"可展示":"需复核");
  const selected=aiState.selectedCandidateId===c.candidate_id?" committed":"";
  return `<article class="ai-candidate${selected}" data-candidate="${esc(c.candidate_id)}">
    <img data-ai-artifact="${esc(art.artifact_id)}" src="${url(art.url)}" alt="AI 空间效果方案 ${i+1}">
    <div class="ai-candidate-body"><div class="ai-candidate-meta"><b>空间方案 ${String(i+1).padStart(2,"0")}</b><span class="ai-risk">${esc(risk)}</span></div>
    <div class="ai-candidate-actions"><button type="button" class="ai-accept">这个效果可以</button><button type="button" class="ai-reject">不太适合</button></div>
    <div class="ai-reject-reasons hidden"><button data-reason="scale_overwhelming" data-category="geometry_feasibility">比例不合适</button><button data-reason="relation_mismatch" data-category="aesthetic_relation">和空间不协调</button><button data-reason="intent_mismatch" data-category="intent_mismatch">不是我想要的感觉</button><button data-reason="other" data-category="other">其他</button></div></div>
  </article>`;
}
async function renderAiResult(d){
  aiClearPoll();aiState.status="completed";aiState.candidateSetId=d.candidate_set_id||null;aiState.candidates=d.candidates||[];aiSetPane("result");
  const outcome=d.outcome?.code||"deliverable";
  const usable=aiState.candidates.filter(c=>(c.artifacts||[]).some(a=>a.production_usable));
  if(outcome==="no_valid_solution"||outcome==="review_required"||!usable.length){
    $("#aiCandidateGrid").innerHTML="";$("#aiNoSolution").classList.remove("hidden");
    $("#aiNoSolution").textContent=outcome==="review_required"?"AI 已完成分析，但当前结果需要复核，因此暂不作为可用空间方案展示。":"AI 已完成判断，但没有找到足够可靠的摆放方案。换一张更完整、正对墙面的空间照片通常会更有效。";
    return;
  }
  $("#aiNoSolution").classList.add("hidden");$("#aiCandidateGrid").innerHTML=usable.map(aiCandidateHtml).join("");
  observeAiCandidates();
}
function observeAiCandidates(){
  const cards=[$$("#aiCandidateGrid .ai-candidate")].flat();
  if(!cards.length)return;
  const exposed=new Set();
  const emitVisible=async card=>{
    const id=card.dataset.candidate;if(!id||exposed.has(id))return;exposed.add(id);
    const position=cards.indexOf(card)+1;
    await traceAI("candidate_set.exposed",{presentation_id:"jj_pres_"+makeId(),surface:"artwork_detail.ai_preview",items:[{candidate_id:id,position}]},"post_preview",aiState.candidateSetId);
    const img=card.querySelector("img[data-ai-artifact]");
    if(img){
      const viewed=()=>traceAI("preview.viewed",{candidate_id:id,artifact_id:img.dataset.aiArtifact||null},"post_preview",aiState.candidateSetId);
      if(img.complete&&img.naturalWidth)viewed();else img.addEventListener("load",viewed,{once:true});
    }
  };
  if(!("IntersectionObserver" in window)){cards.forEach(emitVisible);return}
  const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(entry.isIntersecting&&entry.intersectionRatio>=.45){emitVisible(entry.target);observer.unobserve(entry.target)}}},{threshold:[.45]});
  cards.forEach(card=>observer.observe(card));
}
async function pollAiExperience(immediate=false){
  aiClearPoll();if(!aiState.experienceId)return;
  try{
    const d=await api(`/ai/space-preview/${encodeURIComponent(aiState.experienceId)}?user_id=${encodeURIComponent(USER)}`);
    aiState.status=d.status||aiState.status;aiState.selectedCandidateId=d.selected_candidate_id||aiState.selectedCandidateId;
    if(d.status==="completed"){await renderAiResult(d);return}
    if(d.status==="failed"){
      aiSetPane("result");$("#aiCandidateGrid").innerHTML="";$("#aiNoSolution").classList.remove("hidden");$("#aiNoSolution").textContent=d.error?.message||"AI 生成失败，可以换一张空间照片重新尝试。";return;
    }
    aiSetPane("processing");aiProgress(d);aiState.pollTimer=setTimeout(()=>pollAiExperience(),8000);
  }catch(e){
    if(immediate){aiSetPane("processing");$("#aiProgressMessage").textContent="正在恢复上一次 AI 任务…"}
    aiState.pollTimer=setTimeout(()=>pollAiExperience(),10000);
  }
}
async function startAiExperience(){
  if(!currentSupportsAiSpacePreview()){toast("仅画作类文化资产支持 AI 空间体验");return}
  if(!current||!aiState.file||!$("#aiConsent").checked)return;
  aiClearPoll();aiSetPane("processing");$("#aiProgressPct").textContent="0%";$("#aiProgressBar").style.width="2%";$("#aiProgressMessage").textContent="正在安全上传作品与空间照片…";
  const fd=new FormData();fd.append("artwork_id",String(current.id));fd.append("user_id",USER);fd.append("session_id",currentSession);if(currentRecommendation)fd.append("recommendation_id",currentRecommendation);fd.append("source_code",SOURCE);fd.append("intent_code",aiState.intentCode);fd.append("intent_label",aiState.intentLabel);fd.append("consent","true");fd.append("space_image",aiState.file,aiState.file.name||"space.jpg");
  try{
    const d=await apiForm("/ai/space-preview",fd);aiState.experienceId=d.experience_id;aiState.artworkId=current.id;aiState.status=d.status||"queued";aiState.resultViewed=false;aiState.traced=new Set();aiPersist();aiProgress(d);aiState.pollTimer=setTimeout(()=>pollAiExperience(),3500);
  }catch(e){aiSetPane("idle");toast(e.message||"AI 空间体验启动失败")}
}

$("#aiSpaceInput").addEventListener("change",e=>{
  const file=e.target.files?.[0];if(!file)return;const type=String(file.type||"").toLowerCase();
  if(!aiState.acceptedMimeTypes.includes(type)){toast("当前支持："+aiState.acceptedMimeTypes.join(" / "));e.target.value="";return}
  if(file.size>aiState.maxAssetBytes){toast(`空间照片不能超过 ${(aiState.maxAssetBytes/1024/1024).toFixed(0)}MB`);e.target.value="";return}
  if(aiState.fileUrl)URL.revokeObjectURL(aiState.fileUrl);aiState.file=file;aiState.fileUrl=URL.createObjectURL(file);$("#aiSpacePreview").src=aiState.fileUrl;$("#aiSpacePreviewWrap").classList.remove("hidden");$(".ai-upload").classList.add("hidden");aiUpdateStartEnabled();
});
$("#aiChangeSpace").onclick=()=>{$("#aiSpaceInput").click()};
$("#aiConsent").onchange=aiUpdateStartEnabled;
$("#aiIntentList").onclick=e=>{const b=e.target.closest(".ai-intent");if(!b)return;$$('#aiIntentList .ai-intent').forEach(x=>x.classList.toggle("on",x===b));aiState.intentCode=b.dataset.intent;aiState.intentLabel=b.dataset.label};
$("#aiStart").onclick=startAiExperience;
$("#aiProcessingClose").onclick=()=>toast("任务会继续处理，你稍后回来即可查看结果");
$("#aiRestart").onclick=async()=>{if(aiState.experienceId&&!aiState.selectedCandidateId&&(aiState.status!=="completed"||aiState.resultViewed))await traceAI("decision.abandoned",{reason:"restart_with_new_space"},"final");aiReset();$(".ai-upload").classList.remove("hidden");syncAiForCurrentArtwork()};
$("#aiCandidateGrid").onclick=async e=>{
  const card=e.target.closest("[data-candidate]");if(!card)return;const id=card.dataset.candidate;
  if(e.target.closest(".ai-accept")){
    card.classList.add("committed");aiState.selectedCandidateId=id;await traceAI("candidate.selected",{candidate_id:id},"post_preview");await traceAI("decision.committed",{candidate_id:id,decision:"accepted_preview"},"final");toast("已记住你认可的空间方案");return;
  }
  if(e.target.closest(".ai-reject")){card.querySelector(".ai-reject-reasons")?.classList.toggle("hidden");return}
  const reason=e.target.closest("[data-reason]");if(reason){card.classList.add("rejected");card.querySelector(".ai-reject-reasons")?.classList.add("hidden");await traceAI("candidate.rejected",{candidate_id:id,reason:{category:reason.dataset.category,code:reason.dataset.reason,text:reason.textContent}},"post_preview");toast("已记录这个判断")}
};

async function loadHotelStory(){
  const d=await api("/hotel/1/story");
  $("#hotelStory").textContent=(d.hotel.history||"")+" "+(d.hotel.positioning||"");
  $("#storySections").innerHTML=(d.story_sections||[]).map((x,i)=>`<div class="story-line"><span class="eyebrow light">0${i+1}</span><b>${esc(x.title)}</b><p>${esc(x.text)}</p></div>`).join("");
  const artifacts=(d.artifacts||[]);
  const gallery=(d.gallery||[]);
  $("#artifactGrid").innerHTML=artifacts.length?artifacts.map(x=>`<div class="artifact"><img src="${url(x.cover)}" alt="${esc(x.title)}"><div><b>${esc(x.title)}</b><span>${esc(x.code)} · ${esc(x.theme)}</span></div></div>`).join(""):`<div class="quiet">暂无已通过公开授权门禁的酒店文化物件。</div>`;
  $("#hotelGallery").innerHTML=gallery.length?gallery.map(x=>`<figure class="photo"><img loading="lazy" src="${url(x.file_path)}" alt="${esc(x.category)}"><span>${esc(x.category)}</span></figure>`).join(""):`<div class="quiet">暂无已通过公开授权门禁的酒店空间图片。</div>`;
  await sendTelemetry("story_view","hotel",d.hotel?.id||1,{surface:"story.tab"});
}
async function loadLive(){
  const d=await api("/exhibitions");
  if(!d.items?.length){$("#exhibitionList").innerHTML=`<section class="paper-card"><p class="story">酒店还没有发布展览。用户共创数据会先进入酒店后台，由运营人员确认后发布到这里。</p></section>`;return}
  $("#exhibitionList").innerHTML=d.items.map(ex=>`<section class="exhibition" data-exhibition-id="${esc(ex.id)}">
    <div class="exhibition-head"><div><span class="eyebrow">${esc(ex.theme||"锦江策展")}</span><h2>${esc(ex.title)}</h2></div><span class="exhibition-status">已发布</span></div>
    <p class="exhibition-copy">${esc(ex.description||"")}</p>
    <div class="ex-work-grid">${(ex.works||[]).map(w=>`<div class="ex-work"><img src="${url(w.cover)||""}" alt="${esc(w.title)}"><span>${esc(w.title)}</span></div>`).join("")}</div>
    ${(ex.activities||[]).map(a=>`<button type="button" class="activity-box" data-activity-id="${esc(a.id)}"><b>${esc(a.title)}</b> · ${esc(a.location||"锦江饭店")} · ${esc(a.status)}</button>`).join("")}
    ${ex.generated_from_votes?`<div class="cue" style="margin-bottom:0"><b>共创结果</b>这场展览由用户策展信号生成，并由酒店端确认发布。</div>`:""}
  </section>`).join("");
  const cards=$$("#exhibitionList [data-exhibition-id]");
  if("IntersectionObserver" in window){
    const io=new IntersectionObserver(entries=>{for(const entry of entries){if(entry.isIntersecting&&entry.intersectionRatio>=.4){sendTelemetry("exhibition_view","exhibition",entry.target.dataset.exhibitionId,{surface:"live.tab"});io.unobserve(entry.target)}}},{threshold:[.4]});
    cards.forEach(x=>io.observe(x));
  }else cards.forEach(x=>sendTelemetry("exhibition_view","exhibition",x.dataset.exhibitionId,{surface:"live.tab"}));
}
$("#exhibitionList").addEventListener("click",e=>{const b=e.target.closest("[data-activity-id]");if(!b)return;sendTelemetry("activity_click","activity",b.dataset.activityId,{surface:"live.activity"});toast("已记录你对这个活动的兴趣")});
async function loadMe(){
  const p=await api("/users/"+encodeURIComponent(USER)+"/profile");
  const s=p.stats||{};
  $("#myRecommendations").textContent=s.recommendations||0;$("#myLikes").textContent=s.likes||0;$("#myFavs").textContent=s.favorites||0;$("#myVotes").textContent=s.curation_votes||0;
  $("#myThemes").innerHTML=p.theme_preferences?.length?p.theme_preferences.map(x=>`<span class="preference">${esc(x.value)}<b>${Number(x.score).toFixed(1)}</b></span>`).join(""):`<span class="quiet">多做几次喜欢、收藏或共创选择后，这里会形成你的主题偏好。</span>`;
  $("#myFavorites").innerHTML=workGrid(p.favorite_items);
  $("#myCurated").innerHTML=workGrid(p.curated_items);
  $("#myContributions").innerHTML=(p.published_contributions||[]).map(x=>`<div class="contribution">你的选择已进入已发布展览：<b>${esc(x.title)}</b></div>`).join("");
}

const VIEWS=["today","space","live","me"];
async function go(name){
  $$(".nav button").forEach(b=>b.classList.toggle("on",b.dataset.view===name));
  VIEWS.forEach(v=>$("#view-"+v).classList.toggle("hidden",v!==name));
  window.scrollTo({top:0,behavior:"auto"});
  if(name==="space")await loadHotelStory()
  if(name==="live")await loadLive();
  if(name==="me")await loadMe();
}
$$(".nav button").forEach(b=>b.onclick=()=>go(b.dataset.view));
$$("[data-go]").forEach(b=>b.onclick=()=>go(b.dataset.go));

$("#demoToggle").onclick=()=>{
  const b=$("#demoToggle"),on=b.getAttribute("aria-pressed")!=="true";
  b.setAttribute("aria-pressed",String(on));$$("[data-cue]").forEach(x=>x.classList.toggle("hidden",!on));
  toast(on?"演示旁白已打开":"演示旁白已关闭");
};

loadAiService();
loadRecommendation();

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
