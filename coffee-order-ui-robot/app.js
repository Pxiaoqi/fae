/* 智魔方点单系统前端（动态菜单） */
"use strict";

const grid = document.getElementById("grid");
const brandTitle = document.getElementById("brandTitle");
const pendingOrdersEl = document.getElementById("pendingOrders");
const clearPendingBtn = document.getElementById("clearPendingBtn");
const toastEl = document.getElementById("toast");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const editBtn = document.getElementById("editBtn");
const pureBtn = document.getElementById("pureBtn");
const pureExit = document.getElementById("pureExit");
const todayBtn = document.getElementById("todayBtn");
const drawerMask = document.getElementById("drawerMask");
const todayDrawer = document.getElementById("todayDrawer");
const drawerClose = document.getElementById("drawerClose");
const drawerDate = document.getElementById("drawerDate");
const drawerTotal = document.getElementById("drawerTotal");
const drawerOrders = document.getElementById("drawerOrders");
const timingSwitch = document.getElementById("timingSwitch");
const timingSection = document.getElementById("timingSection");
const timingSwitchLabel = document.getElementById("timingSwitchLabel");
const timingRules = document.getElementById("timingRules");
const startTemplate = document.getElementById("startTemplate");
const startPath = document.getElementById("startPath");
const startPathAdd = document.getElementById("startPathAdd");
const startNode = document.getElementById("startNode");
const startResolved = document.getElementById("startResolved");
const endTemplate = document.getElementById("endTemplate");
const endPath = document.getElementById("endPath");
const endPathAdd = document.getElementById("endPathAdd");
const endNode = document.getElementById("endNode");
const endResolved = document.getElementById("endResolved");
const ruleSave = document.getElementById("ruleSave");
const tabMenu = document.getElementById("tabMenu");
const tabTiming = document.getElementById("tabTiming");
const paneMenu = document.getElementById("paneMenu");
const paneTiming = document.getElementById("paneTiming");
const drinkEditMask = document.getElementById("drinkEditMask");
const drinkEditTitle = document.getElementById("drinkEditTitle");
const drinkTags = document.getElementById("drinkTags");
const drinkTagAdd = document.getElementById("drinkTagAdd");
const drinkDisabled = document.getElementById("drinkDisabled");
const drinkDisabledLabel = document.getElementById("drinkDisabledLabel");
const drinkHint = document.getElementById("drinkHint");
const drinkEditClose = document.getElementById("drinkEditClose");
const drinkEditCancel = document.getElementById("drinkEditCancel");
const drinkEditSave = document.getElementById("drinkEditSave");
const modalMask = document.getElementById("modalMask");
const mCats = document.getElementById("mCats");
const mDrinks = document.getElementById("mDrinks");
const mSaveBtn = document.getElementById("mSave");

let MENU = null;
let activeCatId = null;
let EDITOR = null;
let EDITOR_ACTIVE = null;
let editorPromise = null;
let pureMode = false;
const counts = Object.create(null);
const CLICK_COOLDOWN_MS = 1000;           // 卡片点击冷却：1 秒
const lastOrderAt = Object.create(null);  // 每个饮品最近一次下单时间
const lastBlockAt = Object.create(null);  // 拦截提示节流
let toastTimer = null;
let recentTimer = null;

/* ---------- 动态菜单 ---------- */
async function loadMenu() {
  try {
    const res = await fetch("/api/menu", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.status !== "ok" || !data.categories || !data.categories.length) {
      toast("菜单加载失败：" + (data.error || data.menu_cfg_error || "配置异常"), true);
      return;
    }
    MENU = data;
    brandTitle.textContent = data.title || "智魔方点单系统";
    document.title = data.title || "智魔方点单系统";
    if (recentTimer) clearInterval(recentTimer);
    recentTimer = setInterval(() => {
      fetchPendingOrders();
    }, data.poll_interval_ms || 3000);
    const initial = MENU.active_category || MENU.categories[0].id;
    switchCategory(initial);
  } catch (err) {
    toast("菜单加载失败，请检查服务", true);
  }
}

