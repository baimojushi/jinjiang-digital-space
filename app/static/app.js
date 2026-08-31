/* 锦江数字空间 MVP 3.0 · 用户端
   页面主线：今日随机推荐 → 匹配度拆解 → AI 推荐理由与抽取轨迹 → 用户反馈 → 加入策展候选 */

const USER = "demo-user";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let current = null;      // 当前作品
let currentData = null;  // 当前推荐完整响应
let drawing = false;     // 抽取动画进行中

/* ------------------------------------------------------------------ 基础 */

async function api(path, options) {
  const r = await fetch(path, options ? { headers: { "Content-Type": "application/json" }, ...options } : undefined);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("on");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("on"), 1900);
}

function sendEvent(name, id = current && current.id) {
  if (!id) return Promise.resolve();
  return api("/user-event", {
    method: "POST",
    body: JSON.stringify({ user_id: USER, event: name, artwork_id: id })
  }).catch(() => {});
}

const wait = ms => new Promise(r => setTimeout(r, ms));

/* ------------------------------------------------------------------ 渲染 */

function renderLabel(d) {
  const a = d.artwork, L = d.label;
  $("#plateImg").src = a.cover;
  $("#plateImg").alt = `${a.title}｜${a.category}`;
  $("#plateNo").textContent = L.no;
  $("#plateTag").textContent = `今日推荐 · 第 ${d.sequence_no} 次`;
  $("#labelTheme").textContent = a.theme;
  $("#workTitle").textContent = a.title;
  $("#metaNo").textContent = L.no;
  $("#metaMedium").textContent = L.medium;
  $("#metaOrigin").textContent = L.origin;
  $("#metaCredit").textContent = L.credit;
  $("#workStory").textContent = a.story;
  $("#workTags").innerHTML = a.tags.map(t => `<span class="pill">${t}</span>`).join("");
  $("#stampDate").textContent = d.date.replace(/-/g, ".");
}

const SEG_CLASS = { brand: "seg-brand", region: "seg-region", theme: "seg-theme", style: "seg-style" };

function renderMatch(d) {
  const bd = d.score_breakdown;
  const pct = Math.round(Math.min(bd.total, 1) * 100);
  $("#matchValue").textContent = pct;

  const total = bd.items.reduce((s, i) => s + i.contribution, 0) + Math.max(0, bd.feedback_adjust);
  const seg = bd.items.map(i =>
    `<i class="${SEG_CLASS[i.key]}" style="width:${(i.contribution / total * 100).toFixed(2)}%" title="${i.label}"></i>`
  ).join("");
  const fb = bd.feedback_adjust > 0
    ? `<i class="seg-feedback" style="width:${(bd.feedback_adjust / total * 100).toFixed(2)}%" title="用户反馈修正"></i>` : "";
  $("#matchStack").innerHTML = seg + fb;

  const rows = bd.items.map(i => `
    <div class="legend-row">
      <span class="legend-key ${SEG_CLASS[i.key]}"></span>
      <span class="legend-name">${i.label}<small>${i.note}</small></span>
      <span class="legend-weight num">权重 ${Math.round(i.weight * 100)}%</span>
      <span class="legend-val num">${i.percent}</span>
    </div>`).join("");
  const fbRow = `
    <div class="legend-row">
      <span class="legend-key seg-feedback"></span>
      <span class="legend-name">用户反馈修正<small>${bd.feedback_note}</small></span>
      <span class="legend-weight num">实时</span>
      <span class="legend-val num">${bd.feedback_adjust >= 0 ? "+" : ""}${bd.feedback_adjust.toFixed(3)}</span>
    </div>`;
  $("#matchLegend").innerHTML = rows + fbRow;
  $("#matchCaption").textContent =
    `基础分 ${bd.base_score.toFixed(3)}，叠加用户行为修正 ${bd.feedback_adjust >= 0 ? "+" : ""}${bd.feedback_adjust.toFixed(3)}。`;
}

function renderReasons(d) {
  $("#reasonList").innerHTML = d.reason.map(x => `<li>${x}</li>`).join("");
  $("#traceSteps").innerHTML = d.trace.map(s => `
    <div class="trace-step">
      <span class="s-no">${s.step}</span>
      <span class="s-label">${s.label}<small>${s.detail}</small></span>
      <span class="s-val num">${s.value}<em>${s.unit}</em></span>
    </div>`).join("");
  $("#poolCount").textContent = `${d.pool_size} 件 · 保留匹配度前 15 名`;
}

function renderPool(d, { markPicked = true } = {}) {
  $("#poolStrip").innerHTML = d.pool_preview.map(p => `
    <div class="pool-cell ${markPicked && p.picked ? "picked on" : ""}" data-pid="${p.id}">
      <img src="${p.cover}" alt="${p.title}">
      <b>${Math.round(Math.min(p.match_score, 1) * 100)}</b>
    </div>`).join("");
}

