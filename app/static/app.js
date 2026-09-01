const USER = "demo-user";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const SOURCE = new URLSearchParams(location.search).get("source") || "direct";
const SESSION_KEY = "jinjiang_session_v32";
const makeId = () => (globalThis.crypto?.randomUUID ? crypto.randomUUID().replaceAll("-","") : (Date.now().toString(36)+Math.random().toString(36).slice(2)));
const SESSION = localStorage.getItem(SESSION_KEY) || ("sess-web-" + makeId().slice(0,16));
localStorage.setItem(SESSION_KEY, SESSION);

let current = null;
let currentRecommendation = null;
let currentSession = SESSION;
let loading = false;

async function api(path, options={}) {
  const r = await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  const data = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data));
  return data;
}
function esc(s){return String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function toast(msg){const el=$("#toast");el.textContent=msg;el.classList.add("on");clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove("on"),1800)}
function sendEvent(event,id=current?.id,metadata={}) {
  if(!id) return Promise.resolve();
  return api("/user-event",{method:"POST",body:JSON.stringify({
    user_id:USER,event,artwork_id:id,recommendation_id:currentRecommendation,
    session_id:currentSession,source_code:SOURCE,metadata
  })}).catch(()=>{});
}
function workGrid(items){
  if(!items?.length) return `<div class="quiet">还没有记录。</div>`;
  return items.map(x=>`<div class="mini-work"><img src="${x.cover||""}" alt="${esc(x.title)}"><span>${esc(x.title)}</span></div>`).join("");
}

async function loadRecommendation(exclude){
  if(loading)return;loading=true;
  try{
    const q=new URLSearchParams({user_id:USER,session_id:currentSession,source:SOURCE});
    if(exclude)q.set("exclude",exclude);
    const d=await api("/daily-recommendation?"+q.toString());
    current=d.artwork;currentRecommendation=d.recommendation_id;currentSession=d.session_id||currentSession;
    $("#sourceChip").textContent=d.source?.name||"今日锦江";
    $("#plateImg").src=current.cover;$("#plateImg").alt=current.title;
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
    $("#relatedList").innerHTML=(detail.related||[]).map(r=>`<figure data-open="${r.id}"><img src="${r.cover}" alt="${esc(r.title)}"><figcaption>${esc(r.title)}</figcaption></figure>`).join("");
    await sendEvent("impression",current.id);
  }catch(e){toast("推荐服务暂时不可用");console.error(e)}
  finally{loading=false}
}

$("#btnLike").onclick=async()=>{await sendEvent("like");$("#btnLike").classList.add("on");$("#btnDislike").classList.remove("on");toast("已记住你的喜欢")}
$("#btnFav").onclick=async()=>{await sendEvent("favorite");$("#btnFav").classList.add("on");toast("已收藏")}
$("#btnDislike").onclick=async()=>{await sendEvent("dislike");$("#btnDislike").classList.add("on");$("#btnLike").classList.remove("on");toast("已记录，下次会少一些类似内容")}
$("#btnChange").onclick=async()=>{if(!current)return;const old=current.id;await sendEvent("change",old);await loadRecommendation(old);toast("换了一条新的文化线索")}
$("#btnCurate").onclick=async()=>{
  if(!current)return;
  const r=await api("/curation-vote",{method:"POST",body:JSON.stringify({
    user_id:USER,artwork_id:current.id,vote:1,recommendation_id:currentRecommendation,
    session_id:currentSession,source_code:SOURCE
  })});
  $("#curateIdle").classList.add("hidden");$("#curateDone").classList.remove("hidden");
  $("#curateMeta").textContent=`这件作品目前累计 ${r.votes} 次共创选择。酒店端已经收到新的用户信号。`;
  toast("已加入锦江共创策展");
};

async function openSheet(id){
  await sendEvent("detail",id);
  const a=await api("/artworks/"+id+"?user_id="+encodeURIComponent(USER));
  $("#sheetImg").src=a.cover;$("#sheetImg").alt=a.title;
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

async function loadHotelStory(){
  const d=await api("/hotel/1/story");
  $("#hotelStory").textContent=(d.hotel.history||"")+" "+(d.hotel.positioning||"");
  $("#storySections").innerHTML=(d.story_sections||[]).map((x,i)=>`<div class="story-line"><span class="eyebrow light">0${i+1}</span><b>${esc(x.title)}</b><p>${esc(x.text)}</p></div>`).join("");
  $("#artifactGrid").innerHTML=(d.artifacts||[]).map(x=>`<div class="artifact"><img src="${x.cover}" alt="${esc(x.title)}"><div><b>${esc(x.title)}</b><span>${esc(x.code)} · ${esc(x.theme)}</span></div></div>`).join("");
  $("#hotelGallery").innerHTML=(d.gallery||[]).map(x=>`<figure class="photo"><img loading="lazy" src="${x.file_path}" alt="${esc(x.category)}"><span>${esc(x.category)}</span></figure>`).join("");
}
async function loadLive(){
  const d=await api("/exhibitions");
  if(!d.items?.length){$("#exhibitionList").innerHTML=`<section class="paper-card"><p class="story">酒店还没有发布展览。用户共创数据会先进入酒店后台，由运营人员确认后发布到这里。</p></section>`;return}
  $("#exhibitionList").innerHTML=d.items.map(ex=>`<section class="exhibition">
    <div class="exhibition-head"><div><span class="eyebrow">${esc(ex.theme||"锦江策展")}</span><h2>${esc(ex.title)}</h2></div><span class="exhibition-status">已发布</span></div>
    <p class="exhibition-copy">${esc(ex.description||"")}</p>
    <div class="ex-work-grid">${(ex.works||[]).map(w=>`<div class="ex-work"><img src="${w.cover||""}" alt="${esc(w.title)}"><span>${esc(w.title)}</span></div>`).join("")}</div>
    ${(ex.activities||[]).map(a=>`<div class="activity-box"><b>${esc(a.title)}</b> · ${esc(a.location||"锦江饭店")} · ${esc(a.status)}</div>`).join("")}
    ${ex.generated_from_votes?`<div class="cue" style="margin-bottom:0"><b>共创结果</b>这场展览由用户策展信号生成，并由酒店端确认发布。</div>`:""}
  </section>`).join("");
}
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

loadRecommendation();
