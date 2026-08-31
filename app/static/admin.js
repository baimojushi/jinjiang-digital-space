/* 锦江数字空间 MVP 3.0 · 酒店端运营后台
   全部图表为手写 SVG，不依赖任何外部图表库，断网也能演示。 */

const $ = s => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
let autoTimer = null;

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
  toast._t = setTimeout(() => el.classList.remove("on"), 2000);
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------------ KPI */

const KPI_DEFS = [
  { key: "total_events", name: "累计行为", note: k => `覆盖 ${k.unique_artworks} 件作品` },
  { key: "unique_users", name: "参与用户", note: () => "匿名用户 ID 去重" },
  { key: "curation_votes", name: "加入策展", note: k => `来自 ${k.unique_users} 位用户` },
  { key: "curation_rate", name: "共创转化率", note: () => "看到推荐 → 加入策展", suffix: "%" },
  { key: "favorites", name: "收藏", note: k => `喜欢 ${k.likes} 次` },
  { key: "changes", name: "换一件", note: () => "衡量推荐新鲜度需求" }
];

function renderKpi(k) {
  $("#kpis").innerHTML = KPI_DEFS.map(d => `
    <div class="kpi">
      <span>${d.name}</span>
      <b class="num">${k[d.key] ?? 0}${d.suffix || ""}</b>
      <i>${d.note(k)}</i>
    </div>`).join("");
}

/* ------------------------------------------------------------------ 时序折线 */

function renderTimeline(tl) {
  const svg = $("#chartTimeline");
  const W = 620, H = 230, L = 38, R = 10, T = 14, B = 26;
  const pw = W - L - R, ph = H - T - B;
  const total = tl.series.total, cur = tl.series.curation;
  const max = Math.max(4, ...total) * 1.15;
  const n = total.length;
  const x = i => L + (n === 1 ? pw / 2 : i * pw / (n - 1));
  const y = v => T + ph - (v / max) * ph;

  const parts = [];
  // 网格与刻度
  for (let g = 0; g <= 3; g++) {
    const v = max * g / 3, yy = y(v);
    parts.push(`<line class="grid" x1="${L}" y1="${yy.toFixed(1)}" x2="${W - R}" y2="${yy.toFixed(1)}"/>`);
    parts.push(`<text class="tick" x="${L - 7}" y="${(yy + 3.5).toFixed(1)}" text-anchor="end">${Math.round(v)}</text>`);
  }
  parts.push(`<line class="axis" x1="${L}" y1="${T + ph}" x2="${W - R}" y2="${T + ph}"/>`);

  const step = n > 8 ? 2 : 1;
  tl.labels.forEach((lb, i) => {
    if (i % step === 0 || i === n - 1) {
      parts.push(`<text class="tick" x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(lb)}</text>`);
    }
  });

  const line = total.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  parts.push(`<path class="area" d="${line} L${x(n - 1).toFixed(1)},${T + ph} L${x(0).toFixed(1)},${T + ph} Z"/>`);
  parts.push(`<path class="line" d="${line}"/>`);
  const line2 = cur.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  parts.push(`<path class="line-2" d="${line2}"/>`);
  total.forEach((v, i) => parts.push(
    `<circle class="dot" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.6"><title>${esc(tl.labels[i])}：${v} 次行为</title></circle>`));

  svg.innerHTML = parts.join("");
  const unitName = { minute: "按分钟", hour: "按小时", day: "按天" }[tl.unit] || "";
  $("#tlUnit").textContent = `${unitName}统计，最近 ${n} 个时间段`;
}

/* ------------------------------------------------------------------ 漏斗 */

function renderFunnel(f) {
  const rows = [];
  f.forEach((s, i) => {
    if (i > 0) {
      const prev = f[i - 1].value;
      const drop = prev ? Math.round((1 - s.value / prev) * 100) : 0;
      rows.push(`<div class="drop">↓ 流失 ${drop}%</div>`);
    }
    rows.push(`
      <div class="funnel-row">
        <span class="f-name">${esc(s.label)}</span>
        <div class="funnel-track"><div class="funnel-fill step-${i}" style="width:${s.rate}%"></div></div>
        <span class="f-val"><b class="num">${s.value}</b> · ${s.rate}%</span>
      </div>`);
  });
  $("#funnel").innerHTML = rows.join("");
}