function switchCategory(id) {
  if (!MENU) return;
  const cat = MENU.categories.find((c) => c.id === id);
  if (!cat) return;
  activeCatId = id;
  document.body.dataset.cat = cat.id;
  renderGrid(cat);
}

function renderGrid(cat) {
  grid.innerHTML = "";
  grid.className = `grid ${cat.layout === "6x2" ? "grid-6" : "grid-4"}`;
  cat.drinks.forEach((d, i) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `card ${d.color || "grad-coffee"}${d.disabled ? " disabled" : ""}`;
    card.dataset.type = d.type;
    card.style.animationDelay = `${Math.min(i * 35, 300)}ms`;
    card.innerHTML = `
      ${d.group_name ? `<span class="group-chip">${d.group_name}</span>` : ""}
      ${d.tags && d.tags.length ? `<span class="tags">${d.tags.map((t) => `<span class="tag${t.includes("酒精") ? " tag-alcohol" : ""}">${t}</span>`).join("")}</span>` : ""}
      <span class="icon">${d.icon || cat.icon}</span>
      <span class="name">${d.chinese}</span>
      <span class="en">${d.name}</span>
      ${d.hint ? `<span class="note">${d.hint}</span>` : ""}
      <span class="hint">${d.disabled ? (d.hint || "暂时无法下单") : "点击下单"}</span>
      <span class="badge" data-badge="${d.type}">0</span>
    `;
    card.addEventListener("click", () => placeOrder(d, cat));
    grid.appendChild(card);
  });
}

/* ---------- 编辑模块与饮品绑定 ---------- */
editBtn.addEventListener("click", openEditor);
document.getElementById("mCancel").addEventListener("click", closeEditor);
document.getElementById("mClose").addEventListener("click", closeEditor);
mSaveBtn.addEventListener("click", saveEditor);
modalMask.addEventListener("click", (e) => {
  if (e.target === modalMask) closeEditor();
});

/* ---------- 纯净点单模式（全屏只显示卡片） ---------- */
pureBtn.addEventListener("click", enterPure);
pureExit.addEventListener("click", exitPure);

function enterPure() {
  if (pureMode) return;
  pureMode = true;
  document.body.classList.add("pure");
  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(() => {});
  }
}

function exitPure() {
  if (!pureMode) return;
  pureMode = false;
  document.body.classList.remove("pure");
  if (document.exitFullscreen) {
    document.exitFullscreen().catch(() => {});
  }
}

function switchCategoryByStep(step) {
  if (!MENU || !MENU.categories.length) return;
  const idx = MENU.categories.findIndex((c) => c.id === activeCatId);
  const next = MENU.categories[(idx + step + MENU.categories.length) % MENU.categories.length];
  switchCategory(next.id);
}

document.addEventListener("keydown", (e) => {
  if (!pureMode) return;
  if (e.key === "Escape") {
    exitPure();
  } else if (e.key === "ArrowLeft") {
    switchCategoryByStep(-1);
  } else if (e.key === "ArrowRight") {
    switchCategoryByStep(1);
  }
});

let swipeX = null;
grid.addEventListener("touchstart", (e) => {
  swipeX = e.touches[0].clientX;
}, { passive: true });
grid.addEventListener("touchend", (e) => {
  if (!pureMode || swipeX === null) return;
  const dx = e.changedTouches[0].clientX - swipeX;
  if (Math.abs(dx) > 60) {
    switchCategoryByStep(dx < 0 ? 1 : -1);
  }
  swipeX = null;
}, { passive: true });

/* 页面加载时预取编辑器数据；force=true 时强制刷新 */
async function loadEditor(force) {
  if (force) editorPromise = null;
  if (editorPromise) return editorPromise;
  editorPromise = (async () => {
    try {
      const res = await fetch("/api/editor", { cache: "no-store" });
      const data = await res.json();
      if (!res.ok || data.status !== "ok") {
        editorPromise = null; // 允许下次重试
        toast("编辑器数据加载失败", true);
        return null;
      }
      EDITOR = data;
      return data;
    } catch (_) {
      editorPromise = null;
      toast("编辑器数据加载失败", true);
      return null;
    }
  })();
  return editorPromise;
}

