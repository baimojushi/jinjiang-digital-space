/* ============================================================
   锦江非遗数字空间 · 后台行为补丁
   同时服务 /admin 与 /asset-admin，必须在各自的业务脚本之后加载。
   ============================================================ */
(function () {
  "use strict";
  const JJ = window.JJ;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const isOps = !!$(".admin");
  const isAsset = !!$(".asset-admin");

  /* ---------------------------------------------------------
     0. 通用：toast 容器、装饰性图片 alt、外链 rel、视差
     缺陷：后台大量 <img> 没有 alt，读屏会逐字念出文件路径；
          资产维护台完全没有 toast，失败一律弹 alert 阻塞操作。
     --------------------------------------------------------- */
  if (!$("#toast")) {
    const t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    document.body.appendChild(t);
    JJ.initToast();
  }
  const fixImgs = () => {
    $$("img:not([alt])").forEach((i) => i.setAttribute("alt", ""));
    $$('a[target="_blank"]:not([rel])').forEach((a) => a.setAttribute("rel", "noopener"));
  };
  new MutationObserver(fixImgs).observe(document.body, { childList: true, subtree: true });
  fixImgs();

  const oldWm = document.getElementById("brandWatermark");
  if (oldWm && oldWm.parentNode) {
    const fresh = oldWm.cloneNode(true);
    fresh.removeAttribute("style");
    oldWm.parentNode.replaceChild(fresh, oldWm);
  }
  JJ.parallax("brandWatermark", 0.5);

  /* =========================================================
     文化运营后台 /admin
     ========================================================= */
  if (isOps && typeof window.refresh === "function") {
    const rawRefresh = window.refresh;
    window.refresh = async function () {
      try {
        await rawRefresh();
        JJ.markScrollables();
        fillEmpty();
      } catch (e) {
        JJ.showError("#kpis", "看板数据没有加载出来，可能是后端未启动或接口报错。", () =>
          window.refresh()
        );
        JJ.toast("看板加载失败", { error: true });
      }
    };

    // 缺陷：无数据时漏斗、主题、渠道、内容四块渲染成纯空白，运营无法判断
    // 是「还没有人用」还是「页面坏了」。
    function fillEmpty() {
      const cases = [
        ["#funnel", "还没有推荐记录。先注入演示数据，或让用户端产生真实访问。"],
        ["#themeBars", "还没有足够行为形成主题偏好。"],
        ["#sourceBody", null],
        ["#contentBody", null],
        ["#internalList", "内部策展资源为空。"],
      ];
      cases.forEach(([sel, msg]) => {
        const el = $(sel);
        if (!el || el.children.length) return;
        if (msg) JJ.showEmpty(el, msg);
        else if (el.tagName === "TBODY")
          el.innerHTML = `<tr><td colspan="8" style="padding:22px;text-align:center;color:var(--muted)">暂无数据</td></tr>`;
      });
    }

    // 缺陷：清空行为数据是不可逆动作，原来一次点击直接执行。
    const btnReset = $("#btnReset");
    if (btnReset) {
      const raw = btnReset.onclick;
      btnReset.onclick = JJ.guard(btnReset, async (e) => {
        if (!JJ.confirmAction("将清空全部推荐、行为、偏好与共创数据。文化资产与已发布展览保留。确定继续？"))
          return;
        try {
          await raw.call(btnReset, e);
        } catch (err) {
          JJ.toast("清空失败：" + (err.message || ""), { error: true });
        }
      });
    }

    const btnSeed = $("#btnSeed");
    if (btnSeed) {
      const raw = btnSeed.onclick;
      btnSeed.onclick = JJ.guard(btnSeed, async (e) => {
        JJ.toast("正在注入演示数据，约需数秒");
        try {
          await raw.call(btnSeed, e);
        } catch (err) {
          JJ.toast("注入失败：" + (err.message || ""), { error: true });
        }
      });
    }

    const btnProposal = $("#btnProposal");
    if (btnProposal) {
      const raw = btnProposal.onclick;
      btnProposal.onclick = JJ.guard(btnProposal, async (e) => {
        try {
          await raw.call(btnProposal, e);
        } catch (err) {
          JJ.showError("#proposalBox", "策展预案没有生成成功。", () => btnProposal.click());
        }
      });
    }

    // 缺陷：发布后 currentProposal 未清空，再点一次「生成策展预案」就能
    // 用同一份数据重复发布，服务端没有去重，会产生重复展览。
    const btnPublish = $("#btnPublish");
    if (btnPublish) {
      const raw = btnPublish.onclick;
      btnPublish.onclick = JJ.guard(btnPublish, async (e) => {
        if (!JJ.confirmAction("发布后用户端「正在发生」会立即出现这场展览。确认发布？")) return;
        try {
          await raw.call(btnPublish, e);
          if (typeof currentProposal !== "undefined") currentProposal = null;
          btnPublish.disabled = true;
          const box = $("#proposalBox");
          if (box) {
            box.className = "empty";
            box.textContent = "展览已发布。如需再发布一场，请先重新生成策展预案。";
          }
        } catch (err) {
          JJ.toast("发布失败：" + (err.message || ""), { error: true });
        }
      });
    }
  }

  /* =========================================================
     数字资产维护台 /asset-admin
     ========================================================= */
  if (isAsset) {
    // 缺陷：授权状态筛选缺 public_domain_verified 与 expired。
    // public_domain_verified 是仅有的两个可公开状态之一，运营无法按它筛选。
    const rightsSel = $("#rights");
    if (rightsSel && !rightsSel.querySelector('option[value="public_domain_verified"]')) {
      [
        ["public_domain_verified", "公版已核验"],
        ["expired", "已到期"],
      ].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = t;
        rightsSel.appendChild(o);
      });
    }

    // 缺陷：搜索框每敲一个键就发一次 100 行查询并重绘整张表，
    // 还会重新绑定每一行的 onclick。改为防抖 + 事件委托。
    const q = $("#q");
    if (q && typeof window.loadAssets === "function") {
      const fresh = q.cloneNode(true); // 换节点以摘掉原来的 input 监听
      q.parentNode.replaceChild(fresh, q);
      fresh.setAttribute("aria-label", "按作品名、编号、作者或来源搜索");
      fresh.addEventListener(
        "input",
        JJ.debounce(() => window.loadAssets(), 300)
      );
    }
    const body = $("#assetBody");
    if (body && typeof window.openAsset === "function") {
      body.addEventListener("click", (e) => {
        const row = e.target.closest(".aa-row");
        if (row) window.openAsset(+row.dataset.id);
      });
      body.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        const row = e.target.closest(".aa-row");
        if (row) window.openAsset(+row.dataset.id);
      });
    }

    // 缺陷：抽屉只能靠右上角 × 关闭，点遮罩无反应，Esc 无反应，无焦点管理。
    const drawer = JJ.overlay("#drawer", { panel: ".aa-drawer-card", label: "资产编辑" });
    if (drawer) {
      const close = $("#drawerClose");
      if (close) {
        close.setAttribute("aria-label", "关闭编辑面板");
        close.onclick = () => drawer.close();
      }
      ["openAsset", "openSpace"].forEach((name) => {
        if (typeof window[name] !== "function") return;
        const raw = window[name];
        window[name] = async function (...a) {
          try {
            const r = await raw.apply(this, a);
            drawer.open();
            renderGateChips();
            return r;
          } catch (e) {
            JJ.toast("详情没有打开：" + (e.message || ""), { error: true });
          }
        };
      });
      // asset-admin.js 里保存空间后会直接 classList.add("hidden")，
      // 绕过 overlay.close()，会把 body 的滚动锁留在页面上。这里做兜底同步。
      new MutationObserver(() => {
        if (drawer.root.classList.contains("hidden")) document.body.classList.remove("jj-lock");
      }).observe(drawer.root, { attributes: true, attributeFilter: ["class"] });
    }

    // 缺陷：公开门禁列把多条阻断原因 join(" / ") 塞进一个 border-radius:999px
    // 的胶囊里，长文本会把表格撑破。改成并排短标签。
    function renderGateChips() {
      $$("#assetBody .aa-status.block").forEach((el) => {
        if (el.dataset.chipped === "1") return;
        const parts = el.textContent.split(" / ").filter(Boolean);
        if (parts.length < 2) return;
        const wrap = document.createElement("div");
        wrap.className = "aa-gate-list";
        parts.forEach((p) => {
          const s = document.createElement("span");
          s.className = "aa-status block";
          s.dataset.chipped = "1";
          s.textContent = p;
          wrap.appendChild(s);
        });
        el.replaceWith(wrap);
      });
    }

    // 缺陷：列表写死 page_size=100 且从不展示 total，资产超过 100 条会静默截断。
    // 这里只读已渲染的行数，不再重复请求同一份 100 行数据。
    const PAGE_SIZE = 100;
    if (typeof window.loadAssets === "function") {
      const raw = window.loadAssets;
      window.loadAssets = async function () {
        try {
          await raw();
          renderGateChips();
          JJ.markScrollables();
          const rows = $$("#assetBody .aa-row").length;
          let note = $("#assetCountNote");
          if (!note) {
            note = document.createElement("p");
            note.id = "assetCountNote";
            note.style.cssText = "margin:10px 2px 0;font-size:12px;color:var(--inkbrown)";
            $("#assetBody").closest(".aa-panel").appendChild(note);
          }
          note.textContent =
            rows >= PAGE_SIZE
              ? `已显示前 ${PAGE_SIZE} 条，可能还有更多。请用上方筛选缩小范围。`
              : `当前筛选共 ${rows} 条，已全部显示。`;
          if (!rows) {
            $("#assetBody").innerHTML =
              '<tr><td colspan="5" style="padding:26px;text-align:center;color:var(--muted)">没有匹配的资产。调整筛选条件试试。</td></tr>';
            note.textContent = "";
          }
        } catch (e) {
          JJ.showError(
            $("#assetBody").closest(".aa-table-wrap"),
            "资产列表没有加载出来。",
            () => window.loadAssets()
          );
        }
      };
    }

    if (typeof window.refreshAll === "function") {
      const raw = window.refreshAll;
      window.refreshAll = async function () {
        try {
          await raw();
        } catch (e) {
          JJ.toast("部分数据没有加载出来，请刷新重试", { error: true });
        }
        JJ.markScrollables();
      };
    }

    // 缺陷：重算候选匹配是 O(资产×空间) 的全量重写，原来只 disable 按钮、
    // 结果用 alert 弹出，操作期间没有任何进度反馈。
    const recompute = $("#recompute");
    if (recompute) {
      const raw = recompute.onclick;
      recompute.onclick = JJ.guard(recompute, async (e) => {
        JJ.toast("正在重算候选匹配");
        try {
          await raw.call(recompute, e);
        } catch (err) {
          JJ.toast("重算失败：" + (err.message || ""), { error: true });
        }
      });
    }

    // 缺陷：保存失败走 window.alert，与其它页面的 toast 反馈不一致且阻塞。
    const nativeAlert = window.alert;
    window.alert = function (msg) {
      const text = String(msg == null ? "" : msg);
      if (/失败|错误/.test(text)) JJ.toast(text, { error: true, duration: 3600 });
      else JJ.toast(text);
    };
    window.alert.native = nativeAlert;
  }
})();