/* ------------------------------------------------------------------ 主题条 */

function renderThemes(themes, baseline) {
  $("#themeBars").innerHTML = themes.map(t => `
    <div class="tbar-row">
      <div class="t-top"><span>${esc(t.name)}</span><b class="num">${t.share}%</b></div>
      <div class="tbar-track">
        <div class="tbar-fill" style="width:${Math.min(100, t.share)}%"></div>
        <div class="baseline" style="left:${baseline}%"></div>
      </div>
    </div>`).join("");
}

/* ------------------------------------------------------------------ 标签热度 */

function renderTags(tags) {
  if (!tags.length) { $("#tagCloud").innerHTML = `<span style="border:0;color:var(--ink-4)">还没有足够的行为数据</span>`; return; }
  const max = Math.max(...tags.map(t => t.weight));
  $("#tagCloud").innerHTML = tags.map((t, i) => {
    const s = 12 + (t.weight / max) * 13;
    return `<span class="${i < 3 ? "hot" : ""}" style="font-size:${s.toFixed(1)}px">${esc(t.tag)}<em style="font-style:normal;font-family:var(--mono);font-size:10px;opacity:.6;margin-left:6px">${t.weight}</em></span>`;
  }).join("");
}

/* ------------------------------------------------------------------ 集中度 */

function renderGauge(c) {
  $("#gauge").innerHTML = `
    <div class="g-val num">${c.lead_share}<em>%</em></div>
    <div class="g-sub">
      领先主题《${esc(c.lead_theme)}》占全部策展票的 ${c.lead_share}%，
      是三主题均分基线 ${c.uniform_baseline}% 的 <b class="num">${c.lift}</b> 倍。<br>
      候选作品 ${c.voted_artworks} 件，前三名合计 ${c.top3_share}%，赫芬达尔指数 ${c.hhi}。
    </div>
    <div class="g-verdict">${esc(c.verdict)}</div>`;
}

/* ------------------------------------------------------------------ 热度榜 */

function renderRank(top) {
  if (!top.length) { $("#rankList").innerHTML = `<div class="empty"><b>还没有作品被互动</b>打开用户端产生几次行为，或点击"注入演示数据"。</div>`; return; }
  const max = Math.max(...top.map(t => t.score), 1);
  $("#rankList").innerHTML = top.map((t, i) => `
    <div class="rankrow">
      <span class="r-no">${String(i + 1).padStart(2, "0")}</span>
      <img src="${t.cover}" alt="${esc(t.title)}">
      <div>
        <div class="r-name">${esc(t.title)} <span class="label" style="margin-left:6px">${esc(t.theme)}</span></div>
        <div class="r-bar"><i style="width:${Math.max(3, t.score / max * 100)}%"></i></div>
      </div>
      <span class="r-score num">${t.score}<em>${t.votes} 票 / ${t.favorites} 收藏</em></span>
    </div>`).join("");
}

/* ------------------------------------------------------------------ 候选池表 */

function renderPool(items) {
  $("#poolBody").innerHTML = items.slice(0, 12).map((x, i) => `
    <tr>
      <td><span class="rank-badge ${i < 3 ? "top" : ""}">${String(i + 1).padStart(2, "0")}</span></td>
      <td><div class="work"><img src="${x.cover}" alt=""><span>${esc(x.title)}</span></div></td>
      <td><span class="pill">${esc(x.theme)}</span></td>
      <td class="n">${x.curation_votes}</td>
      <td class="n">${x.favorites}</td>
      <td class="n">${x.likes}</td>
      <td class="n">${Math.round(Math.min(x.match_score, 1) * 100)}%</td>
      <td class="n"><b>${x.score}</b></td>
    </tr>`).join("");
}

/* ------------------------------------------------------------------ 主题展方案 */