async function openEditor() {
  modalMask.hidden = false;
  if (EDITOR && EDITOR.categories && EDITOR.categories.length) {
    EDITOR_ACTIVE = (MENU && MENU.active_category) || EDITOR.categories[0].id; // 默认当前饮品类型
    renderEditor(); // 用预取数据秒开
    fetchTiming();  // 编辑弹窗内加载制作时长设置
    loadEditor(true).then(() => {
      if (!modalMask.hidden && EDITOR) renderEditor(); // 后台刷新
    });
    return;
  }
  // 预取还没完成：先显示加载态，数据就绪后立即渲染
  mCats.innerHTML = '<div class="m-loading">正在加载菜单数据…</div>';
  mDrinks.innerHTML = "";
  await loadEditor();
  if (modalMask.hidden || !EDITOR) return;
  EDITOR_ACTIVE = (MENU && MENU.active_category)
    || (EDITOR.categories && EDITOR.categories[0] ? EDITOR.categories[0].id : null);
  renderEditor();
  fetchTiming();
}

function switchEditorTab(which) {
  const isTiming = which === "timing";
  tabMenu.classList.toggle("active", !isTiming);
  tabTiming.classList.toggle("active", isTiming);
  paneMenu.hidden = isTiming;
  paneTiming.hidden = !isTiming;
  if (isTiming) fetchTiming();
}

tabMenu.addEventListener("click", () => switchEditorTab("menu"));
tabTiming.addEventListener("click", () => switchEditorTab("timing"));

function closeEditor() {
  modalMask.hidden = true;
}

function renderEditor() {
  if (!EDITOR) return;
  mCats.innerHTML = "";
  for (const c of EDITOR.categories) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "m-cat";
    b.dataset.cid = c.id;
    b.innerHTML = `<span class="m-cat-icon">${c.icon}</span>${c.name}`;
    if (c.id === EDITOR_ACTIVE) b.classList.add("active");
    b.addEventListener("click", () => {
      EDITOR_ACTIVE = c.id;
      renderEditor();
    });
    mCats.appendChild(b);
  }

  const cat = EDITOR.categories.find((c) => c.id === EDITOR_ACTIVE);
  if (!cat) return;

  document.querySelectorAll('input[name="mLayout"]').forEach((r) => {
    r.checked = r.value === cat.layout;
  });

  mDrinks.innerHTML = "";
  for (const d of EDITOR.all_drinks) {
    const li = document.createElement("li");
    const checked = cat.bound_types.includes(d.type);
    li.innerHTML = `
      <label class="m-drink ${checked ? "checked" : ""}">
        <input type="checkbox" data-type="${d.type}" ${checked ? "checked" : ""}>
        ${d.icon ? `<span class="m-drink-icon">${d.icon}</span>` : ""}
        <span class="m-name">${d.chinese}</span>
        ${checked ? '<span class="m-check">✓</span>' : ""}
        <span class="m-sub">type ${d.type}${d.tags && d.tags.length ? " · " + d.tags.join("/") : ""}${d.disabled ? " · 缺货" : ""}</span>
        <button class="m-edit" type="button" title="编辑饮品">✎</button>
      </label>`;
    const input = li.querySelector("input");
    input.addEventListener("change", () => {
      let iconEl = li.querySelector(".m-check");
      if (input.checked && !iconEl) {
        iconEl = document.createElement("span");
        iconEl.className = "m-check";
        iconEl.textContent = "✓";
        const sub = li.querySelector(".m-sub");
        if (sub) {
          sub.before(iconEl);
        } else {
          li.querySelector("label").appendChild(iconEl);
        }
      } else if (!input.checked && iconEl) {
        iconEl.remove();
      }
      li.classList.toggle("checked", input.checked);
    });
    li.querySelector(".m-edit").addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openDrinkEdit(d);
    });
    mDrinks.appendChild(li);
  }
}

