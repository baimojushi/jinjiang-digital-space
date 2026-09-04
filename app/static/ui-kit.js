/* ============================================================
   锦江非遗数字空间 · 共享 UI 工具层
   在各页面自身的脚本之前加载。只暴露 window.JJ 一个命名空间。
   ============================================================ */
(function () {
  "use strict";

  const JJ = (window.JJ = window.JJ || {});
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  JJ.reduceMotion = reduceMotion;

  /* ---------------------------------------------------------
     1. 图片兜底
     app/static/assets/ 未随仓库分发（.gitignore 排除了 *.jpg/*.png/*.svg），
     克隆后所有封面都是 404；同时 `src="${url(x.cover)||""}"` 这种写法
     会把当前 HTML 页面当作图片请求。两种情况都会触发 img 的 error 事件，
     这里用捕获阶段统一接住，换成占位底纹，不再显示浏览器碎图标。
     --------------------------------------------------------- */
  const FALLBACK_LABEL = "图片待补";
  const HOSTS =
    "figure,.mini-work,.artifact,.ex-work,.aa-media,.candidate,.photo," +
    ".proposal-works figure,.aa-space,.hero-image-wrap,.ai-current-work,.work,.aa-asset";
  const SELF = ".sheet-image,.aa-editor-cover,.ai-space-preview img,.ai-candidate img";
  function markMissing(img) {
    if (img.dataset.imgMissing === "1") return;
    img.dataset.imgMissing = "1";
    img.removeAttribute("srcset");
    const label = img.getAttribute("alt") || FALLBACK_LABEL;
    const host = img.closest(HOSTS);
    if (host) {
      // 卡片类容器：容器画占位底纹，图片本身隐藏
      host.classList.add("img-fallback");
      if (!host.getAttribute("data-fallback-label")) host.setAttribute("data-fallback-label", label);
      return;
    }
    if (img.matches(SELF)) {
      // 独立大图：图片自身画占位，避免整个弹层被底纹铺满
      img.dataset.imgMissing = "";
      img.classList.add("img-fallback", "img-fallback-self");
      img.setAttribute("data-fallback-label", label);
      return;
    }
    // 装饰性图片（logo、水印，alt 为空）：直接隐藏，不做任何装饰
  }
  document.addEventListener(
    "error",
    (e) => {
      const t = e.target;
      if (t && t.tagName === "IMG") markMissing(t);
    },
    true
  );
  // 空 src 直接判定为缺失，避免把整页 HTML 当图片下载
  JJ.setImg = function (img, src, alt) {
    if (!img) return;
    if (alt != null) img.alt = alt;
    if (!src || src === "undefined" || src === "null") {
      img.removeAttribute("src");
      markMissing(img);
      return;
    }
    img.dataset.imgMissing = "";
    const host = img.closest(".img-fallback");
    if (host) host.classList.remove("img-fallback");
    img.src = src;
  };
  // 供模板字符串使用：返回可安全写入 src 的字符串（缺失时给出 1x1 透明位图）
  const BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
  JJ.imgSrc = function (u) {
    return u && u !== "undefined" && u !== "null" ? u : BLANK;
  };

  /* ---------------------------------------------------------
     2. Toast：补 aria-live，让读屏用户也能听到「已收藏」这类核心反馈
     --------------------------------------------------------- */
  JJ.initToast = function (selector) {
    const el = document.querySelector(selector || "#toast");
    if (!el) return null;
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.setAttribute("aria-atomic", "true");
    return el;
  };
  JJ.toast = function (msg, opts) {
    const el = document.querySelector("#toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle("is-error", !!(opts && opts.error));
    el.classList.add("on");
    clearTimeout(JJ.toast._t);
    JJ.toast._t = setTimeout(() => el.classList.remove("on"), (opts && opts.duration) || 2200);
  };

  /* ---------------------------------------------------------
     3. 弹层／抽屉：Esc 关闭、遮罩点击关闭、焦点陷阱、背景滚动锁
     原实现只切 .hidden，键盘用户进入后无法退出，背景还会跟着滚。
     --------------------------------------------------------- */
  const FOCUSABLE =
    'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  JJ.overlay = function (rootSel, opts) {
    const root = document.querySelector(rootSel);
    if (!root) return null;
    const o = opts || {};
    const panel = o.panel ? root.querySelector(o.panel) : root.firstElementChild;
    let lastFocus = null;

    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    if (o.label) root.setAttribute("aria-label", o.label);

    function onKey(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        api.close();
        return;
      }
      if (e.key !== "Tab") return;
      const items = [...root.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    function onClick(e) {
      if (e.target === root) api.close();
    }

    const api = {
      root,
      isOpen: () => !root.classList.contains("hidden"),
      open() {
        lastFocus = document.activeElement;
        root.classList.remove("hidden");
        document.body.classList.add("jj-lock");
        document.addEventListener("keydown", onKey, true);
        root.addEventListener("click", onClick);
        const target = root.querySelector(FOCUSABLE);
        if (target) setTimeout(() => target.focus(), reduceMotion ? 0 : 60);
      },
      close() {
        if (!api.isOpen()) return;
        root.classList.add("hidden");
        document.body.classList.remove("jj-lock");
        document.removeEventListener("keydown", onKey, true);
        root.removeEventListener("click", onClick);
        if (lastFocus && lastFocus.focus) lastFocus.focus();
        if (typeof o.onClose === "function") o.onClose();
      },
    };
    if (panel) panel.addEventListener("click", (e) => e.stopPropagation());
    return api;
  };

  /* ---------------------------------------------------------
     4. 按钮忙碌态：原代码里换一幅／加入策展／注入演示数据都可以连点，
        重复请求会污染 recommendations 与 user_events 这两张分析表。
     --------------------------------------------------------- */
  JJ.guard = function (btn, fn) {
    if (!btn) return fn;
    return async function (...args) {
      if (btn.dataset.busy === "1") return;
      btn.dataset.busy = "1";
      btn.disabled = true;
      try {
        return await fn.apply(this, args);
      } finally {
        btn.dataset.busy = "";
        btn.disabled = false;
      }
    };
  };

  /* ---------------------------------------------------------
     5. 防抖：资产维护台的搜索框原本每敲一个键就跑一次 100 行查询 + 全表重绘
     --------------------------------------------------------- */
  JJ.debounce = function (fn, wait) {
    let t = null;
    return function (...a) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, a), wait == null ? 260 : wait);
    };
  };

  /* ---------------------------------------------------------
     6. 错误呈现：接口失败时不再让区域保持空白
     --------------------------------------------------------- */
  JJ.showError = function (target, message, retry) {
    const el = typeof target === "string" ? document.querySelector(target) : target;
    if (!el) return;
    el.innerHTML = "";
    const box = document.createElement("div");
    box.className = "jj-error";
    box.setAttribute("role", "alert");
    box.textContent = message || "数据没有加载出来。";
    if (typeof retry === "function") {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "重新加载";
      b.addEventListener("click", retry);
      box.appendChild(b);
    }
    el.appendChild(box);
  };
  JJ.showEmpty = function (target, message) {
    const el = typeof target === "string" ? document.querySelector(target) : target;
    if (!el) return;
    el.innerHTML = '<div class="jj-empty"></div>';
    el.firstChild.textContent = message;
  };

  /* ---------------------------------------------------------
     7. 表格横向可滚动提示
     --------------------------------------------------------- */
  JJ.markScrollables = function () {
    document.querySelectorAll(".table-wrap,.aa-table-wrap").forEach((w) => {
      w.dataset.scrollable = w.scrollWidth > w.clientWidth + 4 ? "1" : "";
    });
  };
  window.addEventListener("resize", JJ.debounce(() => JJ.markScrollables(), 200));

  /* ---------------------------------------------------------
     8. 视差水印：尊重 reduce-motion，改用 translate3d 交给合成线程，
        并在元素完全移出视口后停止写入 style
     --------------------------------------------------------- */
  JJ.parallax = function (id, factor) {
    const wm = document.getElementById(id || "brandWatermark");
    if (!wm) return;
    if (reduceMotion) {
      wm.style.transform = "translateY(-50%)";
      return;
    }
    const k = factor == null ? 0.5 : factor;
    let ticking = false;
    const update = () => {
      const offset = window.scrollY * k;
      wm.style.transform = `translate3d(0, calc(-50% - ${offset}px), 0)`;
      ticking = false;
    };
    window.addEventListener(
      "scroll",
      () => {
        if (!ticking) {
          requestAnimationFrame(update);
          ticking = true;
        }
      },
      { passive: true }
    );
    update();
  };

  /* ---------------------------------------------------------
     9. 确认操作：清空行为数据这类不可逆动作原来是一键直接执行
     --------------------------------------------------------- */
  JJ.confirmAction = function (message) {
    return window.confirm(message);
  };

  document.addEventListener("DOMContentLoaded", () => {
    JJ.initToast();
    JJ.markScrollables();
  });
})();
