/* ============================================================
   锦江非遗数字空间 · 用户端行为补丁
   必须在 static/app.js 之后加载。
   app.js 顶层的 function 声明与 const/let 都在全局词法环境中，
   这里直接复用，不重写原文件。
   ============================================================ */
(function () {
  "use strict";
  const JJ = window.JJ;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];

  /* ---------------------------------------------------------
     1. 首屏图片：补 LCP 提示与加载骨架
     --------------------------------------------------------- */
  const plateImg = $("#plateImg");
  if (plateImg) {
    plateImg.setAttribute("fetchpriority", "high");
    plateImg.setAttribute("decoding", "async");
    const wrap = plateImg.closest(".hero-image-wrap");
    if (wrap) {
      wrap.classList.add("is-loading");
      plateImg.addEventListener("load", () => wrap.classList.remove("is-loading"));
      plateImg.addEventListener("error", () => wrap.classList.remove("is-loading"));
    }
  }

  /* ---------------------------------------------------------
     2. 详情弹层：Esc / 遮罩 / 焦点陷阱 / 背景滚动锁
        原实现只切 .hidden，键盘无法关闭，背景仍可滚动。
     --------------------------------------------------------- */
  const sheet = JJ.overlay("#sheet", { panel: ".sheet-inner", label: "作品详情" });
  if (sheet) {
    const closeBtn = $("#sheetClose");
    if (closeBtn) {
      closeBtn.setAttribute("aria-label", "关闭作品详情");
      closeBtn.onclick = () => sheet.close();
    }
    $("#sheet").onclick = null; // 交给 overlay 统一处理
    if (typeof window.openSheet === "function") {
      const rawOpen = window.openSheet;
      window.openSheet = async function (id) {
        try {
          await rawOpen(id);
          sheet.open();
        } catch (e) {
          JJ.toast("作品详情没有打开，请稍后重试", { error: true });
        }
      };
    }
  }

  /* ---------------------------------------------------------
     3. 主图可用键盘打开
        原来靠 <section id="plate"> 的 click，键盘与读屏用户完全够不到。
     --------------------------------------------------------- */
  const heroWrap = document.querySelector(".hero-image-wrap");
  if (heroWrap) {
    heroWrap.setAttribute("role", "button");
    heroWrap.setAttribute("tabindex", "0");
    heroWrap.setAttribute("aria-label", "查看作品详情");
    heroWrap.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (typeof current !== "undefined" && current) window.openSheet(current.id);
      }
    });
  }

  /* ---------------------------------------------------------
     4. 标签页语义 + 浏览器返回键
        原来切换视图不改 URL，安卓返回键会直接退出应用；
        导航也没有 aria-selected，读屏无法判断当前所在页。
     --------------------------------------------------------- */
  const VIEW_LABEL = { today: "今日推荐", space: "锦江故事", live: "正在发生", me: "我的偏好" };
  const nav = document.querySelector(".nav");
  if (nav) {
    nav.setAttribute("role", "tablist");
    nav.setAttribute("aria-label", "主导航");
    $$(".nav button").forEach((b) => {
      const v = b.dataset.view;
      b.setAttribute("role", "tab");
      b.id = "tab-" + v;
      b.setAttribute("aria-controls", "view-" + v);
      b.setAttribute("aria-selected", String(b.classList.contains("on")));
      b.setAttribute("aria-label", VIEW_LABEL[v] || v);
    });
    Object.keys(VIEW_LABEL).forEach((v) => {
      const panel = document.getElementById("view-" + v);
      if (!panel) return;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", "tab-" + v);
      panel.classList.add("view-panel");
    });
  }

  if (typeof window.go === "function") {
    const rawGo = window.go;
    let navigating = false;
    window.go = async function (name, opts) {
      const silentHistory = opts && opts.fromHistory;
      try {
        await rawGo(name);
      } catch (e) {
        const panel = document.getElementById("view-" + name);
        if (panel) {
          JJ.showError(
            panel.querySelector("#exhibitionList") || panel,
            "这一页的数据没有加载出来。",
            () => window.go(name)
          );
        }
        JJ.toast("加载失败，请检查网络后重试", { error: true });
      }
      $$(".nav button").forEach((b) =>
        b.setAttribute("aria-selected", String(b.dataset.view === name))
      );
      if (!silentHistory && !navigating) {
        const target = "#" + name;
        if (location.hash !== target) history.pushState({ view: name }, "", target);
      }
    };
    window.addEventListener("popstate", (e) => {
      const name = (e.state && e.state.view) || (location.hash || "#today").slice(1);
      if (!VIEW_LABEL[name]) return;
      navigating = true;
      window.go(name, { fromHistory: true }).finally(() => (navigating = false));
    });
    const initial = (location.hash || "").slice(1);
    if (VIEW_LABEL[initial] && initial !== "today") window.go(initial, { fromHistory: true });
    else history.replaceState({ view: "today" }, "", location.hash || "#today");
  }

  /* ---------------------------------------------------------
     5. 反馈按钮：补 aria-pressed；写入失败时不再假装成功
        原 sendEvent 用 .catch(()=>{}) 吞掉所有错误，
        用户看到「已收藏」但数据库里没有记录 —— 这条链路正是本产品的核心资产。
     --------------------------------------------------------- */
  if (typeof window.sendEvent === "function") {
    const rawSend = window.sendEvent;
    window.sendEvent = function (event, id, metadata) {
      const target = id != null ? id : typeof current !== "undefined" && current ? current.id : null;
      const p = rawSend(event, id, metadata);
      return Promise.resolve(p).then((r) => {
        if (r && r.ok === true) return r;
        // 只有在确有目标作品、却没拿到 ok 的情况下才算写入失败
        if (target && ["like", "favorite", "dislike"].includes(event)) {
          JJ.toast("这次选择没有保存成功，请稍后再试", { error: true });
          return null;
        }
        return r;
      });
    };
  }

  const FB = [
    ["#btnLike", "喜欢这件作品"],
    ["#btnFav", "收藏这件作品"],
    ["#btnDislike", "对这件作品不感兴趣"],
    ["#btnChange", "换一件作品"],
  ];
  FB.forEach(([sel, label]) => {
    const b = $(sel);
    if (!b) return;
    b.setAttribute("aria-label", label);
    if (sel !== "#btnChange") b.setAttribute("aria-pressed", "false");
  });
  ["#btnLike", "#btnFav", "#btnDislike"].forEach((sel) => {
    const b = $(sel);
    if (!b) return;
    const raw = b.onclick;
    b.onclick = async (e) => {
      await raw.call(b, e);
      $$(".fb[aria-pressed]").forEach((x) =>
        x.setAttribute("aria-pressed", String(x.classList.contains("on")))
      );
    };
  });

  /* ---------------------------------------------------------
     6. 换一幅 / 加入策展：忙碌态 + 错误呈现
        原来两个按钮都能连点；loadRecommendation 内部的 loading 标志
        只是提前 return，change 事件却已经写进了 user_events，
        直接抬高漏斗里的「换一幅」计数。
     --------------------------------------------------------- */
  const btnChange = $("#btnChange");
  if (btnChange) {
    const raw = btnChange.onclick;
    btnChange.onclick = JJ.guard(btnChange, async (e) => {
      try {
        await raw.call(btnChange, e);
      } catch (err) {
        JJ.toast("换一幅没有成功，请稍后重试", { error: true });
      }
    });
  }
  const btnCurate = $("#btnCurate");
  if (btnCurate) {
    const raw = btnCurate.onclick;
    btnCurate.onclick = JJ.guard(btnCurate, async (e) => {
      try {
        await raw.call(btnCurate, e);
      } catch (err) {
        JJ.toast(err && err.message ? err.message : "加入策展没有成功，请稍后重试", { error: true });
      }
    });
  }

  /* ---------------------------------------------------------
     7. 空间照片上传：键盘可达 + 拖拽 + 尺寸提示
        原 input 用 display:none，label 无 tabindex，键盘完全无法触发选择；
        视觉上是一个虚线拖拽区，却没有实现拖拽。
     --------------------------------------------------------- */
  const upload = document.querySelector(".ai-upload");
  const fileInput = $("#aiSpaceInput");
  if (upload && fileInput) {
    upload.setAttribute("tabindex", "0");
    upload.setAttribute("role", "button");
    upload.setAttribute("aria-label", "上传空间照片，支持 JPG、PNG，最大 18MB");
    upload.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });
    ["dragenter", "dragover"].forEach((t) =>
      upload.addEventListener(t, (e) => {
        e.preventDefault();
        upload.classList.add("is-dragover");
      })
    );
    ["dragleave", "drop"].forEach((t) =>
      upload.addEventListener(t, (e) => {
        e.preventDefault();
        upload.classList.remove("is-dragover");
      })
    );
    upload.addEventListener("drop", (e) => {
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      const dt = new DataTransfer();
      dt.items.add(f);
      fileInput.files = dt.files;
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  /* ---------------------------------------------------------
     8. 开始生成按钮：说明禁用原因
        原来只有 opacity:.42，用户无从知道差什么。
     --------------------------------------------------------- */
  const startBtn = $("#aiStart");
  if (startBtn) {
    const hint = document.createElement("small");
    hint.className = "jj-hint";
    hint.id = "aiStartHint";
    startBtn.insertAdjacentElement("afterend", hint);
    startBtn.setAttribute("aria-describedby", "aiStartHint");
    const sync = () => {
      const needFile = !(typeof aiState !== "undefined" && aiState.file);
      const needConsent = !$("#aiConsent").checked;
      const off = typeof aiState !== "undefined" && !aiState.serviceEnabled;
      hint.textContent = off
        ? "AI 空间体验当前不可用。"
        : needFile && needConsent
        ? "上传一张空间照片并勾选数据使用说明后即可生成。"
        : needFile
        ? "还差一张空间照片。"
        : needConsent
        ? "请先勾选数据使用说明。"
        : "";
    };
    ["change", "input"].forEach((t) => document.addEventListener(t, sync, true));
    new MutationObserver(sync).observe(startBtn, { attributes: true, attributeFilter: ["disabled"] });
    sync();
  }

  const processingClose = $("#aiProcessingClose");
  if (processingClose) {
    // 原按钮点了只弹一句提示，不产生任何状态变化；改成真正收起处理面板
    processingClose.textContent = "先去看别的，稍后回来查看";
    processingClose.onclick = () => {
      const card = $("#aiSpaceCard");
      if (card) card.scrollIntoView({ block: "start", behavior: JJ.reduceMotion ? "auto" : "smooth" });
      JJ.toast("任务会继续处理，回到这里就能看到结果");
    };
  }

  /* ---------------------------------------------------------
     9. AI 轮询：退避 + 上限 + 页面不可见时暂停
        原实现固定 8s 轮询、失败后 10s 重试，且没有终止条件，
        标签页留着不动就会一直打服务端。
     --------------------------------------------------------- */
  if (typeof window.pollAiExperience === "function") {
    const rawPoll = window.pollAiExperience;
    let rounds = 0;
    const MAX_ROUNDS = 90; // 约 15 分钟后停止
    window.pollAiExperience = async function (immediate) {
      if (document.visibilityState === "hidden") {
        if (typeof aiClearPoll === "function") aiClearPoll();
        aiState.pollTimer = setTimeout(() => window.pollAiExperience(), 15000);
        return;
      }
      if (++rounds > MAX_ROUNDS) {
        if (typeof aiClearPoll === "function") aiClearPoll();
        JJ.toast("AI 任务耗时超出预期，稍后刷新页面即可继续查看", { error: true });
        return;
      }
      const r = await rawPoll(immediate);
      // 在原有定时器基础上做线性退避，减少长任务的空转请求
      if (aiState.pollTimer && rounds > 6) {
        clearTimeout(aiState.pollTimer);
        const delay = Math.min(30000, 8000 + (rounds - 6) * 2000);
        aiState.pollTimer = setTimeout(() => window.pollAiExperience(), delay);
      }
      return r;
    };
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && typeof aiState !== "undefined" && aiState.experienceId && aiState.status !== "completed") {
        if (typeof aiClearPoll === "function") aiClearPoll();
        window.pollAiExperience();
      }
    });
  }

  /* ---------------------------------------------------------
     10. 演示旁白：切换时不再突兀跳动，并补上状态说明
     --------------------------------------------------------- */
  const demoToggle = $("#demoToggle");
  if (demoToggle) demoToggle.setAttribute("aria-label", "切换演示旁白说明");

  /* ---------------------------------------------------------
     11. 视差水印
     app.js 里的原实现已经在 window 上挂了 scroll 监听且无法解绑，
     这里把节点整体换成克隆体：旧监听写入的是已脱离文档的节点，不再生效；
     新节点交给 JJ.parallax，走 translate3d 并尊重 reduce-motion。
     --------------------------------------------------------- */
  const oldWm = document.getElementById("brandWatermark");
  if (oldWm && oldWm.parentNode) {
    const fresh = oldWm.cloneNode(true);
    fresh.removeAttribute("style");
    oldWm.parentNode.replaceChild(fresh, oldWm);
  }
  JJ.parallax("brandWatermark", 0.5);
})();