async function saveEditor() {
  if (!EDITOR) {
    openEditor(); // 弹窗数据未加载时先加载
    return;
  }
  if (mSaveBtn.disabled) return; // 防止重复提交
  const cat = EDITOR.categories.find((c) => c.id === EDITOR_ACTIVE);
  if (!cat) return;
  const layout = (document.querySelector('input[name="mLayout"]:checked') || {}).value || cat.layout;
  const drinks = [...mDrinks.querySelectorAll('input[type="checkbox"]:checked')]
    .map((i) => Number(i.dataset.type));
  const payload = {
    categories: { [cat.id]: { layout, drinks } },
  };
  const originalText = mSaveBtn.textContent;
  mSaveBtn.disabled = true;
  mSaveBtn.classList.add("saving");
  mSaveBtn.textContent = "保存中…";
  try {
    const res = await fetch("/api/editor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      toast("保存失败：" + (data.error || "未知错误"), true);
      return;
    }
    toast("✅ 已保存，菜单已更新");
    closeEditor();
    loadEditor(true); // 后台刷新编辑器数据
    await loadMenu();
    switchCategory(MENU.active_category || cat.id);
  } catch (_) {
    toast("保存失败：网络错误", true);
  } finally {
    mSaveBtn.disabled = false;
    mSaveBtn.classList.remove("saving");
    mSaveBtn.textContent = originalText;
  }
}

/* ---------- 下单 ---------- */
async function placeOrder(drink, cat) {
  const card = grid.querySelector(`[data-type="${drink.type}"]`);
  if (!card || card.classList.contains("ordering")) return;
  if (drink.disabled) {
    toast(drink.hint || "该饮品暂时无法下单", true);
    return;
  }
  const now = Date.now();
  if (now - (lastOrderAt[drink.type] || 0) < CLICK_COOLDOWN_MS) {
    // 1 秒内重复点击：拦截 + 轻微视觉提示（提示本身也节流）
    card.classList.remove("blocked");
    void card.offsetWidth;
    card.classList.add("blocked");
    setTimeout(() => card.classList.remove("blocked"), 320);
    if (now - (lastBlockAt[drink.type] || 0) >= 1000) {
      lastBlockAt[drink.type] = now;
      toast("操作太快，请稍候再试", true);
    }
    return;
  }
  lastOrderAt[drink.type] = now;
  card.classList.add("ordering");

  try {
    const res = await fetch("/api/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: drink.type, quantity: 1 }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      toast(`下单失败：${data.error || "未知错误"}`, true);
      return;
    }

    counts[drink.type] = (counts[drink.type] || 0) + 1;
    const badge = card.querySelector(`[data-badge="${drink.type}"]`);
    badge.textContent = counts[drink.type];
    badge.classList.remove("show");
    void badge.offsetWidth; // 重新触发动画
    badge.classList.add("show");

    const code = (data.pickup_codes && data.pickup_codes[0]) || "----";
    toast(`✅ ${drink.chinese} 下单成功 · 取餐码 ${code}${(!drink.disabled && drink.hint) ? " · " + drink.hint : ""}`);
    fetchPendingOrders();
    if (!drawerMask.hidden) { // 统计面板打开时同步刷新
      fetchTodayOrders();
    }
  } catch (err) {
    toast("网络错误，请确认服务已启动", true);
  } finally {
    card.classList.remove("ordering");
  }
}