function renderCurateState(d) {
  const s = d.curation_state || { votes: 0 };
  $("#curateIdle").classList.remove("hidden");
  $("#curateDone").classList.add("hidden");
  $("#curateNote").textContent = s.votes
    ? `已有 ${s.votes} 位用户把它推荐给锦江饭店，目前排在候选池第 ${s.rank} 位。`
    : "你的选择会直接进入锦江饭店的策展候选池，参与决定下一场展览。";
}

function renderRelated(list) {
  if (!list || !list.length) { $("#relatedList").innerHTML = ""; return; }
  $("#relatedList").innerHTML = list.map(r => `
    <figure data-open="${r.id}">
      <img src="${r.cover}" alt="${r.title}">
      <figcaption>${r.title}</figcaption>
    </figure>`).join("");
}

function resetFeedback() {
  ["#btnLike", "#btnDislike", "#btnFav"].forEach(s => $(s).classList.remove("on"));
}

function render(d) {
  currentData = d;
  current = d.artwork;
  renderLabel(d);
  renderMatch(d);
  renderReasons(d);
  renderPool(d);
  renderCurateState(d);
  resetFeedback();
  api("/artworks/" + current.id).then(a => renderRelated(a.related)).catch(() => {});
}

/* ------------------------------------------------------------------ 抽取动画 */

async function animateDraw(d) {
  const panelOpen = !$("#tracePanel").classList.contains("hidden");
  $("#plate").classList.add("loading");

  if (!REDUCED && panelOpen) {
    renderPool(d, { markPicked: false });
    const cells = $$("#poolStrip .pool-cell");
    const pickedIdx = d.pool_preview.findIndex(p => p.picked);
    const start = performance.now();
    // 前 700ms 高频跳动，之后减速，最后落在中签作品上
    while (performance.now() - start < 900) {
      const i = Math.floor(Math.random() * cells.length);
      cells.forEach(c => c.classList.remove("on"));
      cells[i].classList.add("on");
      const t = (performance.now() - start) / 900;
      await wait(45 + t * t * 110);
    }
    cells.forEach(c => c.classList.remove("on"));
    if (pickedIdx >= 0) {
      cells[pickedIdx].classList.add("on", "picked");
      cells[pickedIdx].scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
    }
    await wait(220);
  } else if (!REDUCED) {
    await wait(260);
  }

  render(d);
  $("#plate").classList.remove("loading");
}

/* ------------------------------------------------------------------ 数据加载 */

async function loadRecommendation(exclude) {
  const q = "/daily-recommendation?user_id=" + USER + (exclude ? "&exclude=" + exclude : "");
  const d = await api(q);
  if (exclude) {
    await animateDraw(d);
  } else {
    render(d);
  }
  sendEvent("impression", d.artwork.id);
  return d;
}

async function loadHotel() {
  const h = await api("/hotel/1");
  $("#hotelStory").textContent = h.history + h.positioning + "。";
  $("#hotelTags").innerHTML = h.keywords.map(t => `<span class="pill">${t}</span>`).join("");
  $("#hotelSpaces").innerHTML = h.spaces.map(s =>
    `<div class="tile"><b>${s.name}</b><p>${s.function}</p></div>`).join("");
}

async function loadLive() {
  const p = await api("/curation/proposal");
  $("#liveSource").textContent = p.status;
  if (!p.works.length) {
    $("#liveProposal").innerHTML =
      `<div class="empty"><b>候选池还是空的</b>回到今日推荐，把第一件作品送进来。</div>`;
    return;
  }
  $("#liveProposal").innerHTML = `
    <div class="proposal">
      <div class="label">${p.theme}</div>
      <h3>${p.title}</h3>
      <p class="p-statement">${p.statement}</p>
      <div class="proposal-works" style="grid-template-columns:repeat(3,1fr)">
        ${p.works.map(w => `<figure><img src="${w.cover}" alt="${w.title}">
          <figcaption>${w.title}<span class="v">${w.votes} 票</span></figcaption></figure>`).join("")}
      </div>
      <div class="route">
        ${p.route.map(r => `<div><div class="r-role">${r.role}</div>
          <div class="r-space">${r.space}</div><div class="r-note">${r.note}</div></div>`).join("")}
      </div>
      <div class="label" style="margin-bottom:10px">配套活动</div>
      <div class="next"><div>${p.activity.title}｜${p.activity.location}｜${p.activity.status}</div></div>
    </div>`;
}

const EFFECT = [
  { k: "like", label: "喜欢", w: "+0.035" },
  { k: "favorite", label: "收藏", w: "+0.050" },
  { k: "curation", label: "加入策展", w: "+0.080" },
  { k: "dislike", label: "不感兴趣", w: "−0.040" }
];

async function loadMe() {
  const a = await api("/analytics");
  $("#myLikes").textContent = a.likes || 0;
  $("#myFavs").textContent = a.favorites || 0;
  $("#myVotes").textContent = a.curation_votes || 0;
  $("#myChanges").textContent = a.changes || 0;
  const ev = a.events || {};
  $("#myEffect").innerHTML = EFFECT.map(e => `
    <div class="legend-row">
      <span class="legend-key" style="background:var(--ink-4)"></span>
      <span class="legend-name">${e.label}<small>每记录一次，该作品下一轮匹配度变化 ${e.w}</small></span>
      <span class="legend-weight num">${e.w}</span>
      <span class="legend-val num">${ev[e.k] || 0} 次</span>
    </div>`).join("");
}