function renderProposal(p) {
  if (!p.works.length) {
    $("#proposalBox").innerHTML = `<div class="empty"><b>候选池还是空的</b>先让用户产生几次"加入策展"，再生成方案。</div>`;
    return;
  }
  $("#proposalBox").innerHTML = `
    <div class="proposal">
      <div class="label">${esc(p.theme)}　·　${esc(p.status)}</div>
      <h3>${esc(p.title)}</h3>
      <p class="p-statement">${esc(p.statement)}</p>
      <div class="proposal-works">
        ${p.works.map(w => `<figure><img src="${w.cover}" alt="${esc(w.title)}">
          <figcaption>${esc(w.title)}<span class="v">${w.votes} 票 · 热度 ${w.score}</span></figcaption></figure>`).join("")}
      </div>
      <div class="route">
        ${p.route.map(r => `<div><div class="r-role">${esc(r.role)}</div>
          <div class="r-space">${esc(r.space)}</div><div class="r-note">${esc(r.note)}</div></div>`).join("")}
      </div>
      <div class="label" style="margin:0 0 10px">配套活动</div>
      <div class="next" style="margin-bottom:20px">
        <div>${esc(p.activity.title)}｜${esc(p.activity.type)}｜${esc(p.activity.location)}｜可容纳 ${p.activity.capacity} 人｜${esc(p.activity.status)}</div>
      </div>
      <div class="label" style="margin:0 0 10px">下一步</div>
      <div class="next">${p.next_actions.map(a => `<div>${esc(a)}</div>`).join("")}</div>
    </div>`;
}

/* ------------------------------------------------------------------ 主流程 */

async function refresh() {
  try {
    const [db, pool] = await Promise.all([api("/analytics/dashboard"), api("/curation-pool")]);
    renderKpi(db.kpi);
    renderTimeline(db.timeline);
    renderFunnel(db.funnel);
    renderThemes(db.themes, db.concentration.uniform_baseline);
    renderTags(db.tags);
    renderGauge(db.concentration);
    renderRank(db.top_artworks);
    renderPool(pool.items);
    $("#stamp").textContent = db.generated_at.replace("T", " ");
  } catch (e) {
    toast("读取数据失败，请确认后端已启动");
    console.error(e);
  }
}

$("#btnSeed").onclick = async () => {
  const b = $("#btnSeed"); b.disabled = true; b.textContent = "注入中…";
  try {
    const r = await api("/demo/seed", { method: "POST", body: JSON.stringify({ users: 68, days: 7 }) });
    await refresh();
    toast(r.message);
  } finally { b.disabled = false; b.textContent = "注入演示数据"; }
};

$("#btnReset").onclick = async () => {
  const r = await api("/demo/reset", { method: "POST", body: "{}" });
  $("#proposalBox").innerHTML = `<div class="empty"><b>还没有生成方案</b>点下面的按钮，用当前候选池数据生成一份主题展方案。</div>`;
  await refresh();
  toast(r.message);
};

$("#btnProposal").onclick = async () => {
  const b = $("#btnProposal"); b.disabled = true; b.textContent = "生成中…";
  try {
    renderProposal(await api("/curation/proposal"));
    $("#proposalBox").scrollIntoView({ behavior: "smooth", block: "nearest" });
    toast("已根据当前候选池生成方案");
  } finally { b.disabled = false; b.textContent = "重新生成方案"; }
};

$("#btnAuto").onclick = () => {
  const b = $("#btnAuto");
  const on = b.getAttribute("aria-pressed") !== "true";
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "自动刷新 开" : "自动刷新 关";
  if (on) { autoTimer = setInterval(refresh, 4000); } else { clearInterval(autoTimer); }
};

$("#btnCue").onclick = () => {
  const b = $("#btnCue");
  const on = b.getAttribute("aria-pressed") !== "true";
  b.setAttribute("aria-pressed", String(on));
  document.querySelectorAll("[data-cue]").forEach(c => c.classList.toggle("hidden", !on));
  toast(on ? "演示旁白已打开" : "演示旁白已关闭");
};

/* 现场演示快捷键：s 注入数据、x 清空、g 生成方案、d 旁白 */
document.addEventListener("keydown", e => {
  if (e.target.matches && e.target.matches("input,textarea")) return;
  const map = { s: "#btnSeed", x: "#btnReset", g: "#btnProposal", d: "#btnCue" };
  const sel = map[e.key.toLowerCase()];
  if (sel) { e.preventDefault(); $(sel).click(); }
});

refresh();
autoTimer = setInterval(refresh, 4000);