/* ---------- 最近下单（服务端订单日志，时间以容器/服务端为准） ---------- */
function formatTime(tsMs) {
  if (!tsMs) return "--:--:--";
  const d = new Date(Number(tsMs));
  if (isNaN(d.getTime())) return "--:--:--";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function statusLabel(status) {
  if (!status) return "已处理";
  if (status === "pending") return "待制作";
  if (status === "executing" || status === "processing" || status === "making") return "制作中";
  if (status === "done" || status === "success" || status === "completed") return "已完成";
  return status;
}

function statusClass(status) {
  if (status === "pending") return "st-pending";
  if (status === "executing" || status === "processing" || status === "making") return "st-making";
  if (status === "done" || status === "success" || status === "completed") return "st-done";
  if (!status) return "st-done";
  return "st-other";
}

/* ---------- 待制作订单（可单删 / 一键清除） ---------- */
const seenPending = new Map();   // orderId -> {name, code, toasted}
const deletedIds = new Set();    // 本会话删除/清除的订单，不触发"已完成"提示

async function fetchPendingOrders() {
  try {
    const res = await fetch("/api/orders/pending", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.status !== "ok") return;

    const rows = data.orders || [];
    const current = new Set(rows.map((o) => o.order_id));

    // 完成检测：之前待制作、现在不在列表、且非本会话删除
    for (const [oid, rec] of seenPending) {
      if (!current.has(oid) && !deletedIds.has(oid) && !rec.toasted) {
        rec.toasted = true;
        toast(`✅ ${rec.name}（取餐码 ${rec.code}）已完成`);
      }
    }
    for (const o of rows) {
      if (!seenPending.has(o.order_id)) {
        seenPending.set(o.order_id, {
          name: o.name, code: o.pickup_code, toasted: false,
        });
      }
    }

    pendingOrdersEl.innerHTML = "";
    if (!rows.length) {
      pendingOrdersEl.innerHTML = '<li class="empty">暂无待制作订单</li>';
      return;
    }
    for (const o of rows) {
      const li = document.createElement("li");
      li.dataset.oid = o.order_id;
      li.innerHTML = `
        <span class="who">${o.name}</span>
        <span class="code">取餐码 ${o.pickup_code}</span>
        <span class="time">${formatTime(o.timestamp)}</span>
        <span class="st ${statusClass(o.status)}">${statusLabel(o.status)}</span>
        <button class="del-btn" type="button" title="删除该订单">删除</button>
      `;
      li.querySelector(".del-btn").addEventListener("click", () => deleteOrder(o));
      pendingOrdersEl.appendChild(li);
    }
  } catch (_) { /* ignore */ }
}

async function deleteOrder(o) {
  if (!confirm(`确定删除 ${o.name}（取餐码 ${o.pickup_code}）？`)) return;
  try {
    const res = await fetch(`/api/orders/${encodeURIComponent(o.order_id)}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      toast("删除失败：" + (data.error || "未知错误"), true);
      return;
    }
    deletedIds.add(o.order_id);
    toast(`已删除 ${o.name}（取餐码 ${o.pickup_code}）`);
    fetchPendingOrders();
  } catch (_) {
    toast("删除失败：网络错误", true);
  }
}

clearPendingBtn.addEventListener("click", clearPending);

async function clearPending() {
  if (!confirm("确定一键清除所有未制作订单？")) return;
  try {
    const res = await fetch("/api/orders/clear-pending", { method: "POST" });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      toast("清除失败：" + (data.error || "未知错误"), true);
      return;
    }
    for (const oid of data.order_ids || []) deletedIds.add(oid);
    toast(`✅ 已清除 ${data.cleared || 0} 笔未制作订单`);
    fetchPendingOrders();
  } catch (_) {
    toast("清除失败：网络错误", true);
  }
}

/* ---------- Toast ---------- */
function toast(msg, isErr) {
  toastEl.textContent = msg;
  toastEl.classList.toggle("err", !!isErr);
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2600);
}

/* ---------- 今日订单统计（右侧滑入面板） ---------- */
todayBtn.addEventListener("click", openTodayDrawer);
drawerClose.addEventListener("click", closeTodayDrawer);
drawerMask.addEventListener("click", closeTodayDrawer);

function openTodayDrawer() {
  drawerMask.hidden = false;
  todayDrawer.classList.add("open");
  todayDrawer.setAttribute("aria-hidden", "false");
  fetchTodayOrders();
}

function closeTodayDrawer() {
  todayDrawer.classList.remove("open");
  drawerMask.hidden = true;
  todayDrawer.setAttribute("aria-hidden", "true");
}

async function fetchTodayOrders() {
  try {
    const res = await fetch("/api/orders/today", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.status !== "ok") {
      drawerOrders.innerHTML = '<li class="empty">统计加载失败</li>';
      return;
    }
    drawerDate.textContent = `${data.date} · 更新于 ${String(data.updated_at || "").slice(11, 19)}`;
    drawerTotal.textContent = data.total;
    drawerOrders.innerHTML = "";
    if (!data.orders.length) {
      drawerOrders.innerHTML = '<li class="empty">今日还没有订单</li>';
      return;
    }
    for (const o of data.orders) {
      const li = document.createElement("li");
      const dur = o.duration_sec != null
        ? `${o.duration_sec.toFixed(1)}s`
        : (o.timing_result === "failed" ? "失败" : "—");
      const durCls = o.timing_result === "failed" ? "t-fail" : "";
      li.innerHTML = `
        <span class="d-name">${o.name}</span>
        <span class="d-time">下单 ${formatTime(o.placed_ms)}</span>
        <span class="d-dur ${durCls}">制作 ${dur}</span>
      `;
      drawerOrders.appendChild(li);
    }
  } catch (_) {
    drawerOrders.innerHTML = '<li class="empty">统计加载失败</li>';
  }
}

/* ---------- 制作时长（cerebrum.log 监听） ---------- */
async function fetchTiming() {
  try {
    const res = await fetch("/api/timing/status", { cache: "no-store" });
    const st = await res.json();
    if (!res.ok || st.status !== "ok") return;
    if (!st.allowed) {
      timingSection.hidden = true; // 桥接模式：隐藏整个制作时长功能
      tabTiming.hidden = true;
      if (!paneTiming.hidden) switchEditorTab("menu");
      return;
    }
    timingSection.hidden = false;
    tabTiming.hidden = false;
    timingSwitch.checked = !!st.enabled;
    timingSwitch.disabled = false;
    timingSwitch.title = "开启/关闭制作时长监听";
    timingSwitchLabel.textContent = st.enabled ? "开启" : "关闭";
    if (!st.enabled) {
      timingRules.hidden = true;
      return;
    }
    timingRules.hidden = false;
    const rc = await fetch("/api/timing/config", { cache: "no-store" });
    const rcfg = await rc.json();
    if (rc.ok && rcfg.status === "ok") {
      startTemplate.value = rcfg.start.template || "";
      startPath.innerHTML = "";
      const startPaths = (rcfg.start.path && rcfg.start.path.length)
        ? rcfg.start.path : (rcfg.start.resolved_path || []);
      for (const p of startPaths) addPathRow(startPath, p);
      if (!startPaths.length) addPathRow(startPath, "");
      startNode.value = rcfg.start.node_name || "";
      startResolved.textContent = rcfg.start.resolved_path && rcfg.start.resolved_path.length
        ? `自动定位：${rcfg.start.resolved_path.join(" / ")}` : "自动定位：未找到（请检查节点/子树）";
      endTemplate.value = rcfg.end.template || "";
      endPath.innerHTML = "";
      const endPaths = (rcfg.end.path && rcfg.end.path.length)
        ? rcfg.end.path : (rcfg.end.resolved_path || []);
      for (const p of endPaths) addPathRow(endPath, p);
      if (!endPaths.length) addPathRow(endPath, "");
      endNode.value = rcfg.end.node_name || "";
      endResolved.textContent = rcfg.end.resolved_path && rcfg.end.resolved_path.length
        ? `自动定位：${rcfg.end.resolved_path.join(" / ")}` : "自动定位：未找到（请检查节点/子树）";
    }
  } catch (_) { /* ignore */ }
}

function addPathRow(container, value) {
  const row = document.createElement("div");
  row.className = "rule-row path-row";
  row.innerHTML = `
    <label>层级</label>
    <input type="text" value="${value || ""}" placeholder="嵌套节点名">
    <button class="path-del" type="button" title="删除该层级">×</button>
  `;
  row.querySelector(".path-del").addEventListener("click", () => row.remove());
  container.appendChild(row);
}

function collectPath(container) {
  return [...container.querySelectorAll("input")]
    .map((i) => i.value.trim())
    .filter(Boolean);
}

startPathAdd.addEventListener("click", () => addPathRow(startPath, ""));
endPathAdd.addEventListener("click", () => addPathRow(endPath, ""));

timingSwitch.addEventListener("change", async () => {
  const want = timingSwitch.checked;
  try {
    const res = await fetch("/api/timing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: want }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      timingSwitch.checked = !want;
      toast("设置失败：" + (data.error || "未知错误"), true);
      return;
    }
    toast(want ? "✅ 制作时长监听已开启" : "制作时长监听已关闭");
    fetchTiming();
  } catch (_) {
    timingSwitch.checked = !want;
    toast("设置失败：网络错误", true);
  }
});

ruleSave.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/timing/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start: {
          template: startTemplate.value.trim(),
          path: collectPath(startPath),
          node_name: startNode.value.trim(),
        },
        end: {
          template: endTemplate.value.trim(),
          path: collectPath(endPath),
          node_name: endNode.value.trim(),
        },
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      toast("规则保存失败：" + (data.error || "未知错误"), true);
      return;
    }
    toast("✅ 起止节点规则已更新");
    fetchTiming();
  } catch (_) {
    toast("规则保存失败：网络错误", true);
  }
});

/* ---------- 饮品编辑弹窗（标签/禁单/提示词） ---------- */
let DRINK_EDIT = null;

function openDrinkEdit(d) {
  DRINK_EDIT = {
    type: d.type,
    tags: [...(d.tags || [])],
    disabled: !!d.disabled,
    hint: d.hint || "",
  };
  drinkEditTitle.textContent = `编辑饮品：${d.chinese}`;
  renderDrinkTags();
  drinkDisabled.checked = DRINK_EDIT.disabled;
  drinkDisabledLabel.textContent = DRINK_EDIT.disabled ? "禁止下单" : "可下单";
  drinkHint.value = DRINK_EDIT.hint;
  drinkEditMask.hidden = false;
}

function closeDrinkEdit() {
  drinkEditMask.hidden = true;
}

function addDrinkTagRow(value) {
  const row = document.createElement("div");
  row.className = "tag-chip";
  row.innerHTML = `
    <input type="text" value="${value || ""}" placeholder="标签名">
    <button class="path-del" type="button" title="删除标签">×</button>
  `;
  row.querySelector(".path-del").addEventListener("click", () => row.remove());
  drinkTags.appendChild(row);
}

function renderDrinkTags() {
  drinkTags.innerHTML = "";
  for (const t of DRINK_EDIT.tags) addDrinkTagRow(t);
  if (!DRINK_EDIT.tags.length) addDrinkTagRow("");
}

function collectDrinkTags() {
  return [...drinkTags.querySelectorAll("input")]
    .map((i) => i.value.trim())
    .filter(Boolean);
}

async function saveDrinkEdit() {
  if (!DRINK_EDIT) return;
  const payload = {
    drinks: {
      [DRINK_EDIT.type]: {
        tags: collectDrinkTags(),
        disabled: drinkDisabled.checked,
        hint: drinkHint.value.trim(),
      },
    },
  };
  try {
    const res = await fetch("/api/editor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      toast("保存失败：" + (data.error || "未知错误"), true);
      return;
    }
    toast("✅ 饮品设置已保存");
    closeDrinkEdit();
    loadEditor(true).then(() => {
      if (!modalMask.hidden && EDITOR) renderEditor();
    });
    loadMenu().then(() => switchCategory(MENU.active_category || activeCatId));
  } catch (_) {
    toast("保存失败：网络错误", true);
  }
}

drinkTagAdd.addEventListener("click", () => addDrinkTagRow(""));
drinkEditClose.addEventListener("click", closeDrinkEdit);
drinkEditCancel.addEventListener("click", closeDrinkEdit);
drinkEditMask.addEventListener("click", (e) => {
  if (e.target === drinkEditMask) closeDrinkEdit();
});
drinkEditSave.addEventListener("click", saveDrinkEdit);
drinkDisabled.addEventListener("change", () => {
  drinkDisabledLabel.textContent = drinkDisabled.checked ? "禁止下单" : "可下单";
});

/* ---------- 健康检查 ---------- */
async function checkHealth() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    const data = await res.json();
    if (data.docker_ok) {
      statusDot.className = "dot ok";
      statusText.textContent = "服务正常 · 可下单";
    } else {
      statusDot.className = "dot bad";
      statusText.textContent = "容器连接异常";
    }
  } catch (_) {
    statusDot.className = "dot bad";
    statusText.textContent = "服务未连接";
  }
}

fetchPendingOrders();
loadMenu();
loadEditor(); // 页面加载时预取编辑数据，点"编辑"秒开
checkHealth();
setInterval(checkHealth, 15000);

// ?pure=1 打开即为纯净模式（适合 Kiosk 收藏）
if (new URLSearchParams(window.location.search).get("pure") === "1") {
  enterPure();
}