/* ------------------------------------------------------------------ 交互 */

$("#btnLike").onclick = async () => {
  await sendEvent("like"); $("#btnLike").classList.add("on"); $("#btnDislike").classList.remove("on");
  toast("已记录喜欢，同类作品权重上调");
};
$("#btnDislike").onclick = async () => {
  await sendEvent("dislike"); $("#btnDislike").classList.add("on"); $("#btnLike").classList.remove("on");
  toast("已记录，同类作品权重下调");
};
$("#btnFav").onclick = async () => {
  await sendEvent("favorite"); $("#btnFav").classList.add("on");
  toast("已收藏");
};
$("#btnChange").onclick = async () => {
  if (drawing) return;
  drawing = true;
  $("#btnChange").disabled = true;
  try {
    const old = current.id;
    await sendEvent("change", old);
    await loadRecommendation(old);
    toast("已从高匹配候选池重新抽取");
  } finally {
    drawing = false;
    $("#btnChange").disabled = false;
  }
};

$("#traceToggle").onclick = () => {
  const panel = $("#tracePanel");
  const open = panel.classList.toggle("hidden") === false;
  $("#traceToggle").setAttribute("aria-expanded", String(open));
  $("#traceChev").textContent = open ? "收起 −" : "展开 +";
  if (open) sendEvent("reason_open");
};

$("#btnCurate").onclick = async () => {
  const r = await api("/curation-vote", {
    method: "POST",
    body: JSON.stringify({ user_id: USER, artwork_id: current.id, vote: 1 })
  });
  $("#curateIdle").classList.add("hidden");
  $("#curateDone").classList.remove("hidden");
  $("#curateMeta").innerHTML =
    `累计 <b>${r.votes}</b> 票，在 ${r.pool_total} 件候选中排第 <b>${r.rank}</b> 位。<br>酒店后台已同步更新。`;
  toast("已加入锦江饭店策展候选");
};

/* 详情抽屉 */
async function openSheet(id) {
  await sendEvent("detail", id);
  const a = await api("/artworks/" + id);
  $("#sheetImg").src = a.cover;
  $("#sheetImg").alt = a.title;
  $("#sheetTheme").textContent = a.theme;
  $("#sheetTitle").textContent = a.title;
  $("#sheetNo").textContent = a.label.no;
  $("#sheetMedium").textContent = a.label.medium;
  $("#sheetOrigin").textContent = a.label.origin;
  $("#sheetStory").textContent = a.story;
  $("#sheetReasons").innerHTML = a.reason.map(x => `<li>${x}</li>`).join("");
  $("#sheet").classList.remove("hidden");
}
$("#sheetClose").onclick = () => $("#sheet").classList.add("hidden");
$("#sheet").onclick = e => { if (e.target.id === "sheet") $("#sheet").classList.add("hidden"); };
$("#plate").onclick = () => current && openSheet(current.id);
$("#relatedList").onclick = e => {
  const fig = e.target.closest("[data-open]");
  if (fig) openSheet(Number(fig.dataset.open));
};
$("#poolStrip").onclick = e => {
  const cell = e.target.closest("[data-pid]");
  if (cell) openSheet(Number(cell.dataset.pid));
};

/* 视图切换 */
const VIEWS = ["today", "space", "live", "me"];
async function go(name) {
  $$(".nav button").forEach(b => b.classList.toggle("on", b.dataset.view === name));
  VIEWS.forEach(v => $("#view-" + v).classList.toggle("hidden", v !== name));
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  if (name === "space") await loadHotel();
  if (name === "live") await loadLive();
  if (name === "me") await loadMe();
}
$$(".nav button").forEach(b => b.onclick = () => go(b.dataset.view));
$$("[data-go]").forEach(el => el.onclick = () => go(el.dataset.go));

/* 演示旁白 */
$("#demoToggle").onclick = () => {
  const btn = $("#demoToggle");
  const on = btn.getAttribute("aria-pressed") !== "true";
  btn.setAttribute("aria-pressed", String(on));
  $$("[data-cue]").forEach(c => c.classList.toggle("hidden", !on));
  toast(on ? "演示旁白已打开" : "演示旁白已关闭");
};

/* 键盘快捷键：现场演示时不必精准点击 */
document.addEventListener("keydown", e => {
  if (e.target.matches("input,textarea")) return;
  const map = { r: "#btnChange", l: "#btnLike", f: "#btnFav", c: "#btnCurate", w: "#traceToggle", d: "#demoToggle" };
  const sel = map[e.key.toLowerCase()];
  if (sel) { e.preventDefault(); $(sel).click(); }
});

loadRecommendation().catch(err => {
  $("#workTitle").textContent = "推荐服务没有响应";
  $("#labelTheme").textContent = "连接失败";
  $("#matchCaption").textContent = "请确认后端已启动：python -m uvicorn app.main:app --port 8000";
  console.error(err);
});
