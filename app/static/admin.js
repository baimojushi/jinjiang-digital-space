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
function toast(m){const e=$("#toast");e.textContent=m;e.classList.add("on");clearTimeout(toast.t);toast.t=setTimeout(()=>e.classList.remove("on"),1800)}
let currentProposal=null;

function renderKpi(k,ex){
 const data=[
  ["会话",k.sessions,"数字入口访问"],
  ["用户",k.users,"匿名ID去重"],
  ["推荐",k.recommendations,"每次推荐独立记录"],
  ["喜欢",k.likes,"强兴趣信号"],
  ["共创选择",k.curation_votes,"进入策展候选"],
  ["共创转化",k.curation_rate+"%","推荐用户→共创"]
 ];
 $("#kpis").innerHTML=data.map(x=>`<div class="kpi"><span>${x[0]}</span><b>${x[1]}</b><small>${x[2]}</small></div>`).join("");
}
function renderFunnel(f){$("#funnel").innerHTML=f.map(x=>`<div class="f-row"><span class="f-name">${esc(x.label)}</span><div class="track"><div class="fill" style="width:${x.rate}%"></div></div><span class="f-value">${x.value} · ${x.rate}%</span></div>`).join("")}
function renderThemes(ts){const max=Math.max(1,...ts.map(x=>Math.max(0,x.weight)));$("#themeBars").innerHTML=ts.map(x=>`<div><div class="bar-top"><span>${esc(x.name)}</span><b>${x.share}%</b></div><div class="bar"><i style="width:${Math.max(0,x.weight)/max*100}%"></i></div></div>`).join("")}
function renderSources(items){$("#sourceBody").innerHTML=items.map(x=>`<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.scene)}</td><td>${x.sessions}</td><td>${x.recommendations}</td><td>${x.strong_sessions}</td><td>${x.curation_sessions}</td><td>${x.strong_rate}%</td></tr>`).join("")}
function renderContent(items){$("#contentBody").innerHTML=items.map(x=>`<tr><td><div class="work"><img src="${url(x.cover)||""}"><div><b>${esc(x.title)}</b><small>${esc(x.asset_code||"")}</small></div></div></td><td>${esc(x.theme)}</td><td>${x.exposures}</td><td>${x.details}</td><td>${x.likes}</td><td>${x.favorites}</td><td>${x.votes}</td><td><b>${x.interest_score}</b></td></tr>`).join("")}
function renderCandidates(pool){
 $("#signalList").innerHTML=(pool.user_signal_items||[]).slice(0,12).map(x=>`<div class="candidate"><img src="${url(x.cover)||""}"><div><b>${esc(x.title)}</b><span>${esc(x.theme)} · ${x.exposures}次曝光 · ${x.curation_votes}票</span></div><div class="score">${x.interest_score}<small>兴趣热度</small></div></div>`).join("")||`<div class="empty">还没有用户行为数据。</div>`;
 $("#internalList").innerHTML=(pool.internal_candidates||[]).slice(0,18).map(x=>`<div class="candidate"><img src="${url(x.cover)||""}"><div><b>${esc(x.title)}</b><span>${esc(x.collection_name||"内部资源")} · ${esc(x.building||"楼宇待定")}</span></div><div class="score" style="font-size:10px">${esc(x.rights_status)}<small>${esc(x.readiness)}</small></div></div>`).join("");
}
function renderDiagnostics(d){
 $("#diagnostics").innerHTML=`<div class="diag-head"><span class="diag-chip">算法版本 ${esc(d.algorithm_version)}</span><span class="diag-chip">Top-N ${d.top_n}</span><span class="diag-chip">品牌 ${Math.round(d.weights.brand*100)}%</span><span class="diag-chip">地域 ${Math.round(d.weights.region*100)}%</span><span class="diag-chip">主题 ${Math.round(d.weights.theme*100)}%</span><span class="diag-chip">风格 ${Math.round(d.weights.style*100)}%</span></div><div class="diag-list">${d.items.map(x=>`<div class="diag-row"><span>${esc(x.asset_code)} · ${esc(x.title)}</span><b>${x.exposures} 次曝光</b></div>`).join("")}</div>`;
}
function renderProposal(p){
 currentProposal=p;
 if(!p.works?.length){$("#proposalBox").className="empty";$("#proposalBox").textContent="当前没有足够的用户共创数据。先注入演示数据或在用户端产生真实选择。";$("#btnPublish").disabled=true;return}
 $("#proposalBox").className="proposal";
 $("#proposalBox").innerHTML=`<span class="eyebrow">${esc(p.theme)}</span><h3>${esc(p.title)}</h3><p>${esc(p.statement)}</p><div class="proposal-works">${p.works.map(w=>`<figure><img src="${url(w.cover)||""}"><figcaption>${esc(w.title)} · ${w.votes}票</figcaption></figure>`).join("")}</div><p>${esc(p.status||"")}。草稿已冻结当前用户共创快照；只有运营确认后才会发布到用户端“正在发生”。</p>`;
 $("#btnPublish").disabled=p.proposal_status==="published";
}
async function refresh(){
 const [d,pool,diag]=await Promise.all([api("/analytics/dashboard"),api("/curation-pool"),api("/recommendation-diagnostics")]);
 renderKpi(d.kpi,d.exhibitions);renderFunnel(d.funnel);renderThemes(d.themes);renderSources(d.sources);renderContent(d.top_artworks);renderCandidates(pool);renderDiagnostics(diag);
}
$("#btnSeed").onclick=async()=>{const b=$("#btnSeed");b.disabled=true;try{const r=await api("/demo/seed",{method:"POST",body:JSON.stringify({users:72,days:7})});toast(r.message);await refresh()}finally{b.disabled=false}}
$("#btnReset").onclick=async()=>{await api("/demo/reset",{method:"POST",body:"{}"});currentProposal=null;$("#proposalBox").className="empty";$("#proposalBox").textContent="行为数据已清空。文化资产和已发布展览保留。";$("#btnPublish").disabled=true;toast("行为数据已清空");await refresh()}
$("#btnProposal").onclick=async()=>{renderProposal(await api("/curation/proposal/draft",{method:"POST",body:"{}"}))}
$("#btnPublish").onclick=async()=>{if(!currentProposal?.proposal_id)return;const r=await api("/curation/proposal/publish",{method:"POST",body:JSON.stringify({proposal_id:currentProposal.proposal_id,title:currentProposal.title,period:"待排期"})});toast(r.idempotent?"该策展草稿已经发布，无需重复创建":"展览已发布到用户端“正在发生”");$("#btnPublish").disabled=true;currentProposal.proposal_status="published";await refresh()}
refresh();

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
