"use strict";
/* ==========================================================================
   EZ-Rent — SPA tĩnh (không build, không CDN). Hệ thiết kế: design.md. Mọi API gọi qua đường dẫn tương
   đối /api/v1/... (cùng origin với nginx).

   ⭐ Không lưu token vào localStorage: access token chỉ nằm trong bộ nhớ
      (mất khi tải lại trang), refresh token nằm trong cookie HttpOnly do
      auth-service đặt — JavaScript (kể cả script độc qua XSS) không đọc được.
      Tải lại trang → gọi /auth/refresh bằng cookie để lấy access token mới.
   ========================================================================== */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  access: null,
  user: null,
  tab: null,
  propertyId: null,
  rooms: null,           // cache id → phòng (cho bảng hợp đồng, hóa đơn)
};

/* ------------------------- Tiện ích hiển thị ------------------------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ico = (name, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
const fmtMoney = (v) => (v === null || v === undefined || v === "") ? "—" : num(v).toLocaleString("vi-VN") + " đ";
const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso).slice(0, 10) : d.toLocaleDateString("vi-VN");
};
const fmtPeriod = (iso) => iso ? `Tháng ${Number(iso.slice(5, 7))}/${iso.slice(0, 4)}` : "—";
const fmtQty = (v) => v === null || v === undefined ? "—" : num(v).toLocaleString("vi-VN");
const money = (v) => `<span class="num">${fmtMoney(v)}</span>`;

/* Kỳ = ngày 1 của tháng, dạng YYYY-MM-01 (đúng định dạng billing-service nhận) */
const curPeriod = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`; };
const shiftPeriod = (p, delta) => {
  const d = new Date(Number(p.slice(0, 4)), Number(p.slice(5, 7)) - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
};
const today = () => new Date().toISOString().slice(0, 10);
const addMonths = (iso, m) => { const d = new Date(iso); d.setMonth(d.getMonth() + m); return d.toISOString().slice(0, 10); };

const LABEL = {
  role: { ADMIN: "Chủ trọ", MANAGER: "Quản lý", TENANT: "Người thuê", SYSTEM: "Hệ thống" },
  room: { OCCUPIED: ["Đang thuê", "g"], AVAILABLE: ["Còn trống", "b"], MAINTENANCE: ["Bảo trì", "a"], RESERVED: ["Đã giữ chỗ", "n"] },
  invoice: { PAID: ["Đã thanh toán", "g"], PENDING: ["Chờ thanh toán", "a"], OVERDUE: ["Quá hạn", "r"], CANCELLED: ["Đã hủy", "n"], PARTIAL: ["Trả một phần", "b"] },
  contract: { DRAFT: ["Nháp", "n"], PENDING_SIGN: ["Chờ ký", "a"], ACTIVE: ["Đang hiệu lực", "g"], EXPIRED: ["Hết hạn", "n"],
              TERMINATED: ["Đã chấm dứt", "r"], CANCELLED: ["Đã hủy", "n"], RENEWED: ["Đã gia hạn", "b"] },
  incident: { OPEN: ["Mới", "r"], ASSIGNED: ["Đã giao", "a"], IN_PROGRESS: ["Đang xử lý", "b"], RESOLVED: ["Đã xử lý", "g"],
              CLOSED: ["Đã đóng", "n"], CANCELLED: ["Đã hủy", "n"] },
  priority: { LOW: ["Thấp", "n"], NORMAL: ["Bình thường", "b"], HIGH: ["Cao", "a"], URGENT: ["Khẩn cấp", "r"] },
  category: { PLUMBING: "Điện nước / ống nước", ELECTRIC: "Điện", APPLIANCE: "Thiết bị", FURNITURE: "Nội thất",
              STRUCTURE: "Kết cấu nhà", PEST: "Côn trùng", GAS: "Gas", OTHER: "Khác" },
  method: { CASH: "Tiền mặt", BANK_TRANSFER: "Chuyển khoản", MOMO: "MoMo", VNPAY: "VNPay", CARD: "Thẻ" },
  risk: { LOW: ["Bình thường", "g"], MEDIUM: ["Cần lưu ý", "a"], HIGH: ["Rủi ro cao", "r"] },
};
/* Màu trạng thái (design.md): g = ok (rêu), b = info (xanh xám), a = warn (vàng đất),
   r = đỏ son (chỉ nợ / quá hạn / khẩn), n = hủy / hết hạn (viền đứt, không màu). */
const TAG_CLASS = { g: "g", b: "b", a: "a", r: "alarm", n: "quiet" };
const pill = (map, v) => { const x = map[v]; return x ? `<span class="tag ${TAG_CLASS[x[1]] || ""}">${x[0]}</span>` : `<span class="tag quiet">${esc(v || "—")}</span>`; };
const options = (map, sel) => Object.entries(map).map(([k, v]) =>
  `<option value="${k}" ${k === sel ? "selected" : ""}>${Array.isArray(v) ? v[0] : v}</option>`).join("");

/* Sáng / tối: mặc định theo hệ điều hành (CSS prefers-color-scheme); người dùng
   chọn khác thì ghi data-theme lên <html> và nhớ trong trình duyệt. */
const THEME_KEY = "ezrent.theme";
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
const isDark = () => (document.documentElement.dataset.theme || (systemDark() ? "dark" : "light")) === "dark";
function setTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { t ? localStorage.setItem(THEME_KEY, t) : localStorage.removeItem(THEME_KEY); } catch (_) { /* chế độ riêng tư */ }
}
try { const t = localStorage.getItem(THEME_KEY); if (t === "dark" || t === "light") document.documentElement.dataset.theme = t; } catch (_) { /* bỏ qua */ }

const skeleton = () => `<div class="loading">Đang tải…</div>`;
const empty = (title, sub = "") => `<div class="empty"><b>${title}</b>${sub}</div>`;

/* Chỉ dùng cho lỗi, việc chạy nền, và thao tác làm dòng biến khỏi danh sách
   đang xem. Thành công thấy được trên màn hình thì im lặng (design.md). */
function toast(msg, type = "ok") {
  const el = document.createElement("div");
  el.className = "toast " + (type === "err" ? "err" : "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "err" ? 6000 : 3500);
}

/* ------------------------------ API core ------------------------------ */
const apiErr = (res) => {
  const d = res.data || {};
  if (d.error && d.error.message) {
    /* 422: nói rõ trường nào sai; 5xx: kèm mã lỗi (request_id) để tra log —
       thông báo lỗi hệ thống tự nó đã bảo "cung cấp mã lỗi cho quản trị viên". */
    const fields = (d.error.details && d.error.details.fields) || [];
    const what = fields.map((f) => `${f.field}: ${f.problem}`).join("; ");
    const id = res.status >= 500 && d.request_id && d.request_id !== "-" ? ` (mã lỗi: ${d.request_id})` : "";
    return d.error.message + (what ? ` — ${what}` : "") + id;
  }
  if (Array.isArray(d.detail)) return d.detail.map((x) => x.msg).join("; ");
  return d.detail || ("Lỗi máy chủ (" + res.status + ")");
};

/* Báo auth-service dùng cookie HttpOnly cho refresh token (và cũng là chốt
   chống CSRF: site khác không gửi được header tùy biến này). */
const AUTH_HEADERS = { "Content-Type": "application/json", "X-Token-Transport": "cookie" };

let refreshPromise = null;
async function doRefresh() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch("/api/v1/auth/refresh", { method: "POST", headers: AUTH_HEADERS, body: "{}" });
        if (!res.ok) return false;
        saveSession(await res.json());
        return true;
      } catch (_) { return false; }
    })();
  }
  try { return await refreshPromise; } finally { refreshPromise = null; }
}

async function api(method, path, body, tryRefresh = true) {
  const headers = { ...AUTH_HEADERS };
  if (state.access) headers.Authorization = "Bearer " + state.access;
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : null });
  if (res.status === 401 && tryRefresh) {
    if (await doRefresh()) return api(method, path, body, false);
  }
  if (res.status === 401 && state.access && !path.startsWith("/api/v1/auth/")) {
    sessionStorage.setItem("qlpt.msg", "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.");
    clearSession();
    location.reload();
    return { status: 401, ok: false, data: null };
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* body rỗng */ }
  return { status: res.status, ok: res.ok, data };
}
/* Gọi API và ném lỗi đọc được nếu thất bại — dùng cho thao tác ghi */
async function must(method, path, body) {
  const res = await api(method, path, body);
  if (!res.ok) throw new Error(apiErr(res));
  return res.data;
}
const items = (res) => (res && res.ok && res.data) ? (Array.isArray(res.data) ? res.data : res.data.items || []) : [];
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v !== null && v !== undefined)).toString();

function saveSession(data) {
  state.access = data.access_token;
  state.user = data.user;
}
function clearSession() {
  state.access = state.user = null;
  // Dọn token do phiên bản cũ của trang để lại trong localStorage
  ["qlpt.access", "qlpt.refresh", "qlpt.user"].forEach((k) => localStorage.removeItem(k));
}

/* Cơ sở hiện tại: MANAGER/TENANT gắn sẵn trong token; ADMIN lấy cơ sở đầu tiên */
async function propertyId() {
  if (state.propertyId) return state.propertyId;
  if (state.user.property_id) return (state.propertyId = state.user.property_id);
  const list = items(await api("GET", "/api/v1/properties?page_size=1"));
  if (!list.length) throw new Error("Chưa có cơ sở nhà trọ nào.");
  return (state.propertyId = list[0].id);
}
async function roomMap(force = false) {
  if (state.rooms && !force) return state.rooms;
  const list = items(await api("GET", "/api/v1/rooms?page_size=100"));
  state.rooms = Object.fromEntries(list.map((r) => [r.id, r]));
  return state.rooms;
}

/* ------------------------------ Hộp thoại ------------------------------ */
/* modal({title, body, submit, onSubmit, wide}) → onSubmit(form) trả về true để đóng.
   Lỗi ném ra trong onSubmit được hiện ngay trong hộp thoại, không đóng. */
function modal({ title, body, submit, onSubmit, wide = false, danger = false, cancel = "Đóng" }) {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `
    <form class="modal ${wide ? "wide" : ""}" novalidate role="dialog" aria-modal="true">
      <div class="modal-h"><h2>${title}</h2></div>
      <div class="modal-b">${body}<div class="err" data-err></div></div>
      <div class="modal-f">
        <button type="button" class="btn ghost" data-close>${cancel}</button>
        ${submit ? `<button type="submit" class="btn ${danger ? "danger" : ""}">${submit}</button>` : ""}
      </div>
    </form>`;
  const opener = document.activeElement;
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const close = () => {
    bg.remove();
    document.removeEventListener("keydown", onKey);
    if (opener && opener.isConnected) opener.focus();
  };
  document.addEventListener("keydown", onKey);
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-close]")) close(); });
  const form = $("form", bg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!onSubmit) return close();
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    $("[data-err]", form).textContent = "";
    try { if ((await onSubmit(form)) !== false) close(); }
    catch (err) { $("[data-err]", form).textContent = err.message; }
    finally { btn.disabled = false; }
  });
  document.body.appendChild(bg);
  const first = $("input:not([type=hidden]), select, textarea", form);
  if (first) first.focus();
  return { el: bg, form, close };
}
const val = (form, name) => { const el = form.elements[name]; return el ? el.value.trim() : ""; };

/* ------------------------------ Đăng nhập ----------------------------- */
$("#pw-toggle").addEventListener("click", (e) => {
  const btn = e.currentTarget, input = $("#p"), show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-pressed", show);
  btn.setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
  btn.querySelector("use").setAttribute("href", show ? "#i-eye-off" : "#i-eye");
  input.focus();
});
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if ($("#p").type === "text") $("#pw-toggle").click();   // ẩn lại trước khi gửi: trình duyệt mới đề nghị lưu mật khẩu
  const btn = $("#login-btn");
  btn.disabled = true; btn.textContent = "Đang đăng nhập…";
  $("#login-err").textContent = "";
  try {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST", headers: AUTH_HEADERS,
      body: JSON.stringify({ username: $("#u").value.trim(), password: $("#p").value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // 429 có 2 nguồn: auth-service khoá tài khoản (có message) hoặc nginx
      // giới hạn tần suất (trang HTML, không có message).
      const msg = data && data.error && data.error.message;
      $("#login-err").textContent = res.status === 401 ? "Sai tên đăng nhập hoặc mật khẩu."
        : res.status === 429 ? (msg || "Bạn thử quá nhiều lần, vui lòng đợi một lát.")
        : apiErr({ status: res.status, data });
      return;
    }
    saveSession(data);
    enterApp();
  } catch (_) {
    $("#login-err").textContent = "Không kết nối được máy chủ.";
  } finally {
    btn.disabled = false; btn.textContent = "Đăng nhập";
  }
});
/* Tài khoản dùng thử chỉ hiện khi mở bằng ?demo=1 (buổi bảo vệ). Bản chạy
   thật không quảng cáo tên đăng nhập admin hay mật khẩu mẫu cho người lạ. */
if (new URLSearchParams(location.search).has("demo")) $(".demo").classList.remove("hidden");
$$(".demo [data-user]").forEach((b) => b.addEventListener("click", () => {
  $("#u").value = b.dataset.user;
  $("#p").value = "";   // không điền sẵn mật khẩu: mật khẩu mẫu nằm trong secrets/
  $("#p").focus();
}));

/* ---------------------------- Điều hướng ------------------------------ */
/* Tab mục kiểu chia sổ. Mỗi nhóm cách nhau một khoảng trống, không có nhãn nhóm. */
const NAV = {
  manager: [
    [["home", "home", "Hôm nay"], ["meters", "gauge", "Điện nước"], ["invoices", "receipt", "Hóa đơn"], ["incidents", "wrench", "Sự cố"]],
    [["plan", "grid", "Sơ đồ phòng"], ["contracts", "file", "Hợp đồng"], ["tenants", "users", "Người thuê"]],
    [["profile", "user", "Tài khoản"]],
  ],
  tenant: [
    [["room", "home", "Phòng của tôi"], ["my-invoices", "receipt", "Hóa đơn"], ["my-incidents", "wrench", "Sự cố"],
     ["inbox", "bell", "Thông báo"], ["profile", "user", "Tài khoản"]],
  ],
};
const isTenant = () => state.user && state.user.role === "TENANT";
const navDef = () => NAV[isTenant() ? "tenant" : "manager"];
const allowedTabs = () => navDef().flat().map((x) => x[0]);

function enterApp() {
  $("#login-wrap").classList.add("hidden");
  $("#app").classList.remove("hidden");
  const fromHash = location.hash.slice(1);
  state.tab = allowedTabs().includes(fromHash) ? fromHash : allowedTabs()[0];
  renderNav();
  go(state.tab);
  if (isTenant() && state.tab !== "room" && state.tab !== "inbox") {
    api("GET", "/api/v1/notifications/mine?limit=30").then((r) => { if (r.ok && Array.isArray(r.data)) inboxBadge(r.data); });
  }
}

function renderNav() {
  /* Khoảng cách giữa các tab đều nhau; tab "Tài khoản" (nhóm cuối) đẩy sang phải */
  const groups = navDef();
  $("#nav").innerHTML = groups.map((list, gi) => list.map(([id, icon, label]) =>
      `<button class="tab ${gi === groups.length - 1 && groups.length > 1 ? "tab-end" : ""}" data-tab="${id}">${ico(icon)}<span>${label}</span><span class="count hidden" data-badge="${id}"></span></button>`).join("")
  ).join("");
  $$("#nav .tab").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
  $("#home-link").addEventListener("click", (e) => { e.preventDefault(); go(allowedTabs()[0]); });
  const u = state.user;
  $("#me").innerHTML = `<b>${esc(u.full_name)}</b><span class="sub role">${LABEL.role[u.role] || u.role}</span>
    <button class="icon-btn" id="theme" type="button"></button>
    <button class="linkish" id="logout">Đăng xuất</button>`;
  const paintTheme = () => {
    const dark = isDark();
    $("#theme").innerHTML = ico(dark ? "sun" : "moon");
    $("#theme").setAttribute("aria-label", dark ? "Chuyển sang nền sáng" : "Chuyển sang nền tối");
    $("#theme").title = $("#theme").getAttribute("aria-label");
  };
  $("#theme").addEventListener("click", () => {
    const want = isDark() ? "light" : "dark";
    setTheme(want === (systemDark() ? "dark" : "light") ? null : want);   // trùng hệ điều hành → bỏ ghi đè
    paintTheme();
  });
  paintTheme();
  $("#logout").addEventListener("click", async () => {
    await api("POST", "/api/v1/auth/logout", {}).catch(() => {});   // xoá cookie + thu hồi phiên
    clearSession();
    location.hash = "";
    location.reload();
  });
}
function setBadge(tab, n) {
  const b = $(`[data-badge="${tab}"]`);
  if (!b) return;
  b.textContent = n;
  b.classList.toggle("hidden", !n);
}

/* ------------------------------------------------------------------------
   Chuyển động — đúng 3 loại, mỗi loại trả lời một câu hỏi của người dùng
   (design.md § Motion). Chỉ transform/opacity (+ một lần đổi màu nền), tắt
   hết khi hệ điều hành bật "giảm chuyển động".
   ------------------------------------------------------------------------ */
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* C · Vạch chân trượt: "bạn vừa chuyển từ đây sang đây". Một thanh 100px duy
   nhất, đặt vị trí + độ rộng bằng transform (translateX + scaleX). */
function moveInk(container, active) {
  if (!container) return;
  let ink = container.querySelector(":scope > .ink");
  const first = !ink;
  if (first) {
    ink = document.createElement("i");
    ink.className = "ink";
    ink.setAttribute("aria-hidden", "true");
    container.appendChild(ink);
  }
  if (!active) { ink.style.opacity = "0"; return; }
  if (first) ink.classList.add("no-anim");          // lần đầu đặt thẳng, không trượt từ mép trái
  ink.style.opacity = "1";
  ink.style.transform = `translateX(${active.offsetLeft}px) scaleX(${active.offsetWidth / 100})`;
  if (first) requestAnimationFrame(() => requestAnimationFrame(() => ink.classList.remove("no-anim")));
}
const syncInks = (root = document) => {
  moveInk($("#nav"), $("#nav .tab[aria-current]"));
  $$(".filter", root).forEach((f) => moveInk(f, $('[aria-pressed="true"]', f)));
};
window.addEventListener("resize", debounce(() => syncInks(), 100));
if (document.fonts) document.fonts.ready.then(() => syncInks());   // font tải xong → chữ đổi độ rộng

/* A · Số liệu đến nơi: số tiền đếm lên một lần (600ms, chậm dần ở cuối) để báo
   "đây là dữ liệu vừa tải về". Thanh tiến độ mọc ra bằng CSS (@keyframes grow). */
function countUp(root = document) {
  $$("[data-count]:not([data-counted])", root).forEach((el) => {
    el.dataset.counted = "1";
    const target = num(el.dataset.count);
    el.setAttribute("aria-label", fmtMoney(target));     // trình đọc màn hình nghe số cuối, không nghe từng nhịp
    if (reduceMotion() || !target) { el.textContent = fmtMoney(target); return; }
    const t0 = performance.now(), dur = 600;
    const step = (t) => {
      const p = Math.min(1, (t - t0) / dur);
      el.textContent = fmtMoney(Math.round(target * (1 - (1 - p) ** 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* B · Dòng vừa đổi sáng lên: thao tác xong thì ghi id vào state.flash; lần vẽ
   bảng / danh sách kế tiếp tìm dòng đó, cho nó lóe một nhịp và cuộn tới nếu
   khuất. Thay cho toast "Đã lưu" — thành công im lặng nhưng chỉ đúng chỗ. */
function flashChanged(root) {
  if (!state.flash || !root) return;
  const el = root.querySelector(`[data-id="${CSS.escape(state.flash)}"]`);
  state.flash = null;
  if (!el) return;
  el.classList.remove("flash");
  void el.offsetWidth;                      // khởi động lại animation nếu dòng vừa lóe
  el.classList.add("flash");
  el.scrollIntoView({ block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
}
const afterRender = (root) => { syncInks(root); countUp(root); };

const VIEWS = {};
function go(tab) {
  if (!allowedTabs().includes(tab)) tab = allowedTabs()[0];
  state.tab = tab;
  history.replaceState(null, "", "#" + tab);
  $$("#nav .tab").forEach((b) => {
    if (b.dataset.tab === tab) { b.setAttribute("aria-current", "page"); b.scrollIntoView({ block: "nearest", inline: "nearest" }); }
    else b.removeAttribute("aria-current");
  });
  moveInk($("#nav"), $("#nav .tab[aria-current]"));
  const v = $("#view");
  v.innerHTML = skeleton();
  window.scrollTo(0, 0);
  VIEWS[tab](v).then(() => afterRender(v)).catch((err) => {
    v.innerHTML = empty("Không tải được dữ liệu", `<div>${esc(err.message)}</div>`);
  });
}

/* Thẻ "đã thu / tổng đã lập" — dùng chung cho Hôm nay và Sổ thu tiền để hai nơi
   luôn cùng nguồn (billing) và cùng cách tính. stats = GET /invoices/stats.
   overdueAmt: tiền quá hạn trong cùng phạm vi (vẽ đoạn đỏ trên thanh), có thể bỏ. */
function collectBlock(stats, label, { overdueAmt = 0, who = "hóa đơn", extra = "" } = {}) {
  const s = stats || {};
  const billed = num(s.total_billed);
  const pctOf = (x) => billed ? Math.min(100, (num(x) / billed) * 100).toFixed(1) + "%" : "0%";
  const unpaid = (s.pending ?? 0) + (s.overdue ?? 0);
  return `
    <div class="label">${ico("receipt")}${label} · ${s.total_invoices ?? 0} hóa đơn đã lập</div>
    <div class="collect">
      <div><div class="collect-fig"><span class="big" data-count="${num(s.total_collected)}">${fmtMoney(s.total_collected)}</span><span class="of-total">/ ${fmtMoney(s.total_billed)}</span></div>
        <div class="cap">Đã thu / tổng đã lập</div></div>
      <div class="collect-owe"><span class="owe">${fmtMoney(s.total_outstanding)}</span><div class="cap">Còn phải thu</div></div>
    </div>
    <div class="meter" role="img" aria-label="Đã thu ${pctOf(s.total_collected)} tổng đã lập${overdueAmt ? `, quá hạn ${pctOf(overdueAmt)}` : ""}">
      <i class="m-ok" style="width:${pctOf(s.total_collected)}"></i>${overdueAmt ? `<i class="m-due" style="width:${pctOf(overdueAmt)}"></i>` : ""}</div>
    <div class="meter-key">
      <span class="ok-t">${ico("check", "sm")} <b>${s.paid ?? 0}</b> ${who} đã trả đủ</span>
      <span>${ico("alert", "sm")} <b>${unpaid}</b> ${who} chưa trả${s.overdue ? ` <span class="due">(${s.overdue} quá hạn${overdueAmt ? " · " + fmtMoney(overdueAmt) : ""})</span>` : ""}</span>
      ${extra}</div>`;
}

const head = (title, lead, actions = "") =>
  `<div class="page-head"><div><h1>${title}</h1>${lead ? `<div class="lead">${lead}</div>` : ""}</div>
   ${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
/* Bộ lọc dạng chữ (thay cho nút phân đoạn có nền) */
const filterBar = (id, key, opts, cur) => `<div class="filter" id="${id}" role="group">${opts.map(([v, label]) =>
  `<button type="button" data-${key}="${v}" aria-pressed="${v === cur}">${label}</button>`).join("")}</div>`;
/* Dòng bảng mở được bằng chuột và bằng bàn phím (Enter / Space) */
const rowsOpen = (root, open) => {
  $$("tr[data-id]", root).forEach((tr) => {
    tr.tabIndex = 0;
    tr.addEventListener("click", () => open(tr.dataset.id));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(tr.dataset.id); } });
  });
  flashChanged(root);
};
const markFilter = (id, key, cur) => {
  $$(`#${id} button`).forEach((x) => x.setAttribute("aria-pressed", String(x.dataset[key] === cur)));
  moveInk($(`#${id}`), $(`#${id} [aria-pressed="true"]`));
};

/* ======================================================================
   1. VIỆC CẦN LÀM (chủ trọ / quản lý)
   ====================================================================== */
VIEWS.home = async (v) => {
  const period = curPeriod();
  const [dash, rooms, inv, overdue, expiring, incidents, readings, occupied, periodInv, allContracts] = await Promise.all([
    api("GET", "/api/v1/reports/dashboard"),
    api("GET", "/api/v1/rooms/stats"),
    api("GET", "/api/v1/invoices/stats"),
    api("GET", "/api/v1/invoices/overdue"),
    api("GET", "/api/v1/contracts/expiring?days=30"),
    api("GET", "/api/v1/incidents?" + qs({ is_open: true, page_size: 100 })),
    api("GET", "/api/v1/meter-readings?" + qs({ period, utility_type: "ELECTRIC", page_size: 100 })),
    api("GET", "/api/v1/rooms?" + qs({ status: "OCCUPIED", page_size: 100 })),
    api("GET", "/api/v1/invoices?" + qs({ period, page_size: 1 })),
    api("GET", "/api/v1/contracts?page_size=100"),
  ]);
  /* ⭐ API lỗi KHÔNG được coi là "danh sách rỗng": nếu API hóa đơn quá hạn
     chết mà vẫn hiện "Mọi việc đã xong" thì chủ trọ yên tâm sai. Ghi nhận
     nguồn nào lỗi, hiện cảnh báo, và không kết luận gì từ nguồn đó. */
  const failed = [[dash, "báo cáo doanh thu"], [rooms, "thống kê phòng"], [inv, "thống kê hóa đơn"],
    [overdue, "hóa đơn quá hạn"], [expiring, "hợp đồng sắp hết hạn"], [incidents, "sự cố"],
    [readings, "chỉ số điện nước"], [occupied, "danh sách phòng"], [periodInv, "hóa đơn kỳ này"]]
    .filter(([res]) => !res.ok).map(([, name]) => name);
  const kpi = (dash.data && dash.data.kpi) || {};
  const r = rooms.ok ? rooms.data || {} : {}, s = inv.ok ? inv.data || {} : {};
  const occRate = r.total ? Math.round((r.occupied / r.total) * 100) : null;
  const od = items(overdue), ex = items(expiring), inc = items(incidents);
  const done = new Set(items(readings).map((x) => x.room_id));
  const missing = items(occupied).filter((x) => !done.has(x.id));
  const issued = periodInv.ok && periodInv.data && periodInv.data.meta ? periodInv.data.meta.total : 0;
  if (incidents.ok) setBadge("incidents", inc.length);

  const todos = [];   // [đỏ?, icon, tiêu đề, chi tiết, đích, nhãn nút]
  const metersKnown = readings.ok && occupied.ok;
  if (metersKnown && missing.length) todos.push([false, "gauge", `${missing.length} phòng chưa nhập chỉ số ${fmtPeriod(period).toLowerCase()}`,
    missing.slice(0, 6).map((x) => x.room_number).join(", ") + (missing.length > 6 ? "…" : ""), "meters", "Nhập chỉ số"]);
  else if (metersKnown && periodInv.ok && !issued && items(occupied).length) todos.push([false, "send", `Chỉ số ${fmtPeriod(period).toLowerCase()} đã đủ, chưa phát hành hóa đơn`,
    "Phát hành một lần cho tất cả hợp đồng đang hiệu lực", "invoices", "Phát hành"]);
  const odSum = od.reduce((a, x) => a + num(x.total_amount) - num(x.paid_amount), 0);
  if (od.length) todos.push([true, "alert", `${od.length} hóa đơn quá hạn · ${fmtMoney(odSum)}`,
    od.slice(0, 3).map((x) => `${x.tenant_name} (${x.room_number || "—"})`).join(", "), "invoices:OVERDUE", "Xem"]);
  if (inc.length) todos.push([true, "wrench", `${inc.length} sự cố chưa xử lý xong`,
    inc.slice(0, 3).map((x) => x.title).join(" · "), "incidents", "Xử lý"]);
  /* ⭐ Hết hạn mà phòng chưa có hợp đồng mới: người thuê thường VẪN Ở. Không dựa
     vào trạng thái phòng được — room-service đã tự trả phòng về "Còn trống" khi
     nhận contract.expired, nên sơ đồ có thể đang báo trống sai. */
  if (allContracts.ok) {
    const all = items(allContracts);
    const liveRooms = new Set(all.filter((c) => ["ACTIVE", "PENDING_SIGN", "DRAFT"].includes(c.status)).map((c) => c.room_id));
    const since = addMonths(today(), -3);
    const latest = {};
    all.filter((c) => c.status === "EXPIRED" && !liveRooms.has(c.room_id) && c.end_date >= since)
      .forEach((c) => { if (!latest[c.room_id] || c.end_date > latest[c.room_id].end_date) latest[c.room_id] = c; });
    const lapsed = Object.values(latest);
    if (lapsed.length) {
      const rm = await roomMap().catch(() => ({}));
      todos.push([true, "file", `${lapsed.length} hợp đồng đã hết hạn, chưa ký lại`,
        lapsed.slice(0, 3).map((c) => `${c.primary_tenant_name} (${(rm[c.room_id] || {}).room_number || "—"}) · hết ${fmtDate(c.end_date)}`).join(", ") +
          " — phòng có thể đang hiện “Còn trống” dù người thuê vẫn ở",
        "contracts:EXPIRED", "Gia hạn"]);
    }
  }
  if (ex.length) todos.push([false, "cal", `${ex.length} hợp đồng hết hạn trong 30 ngày tới`,
    ex.slice(0, 3).map((x) => `${x.primary_tenant_name} · còn ${x.days_remaining} ngày`).join(", "), "contracts:expiring", "Xem"]);

  /* Sổ thu: 7 ngày gần nhất, mới nhất ở trên; thanh ngang tỉ lệ với ngày thu nhiều nhất */
  const pts = ((dash.data && dash.data.revenue_30d) || []).slice(-7).reverse();
  const total7 = pts.reduce((a, p) => a + num(p.collected), 0);
  const max7 = Math.max(...pts.map((p) => num(p.collected)), 1);

  /* Thẻ chính: đúng số liệu "Mọi kỳ" của trang Sổ thu tiền (cùng API, cùng collectBlock)
     để hai nơi luôn khớp. Số "tiền nhận trong tháng" của report-service tính theo NGÀY
     NHẬN tiền — thước đo khác, không đặt ở đây để khỏi lẫn. */
  const urgent = inc.filter((x) => x.priority === "URGENT").length;

  v.innerHTML = head("Hôm nay",
      new Date().toLocaleDateString("vi-VN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })) + `
    ${failed.length ? `<div class="note alarm">${ico("alert")}<div><b>Chưa tải được: ${esc(failed.join(", "))}.</b>
      Số liệu liên quan đang để “—” và danh sách việc có thể chưa đủ. Tải lại trang sau ít phút.</div></div>` : ""}
    <div class="overview">
      <section class="card hero-fig inv-sum" aria-label="Tiền thu, mọi kỳ">
        ${inv.ok ? collectBlock(s, "Mọi kỳ", { overdueAmt: overdue.ok ? odSum : 0 })
          : `<div class="label">${ico("receipt")}Mọi kỳ</div><div class="big">—</div>`}
      </section>
      <div class="stats">
        <section class="card stat ${od.length ? "alarm" : ""}"><div class="label">${ico("alert", "sm")}Quá hạn</div>
          <div class="v">${overdue.ok ? fmtMoney(odSum) : "—"}</div>
          <div class="s">${overdue.ok ? `${od.length} hóa đơn` : ""}</div></section>
        <section class="card stat"><div class="label">${ico("door", "sm")}Phòng có người</div>
          <div class="v">${rooms.ok ? `${r.occupied ?? 0}/${r.total ?? 0}` : "—"}</div>
          <div class="s">${occRate !== null ? `lấp đầy ${occRate}%` : ""}</div></section>
        <section class="card stat ${inc.length ? "alarm" : ""}"><div class="label">${ico("wrench", "sm")}Sự cố đang mở</div>
          <div class="v">${incidents.ok ? inc.length : "—"}</div>
          <div class="s">${incidents.ok ? (urgent ? `${urgent} khẩn cấp` : "không có việc khẩn") : ""}</div></section>
        <section class="card stat"><div class="label">${ico("cal", "sm")}Sắp hết hạn</div>
          <div class="v">${expiring.ok ? ex.length : "—"}</div>
          <div class="s">hợp đồng trong 30 ngày</div></section>
      </div>
    </div>
    <div class="home-grid">
      <section class="card">
        <div class="card-h">${ico("check")}<h2>Việc cần làm</h2><span class="sub">${todos.length ? todos.length + " việc" : ""}</span></div>
        ${todos.length ? `<ul class="todo-list">${todos.map(([red, icon, t, sub, target, btn]) => `
          <li class="todo ${red ? "due" : ""}">${ico(icon)}<div><b>${esc(t)}</b><span>${esc(sub)}</span></div>
            <button class="btn ghost sm" data-go="${target}">${btn}</button></li>`).join("")}</ul>`
          : failed.length ? empty("Chưa kiểm tra được đầy đủ", "Một số dữ liệu chưa tải được nên chưa thể kết luận.")
          : empty("Không còn việc gì", "Không có hóa đơn quá hạn, sự cố hay hợp đồng cần xử lý.")}
      </section>
      <section class="card">
        <div class="card-h">${ico("cash")}<h2>Sổ thu 7 ngày</h2><span class="sub num">${pts.length ? fmtMoney(total7) : ""}</span></div>
        ${pts.length ? `<div class="tbl-wrap"><table>
          ${pts.map((p) => `<tr><td class="num sub">${fmtDate(p.stat_date)}</td>
            <td class="right">${money(p.collected)}${num(p.collected) ? `<i class="ledger-bar" style="width:${(num(p.collected) / max7) * 100}%"></i>` : ""}</td></tr>`).join("")}
          </table></div>`
          : empty("Chưa có khoản thu nào", "Sổ sẽ có dòng khi có thanh toán đầu tiên.")}
      </section>
    </div>`;
  $$("[data-go]", v).forEach((b) => b.addEventListener("click", () => {
    const [tab, arg] = b.dataset.go.split(":");
    state.arg = arg || null;
    go(tab);
  }));
};

/* ======================================================================
   2. SƠ ĐỒ PHÒNG — chia theo tòa, mỗi tòa xếp tầng cao ở trên như mặt đứng
   ====================================================================== */
VIEWS.plan = async (v) => {
  const [roomsRes, contracts, overdue] = await Promise.all([
    api("GET", "/api/v1/rooms?page_size=100"),
    api("GET", "/api/v1/contracts?status=ACTIVE&page_size=100"),
    api("GET", "/api/v1/invoices/overdue"),
  ]);
  if (!roomsRes.ok) throw new Error(apiErr(roomsRes));
  const rooms = items(roomsRes);
  const tenantOf = Object.fromEntries(items(contracts).map((c) => [c.room_id, c.primary_tenant_name]));
  const debtOf = {};
  items(overdue).forEach((i) => { debtOf[i.room_id] = (debtOf[i.room_id] || 0) + num(i.total_amount) - num(i.paid_amount); });

  // Tòa → tầng → phòng
  const tree = {};
  rooms.forEach((r) => {
    const b = r.building_name || "Khu chính";
    const f = r.floor ?? "?";
    ((tree[b] = tree[b] || {})[f] = tree[b][f] || []).push(r);
  });
  const buildings = Object.keys(tree).sort();
  const count = (st) => rooms.filter((r) => r.status === st).length;
  const partial = !contracts.ok || !overdue.ok;
  let current = buildings.length > 1 ? "" : buildings[0];

  v.innerHTML = head("Sơ đồ phòng", `${rooms.length} phòng · ${count("OCCUPIED")} đang thuê · ${count("AVAILABLE")} còn trống`) + `
    ${partial ? `<div class="note alarm">${ico("alert")}<div>Chưa tải được ${!contracts.ok ? "tên người thuê" : ""}${!contracts.ok && !overdue.ok ? " và " : ""}${!overdue.ok ? "công nợ" : ""}; sơ đồ chỉ hiện trạng thái phòng.</div></div>` : ""}
    <div class="card plan-bar">${buildings.length > 1 ? `<div class="toolbar">
      ${filterBar("seg", "b", [["", "Tất cả tòa"], ...buildings.map((b) => [esc(b), "Tòa " + esc(b)])], "")}</div>` : ""}
    <div class="legend" aria-label="Chú giải">
      <span><i class="OCCUPIED"></i>Đang thuê · ${count("OCCUPIED")}</span>
      <span><i class="AVAILABLE"></i>Còn trống · ${count("AVAILABLE")}</span>
      <span><i class="MAINTENANCE"></i>Bảo trì · ${count("MAINTENANCE")}</span>
      ${count("RESERVED") ? `<span><i class="RESERVED"></i>Đã giữ chỗ · ${count("RESERVED")}</span>` : ""}
      <span class="due"><b>Nợ</b> quá hạn tiền</span>
    </div></div>
    <div id="plan"></div>`;

  const render = () => {
    const list = current ? [current] : buildings;
    $("#plan").innerHTML = list.length ? list.map((b) => {
      const floors = Object.keys(tree[b]).sort((x, y) => (Number(y) || 0) - (Number(x) || 0));
      const all = floors.flatMap((f) => tree[b][f]);
      return `<section class="card building">
        <div class="card-h">${ico("home")}<h2>Tòa ${esc(b)}</h2><span class="sub">${all.filter((r) => r.status === "OCCUPIED").length}/${all.length} phòng có người</span></div>
        ${floors.map((f) => {
          const rs = tree[b][f].sort((x, y) => x.room_number.localeCompare(y.room_number, "vi", { numeric: true }));
          const free = rs.filter((r) => r.status === "AVAILABLE").length;
          return `<div class="floor"><div class="floor-lab"><b>${f === "?" ? "Khác" : "Tầng " + esc(f)}</b>${free ? `${free} trống` : "Kín phòng"}</div>
            <div class="tiles">${rs.map((r) => {
              const who = tenantOf[r.id];
              const debt = debtOf[r.id];
              const label = (LABEL.room[r.status] || [r.status])[0];
              return `<button type="button" class="room ${esc(r.status)} ${debt ? "has-debt" : ""}" data-id="${esc(r.id)}"
                  aria-label="Phòng ${esc(r.room_number)}, ${esc(label)}${who ? ", " + esc(who) : ""}${debt ? ", đang nợ " + fmtMoney(debt) : ""}">
                ${debt ? `<span class="debt" title="Quá hạn ${fmtMoney(debt)}">Nợ</span>` : ""}
                <div class="no">${esc(r.room_number)}</div>
                <div class="who">${who ? esc(who) : esc(label)}</div>
                <div class="meta">${r.area_m2 ? num(r.area_m2) + " m² · " : ""}${(num(r.base_price) / 1e6).toLocaleString("vi-VN")} tr</div>
              </button>`;
            }).join("")}</div></div>`;
        }).join("")}
      </section>`;
    }).join("") : empty("Chưa có phòng nào");
    $$(".room", $("#plan")).forEach((t) => t.addEventListener("click", () =>
      roomDetail(rooms.find((x) => x.id === t.dataset.id))));
  };
  $$("#seg button").forEach((btn) => btn.addEventListener("click", () => {
    current = btn.dataset.b; markFilter("seg", "b", current); render();
  }));
  render();
};

async function roomDetail(r) {
  const c = items(await api("GET", "/api/v1/contracts?" + qs({ room_id: r.id, active_only: true, page_size: 1 })))[0];
  modal({
    title: `Phòng ${esc(r.room_number)}`,
    body: `<dl class="kv">
      <dt>Trạng thái</dt><dd>${pill(LABEL.room, r.status)}</dd>
      <dt>Vị trí</dt><dd>${esc(r.building_name || "—")} · Tầng ${r.floor ?? "—"}</dd>
      <dt>Diện tích</dt><dd>${r.area_m2 ? num(r.area_m2) + " m²" : "—"}</dd>
      <dt>Giá thuê</dt><dd>${money(r.base_price)}</dd>
      <dt>Người đang thuê</dt><dd>${c ? `${esc(c.primary_tenant_name)} · ${esc(c.primary_tenant_phone)}` : "—"}</dd>
      <dt>Hợp đồng</dt><dd>${c ? `${esc(c.contract_no)} · đến ${fmtDate(c.end_date)}` : "Chưa có"}</dd></dl>`,
  });
}

/* ======================================================================
   3. CHỈ SỐ ĐIỆN NƯỚC — nhập cả dãy một lần (POST /meter-readings/batch)
   ====================================================================== */
VIEWS.meters = async (v) => {
  const pid = await propertyId();
  let period = curPeriod();
  v.innerHTML = head("Sổ điện nước", "Ghi số công tơ cuối kỳ cho các phòng đang có người thuê",
      `<label class="inline-lab" for="per">Kỳ</label><input type="month" id="per" value="${period.slice(0, 7)}">
       <button class="btn" id="save">${ico("check", "sm")}Lưu chỉ số</button>`) + `
    <div id="msg"></div>
    <div class="card"><div class="tbl-wrap" id="tbl">${skeleton()}</div></div>`;

  let rows = [];
  const load = async () => {
    $("#tbl").innerHTML = skeleton();
    $("#msg").innerHTML = "";
    const [roomsRes, cur, prev] = await Promise.all([
      api("GET", "/api/v1/rooms?" + qs({ status: "OCCUPIED", page_size: 100 })),
      api("GET", "/api/v1/meter-readings?" + qs({ period, page_size: 100 })),
      api("GET", "/api/v1/meter-readings?" + qs({ period: shiftPeriod(period, -1), page_size: 100 })),
    ]);
    if (!roomsRes.ok) throw new Error(apiErr(roomsRes));
    const key = (x) => x.room_id + ":" + x.utility_type;
    const curMap = Object.fromEntries(items(cur).map((x) => [key(x), x]));
    const prevMap = Object.fromEntries(items(prev).map((x) => [key(x), x]));
    rows = items(roomsRes).sort((a, b) => a.room_number.localeCompare(b.room_number)).map((r) => ({
      room: r,
      e: { cur: curMap[r.id + ":ELECTRIC"], prev: prevMap[r.id + ":ELECTRIC"] },
      w: { cur: curMap[r.id + ":WATER"], prev: prevMap[r.id + ":WATER"] },
    }));
    const doneCount = rows.filter((x) => x.e.cur && x.w.cur).length;
    if (rows.length && doneCount === rows.length) {
      $("#msg").innerHTML = `<div class="note ok">${ico("check")}<div>Đã nhập đủ chỉ số ${fmtPeriod(period).toLowerCase()} cho ${rows.length} phòng.
        <a href="#" id="to-inv" class="strong">Phát hành hóa đơn</a></div></div>`;
      $("#to-inv").addEventListener("click", (e) => { e.preventDefault(); state.arg = "issue"; go("invoices"); });
    }
    const cell = (r, t, d) => {
      const prevV = d.prev ? num(d.prev.reading_value) : null;
      const unit = t === "ELECTRIC" ? "kWh" : "m³";
      if (d.cur) return `<td class="right"><span class="num">${fmtQty(d.cur.reading_value)}</span><div class="use">dùng ${fmtQty(d.cur.consumption)} ${unit}</div></td>`;
      return `<td class="right"><input class="meter-in" type="number" min="0" step="0.01" inputmode="decimal"
                aria-label="${t === "ELECTRIC" ? "Điện" : "Nước"} phòng ${esc(r.room_number)}"
                data-room="${r.id}" data-type="${t}" data-prev="${prevV ?? ""}" placeholder="${prevV ?? "Số mới"}">
              <div class="use" data-use></div></td>`;
    };
    $("#tbl").innerHTML = rows.length ? `<table>
      <tr><th>Phòng</th><th class="right">${ico("zap", "sm")}Điện kỳ trước</th><th class="right">Điện kỳ này</th>
          <th class="right">${ico("drop", "sm")}Nước kỳ trước</th><th class="right">Nước kỳ này</th><th>Tình trạng</th></tr>
      ${rows.map(({ room, e, w }) => `<tr>
        <td class="num strong">${esc(room.room_number)}</td>
        <td class="right sub num">${e.prev ? fmtQty(e.prev.reading_value) : "—"}</td>${cell(room, "ELECTRIC", e)}
        <td class="right sub num">${w.prev ? fmtQty(w.prev.reading_value) : "—"}</td>${cell(room, "WATER", w)}
        <td>${e.cur && w.cur ? '<span class="tag g">Đã nhập</span>' : '<span class="tag a">Chưa nhập</span>'}</td></tr>`).join("")}</table>`
      : empty("Chưa có phòng nào đang cho thuê");
    $$(".meter-in", $("#tbl")).forEach((inp) => inp.addEventListener("input", () => {
      const prevV = inp.dataset.prev === "" ? null : num(inp.dataset.prev);
      const out = inp.nextElementSibling;
      if (inp.value === "") { inp.classList.remove("bad"); out.textContent = ""; return; }
      const used = num(inp.value) - (prevV ?? 0);
      const bad = prevV !== null && used < 0;
      inp.classList.toggle("bad", bad);
      out.className = "use " + (bad ? "bad" : "");
      out.textContent = bad ? "nhỏ hơn kỳ trước" : prevV === null ? "kỳ đầu tiên" : `dùng ${fmtQty(used)} ${inp.dataset.type === "ELECTRIC" ? "kWh" : "m³"}`;
    }));
  };

  $("#per").addEventListener("change", () => { period = $("#per").value + "-01"; load(); });
  $("#save").addEventListener("click", async () => {
    const filled = $$(".meter-in", $("#tbl")).filter((x) => x.value !== "");
    if (!filled.length) return toast("Bạn chưa nhập chỉ số nào.", "err");
    if (filled.some((x) => x.classList.contains("bad"))) return toast("Có chỉ số nhỏ hơn kỳ trước, vui lòng kiểm tra lại.", "err");
    $("#save").disabled = true;
    try {
      const res = await must("POST", "/api/v1/meter-readings/batch", {
        property_id: pid, period,
        readings: filled.map((x) => ({ property_id: pid, room_id: x.dataset.room, utility_type: x.dataset.type,
                                       period, reading_value: x.value })),
      });
      await load();
      if (res.skipped) {
        $("#msg").insertAdjacentHTML("afterbegin", `<div class="note alarm">${ico("alert")}<div>
          <b>Đã lưu ${res.inserted} chỉ số, ${res.skipped} chỉ số bị từ chối:</b><br>${res.errors.map((e) => esc(e.reason)).join("<br>")}</div></div>`);
      }   // lưu đủ: bảng tải lại hiện số vừa nhập — không cần thông báo
    } catch (err) { toast(err.message, "err"); }
    finally { $("#save").disabled = false; }
  });
  await load();
};

/* ======================================================================
   4. HÓA ĐƠN — phát hành hàng loạt, xem chi tiết, ghi nhận thanh toán
   ====================================================================== */
VIEWS.invoices = async (v) => {
  const pid = await propertyId();
  const arg = state.arg; state.arg = null;
  let status = arg === "OVERDUE" ? "OVERDUE" : "";
  let period = "";
  v.innerHTML = head("Sổ thu tiền", "Hóa đơn từng kỳ và tiền người thuê đã trả",
      `<button class="btn" id="issue">${ico("send", "sm")}Phát hành hóa đơn</button>`) + `
    <section class="card hero-fig inv-sum" id="sum">${skeleton()}</section>
    <div class="card"><div class="toolbar">
      <input type="month" id="per" aria-label="Lọc theo kỳ">
      ${filterBar("seg", "s", [["", "Tất cả"], ["PENDING", "Chờ thanh toán"], ["OVERDUE", "Quá hạn"], ["PAID", "Đã thanh toán"]], status)}
    </div>
    <div class="tbl-wrap" id="tbl">${skeleton()}</div></div>`;
  const markSeg = () => markFilter("seg", "s", status);

  const load = async () => {
    const [res, stats] = await Promise.all([
      api("GET", "/api/v1/invoices?" + qs({ page_size: 100, status, period })),
      api("GET", "/api/v1/invoices/stats?" + qs({ period })),
    ]);
    if (!res.ok) throw new Error(apiErr(res));
    const s = stats.data || {};
    /* Đếm theo hóa đơn: lọc một kỳ thì mỗi người thuê một hóa đơn → gọi là
       "người thuê"; xem mọi kỳ thì một người có nhiều hóa đơn → gọi "hóa đơn". */
    $("#sum").innerHTML = collectBlock(s, period ? fmtPeriod(period) : "Mọi kỳ", { who: period ? "người thuê" : "hóa đơn" });
    countUp($("#sum"));
    const list = items(res);
    const owe = (i) => num(i.total_amount) - num(i.paid_amount);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Kỳ</th><th>Phòng</th><th>Người thuê</th><th class="right">Tổng tiền</th><th class="right">Còn nợ</th><th>Hạn trả</th><th>Trạng thái</th></tr>
      ${list.map((i) => `<tr class="click" data-id="${i.id}" tabindex="0">
        <td class="nowrap">${fmtPeriod(i.period)}<div class="sub small num">${esc(i.invoice_no)}</div></td>
        <td class="num strong">${esc(i.room_number || "—")}</td><td>${esc(i.tenant_name)}</td>
        <td class="right">${money(i.total_amount)}</td>
        <td class="right ${i.days_overdue && owe(i) > 0 ? "due" : owe(i) > 0 ? "" : "sub"}">${money(Math.max(owe(i), 0))}</td>
        <td class="nowrap num">${fmtDate(i.due_date)}${i.days_overdue ? `<div class="due small">trễ ${i.days_overdue} ngày</div>` : ""}</td>
        <td>${pill(LABEL.invoice, i.status)}</td></tr>`).join("")}</table>`
      : empty("Chưa có hóa đơn nào", "Nhập chỉ số rồi bấm “Phát hành hóa đơn” để tạo hóa đơn cho kỳ mới.");
    rowsOpen($("#tbl"), (id) => invoiceDetail(id, load));
  };
  $("#per").addEventListener("change", () => { period = $("#per").value ? $("#per").value + "-01" : ""; load(); });
  $$("#seg button").forEach((b) => b.addEventListener("click", () => { status = b.dataset.s; markSeg(); load(); }));
  $("#issue").addEventListener("click", () => issueInvoices(pid, load));
  await load();
  if (arg === "issue") issueInvoices(pid, load);
};

function issueInvoices(pid, after) {
  const m = modal({
    title: "Phát hành hóa đơn",
    body: `<div class="field"><label>Kỳ hóa đơn</label><input type="month" name="period" value="${curPeriod().slice(0, 7)}"></div>
      <div class="note">${ico("alert")}<p>Hệ thống tạo hóa đơn cho mọi hợp đồng đang hiệu lực: tiền phòng, điện nước theo bậc thang và phí dịch vụ.
        Hợp đồng nào đã có hóa đơn kỳ này sẽ được bỏ qua, bấm lại nhiều lần cũng không bị trùng.</p></div>
      <div id="job" class="hidden"><div class="progress"><i></i></div><div class="sub" id="job-t"></div></div>`,
    submit: "Phát hành",
    onSubmit: async (form) => {
      const period = val(form, "period") + "-01";
      let job = await must("POST", "/api/v1/billing-jobs", { property_id: pid, period, skip_existing: true });
      $("#job", form).classList.remove("hidden");
      for (let i = 0; i < 60 && ["PENDING", "RUNNING"].includes(job.status); i++) {
        $("#job-t", form).textContent = `Đang xử lý ${job.processed}/${job.total_contracts || "…"} hợp đồng`;
        $(".progress i", form).style.width = Math.round(job.progress || 0) + "%";   // progress: 0–100
        await new Promise((r) => setTimeout(r, 1200));
        job = await must("GET", "/api/v1/billing-jobs/" + job.id);
      }
      $(".progress i", form).style.width = "100%";
      if (job.status === "FAILED") throw new Error(job.error || "Phát hành thất bại.");
      toast(`Đã xử lý ${job.processed} hợp đồng: ${job.succeeded} thành công${job.failed ? `, ${job.failed} lỗi` : ""}.`, job.failed ? "err" : "ok");
      after();
      return true;
    },
  });
  return m;
}

async function invoiceDetail(id, after) {
  const [inv, pays] = await Promise.all([must("GET", "/api/v1/invoices/" + id), must("GET", `/api/v1/invoices/${id}/payments`)]);
  const remaining = num(inv.total_amount) - num(inv.paid_amount);
  const canPay = !["PAID", "CANCELLED"].includes(inv.status) && remaining > 0;
  const m = modal({
    wide: true,
    title: `Hóa đơn ${fmtPeriod(inv.period).toLowerCase()} ${pill(LABEL.invoice, inv.status)}`,
    body: `
      ${receipt(inv)}
      ${pays.length ? `<div class="section-t">Lịch sử thanh toán</div><table>${pays.map((p) => `<tr>
          <td class="num">${fmtDate(p.received_at)}</td><td class="sub">${LABEL.method[p.method] || esc(p.method)}${p.receipt_no ? " · " + esc(p.receipt_no) : ""}</td>
          <td class="right">${money(p.amount)}</td></tr>`).join("")}</table>` : ""}
      ${canPay ? `<div class="section-t">Ghi nhận thanh toán</div>
        <div class="row2"><div class="field"><label>Số tiền</label><input name="amount" type="number" min="1000" step="1000" value="${remaining}" required></div>
          <div class="field"><label>Hình thức</label><select name="method">${options(LABEL.method, "BANK_TRANSFER")}</select></div></div>
        <div class="row2"><div class="field"><label>Mã giao dịch / số phiếu thu</label><input name="receipt_no" maxlength="50"></div>
          <div class="field"><label>Ghi chú</label><input name="note" maxlength="500"></div></div>
        <div data-confirm></div>` : ""}`,
    submit: canPay ? "Ghi nhận thanh toán" : null,
    onSubmit: canPay ? async (form) => {
      const amount = val(form, "amount");
      if (!(num(amount) > 0)) throw new Error("Số tiền phải lớn hơn 0.");
      if (num(amount) > remaining) throw new Error(`Số tiền lớn hơn số còn nợ (${fmtMoney(remaining)}).`);
      /* ⭐ Xác nhận 2 bước: không có API hoàn/huỷ thanh toán, gõ nhầm một số 0
         là sổ sách sai mà không sửa được trên phần mềm. Lần bấm đầu chỉ hiện
         bản tóm tắt; đổi số tiền hoặc hình thức thì phải xác nhận lại. */
      const sig = amount + "|" + val(form, "method");
      if (form.dataset.confirmed !== sig) {
        form.dataset.confirmed = sig;
        $("[data-confirm]", form).innerHTML = `<div class="note alarm">${ico("alert")}<div>
          Xác nhận đã nhận <b class="num">${fmtMoney(amount)}</b> bằng <b>${esc(LABEL.method[val(form, "method")])}</b>
          từ ${esc(inv.tenant_name)} (phòng ${esc(inv.room_number || "—")})?<br>
          Sau khi ghi nhận sẽ không xóa được trên phần mềm.</div></div>`;
        $("button[type=submit]", form).textContent = "Xác nhận đã nhận tiền";
        return false;
      }
      await must("POST", `/api/v1/invoices/${id}/payments`, {
        amount, method: val(form, "method"), receipt_no: val(form, "receipt_no") || null, note: val(form, "note") || null,
      });
      state.flash = id;   // dòng hóa đơn lóe lên khi bảng vẽ lại — không cần thông báo
      after && after();
    } : null,
  });
  printButton(m);
}

/* Nút "In biên lai" cạnh nút Đóng — in chỉ phần .receipt (xem @media print) */
/* Đưa các nút thao tác (.acts trong thân hộp thoại) xuống chân hộp thoại:
   nút chính nằm bên phải "Đóng" (chỗ mắt tìm hành động), nút nguy hiểm
   (hủy / chấm dứt) dạt sang mép trái để khó bấm nhầm. */
function actsToFooter(m) {
  const acts = $(".modal-b .acts", m.el);
  if (!acts) return;
  const f = $(".modal-f", m.el);
  $$("button", acts).forEach((b) => {
    if (b.classList.contains("danger")) f.prepend(b); else f.append(b);
  });
  acts.remove();
}

function printButton(m) {
  const f = $(".modal-f", m.el);
  f.insertAdjacentHTML("afterbegin", `<button type="button" class="btn ghost" data-print>${ico("printer", "sm")}In biên lai</button>`);
  $("[data-print]", f).addEventListener("click", () => window.print());
}

/* Biên lai: đầu có logo + số hóa đơn, thân là các khoản như sổ, chân là hạn trả */
function receipt(inv) {
  return `<div class="receipt">
    <div class="receipt-head">
      <div><img class="brand-light" src="/brand/wordmark.svg?v=1" alt="EZ-Rent" width="114" height="20"><img class="brand-dark" src="/brand/wordmark-dark.svg?v=1" alt="EZ-Rent" width="114" height="20">
        <div class="strong rc-name">${esc(inv.tenant_name)}</div>
        <div class="sub">Phòng <span class="num">${esc(inv.room_number || "—")}</span></div></div>
      <div class="meta"><div class="strong">HÓA ĐƠN ${fmtPeriod(inv.period).toUpperCase()}</div>
        <div class="num">Số ${esc(inv.invoice_no)}</div><div>Hạn trả <span class="num">${fmtDate(inv.due_date)}</span></div></div>
    </div>
    ${invoiceLines(inv)}
    <div class="receipt-foot">Chuyển khoản ghi nội dung: <span class="num">${esc(inv.room_number || "")} ${esc(inv.invoice_no)}</span></div>
  </div>`;
}

function invoiceLines(inv) {
  const lines = (inv.details && inv.details.length) ? inv.details.map((d) => [d.description,
      d.quantity !== null && d.unit_price !== null ? `${fmtQty(d.quantity)} × ${fmtMoney(d.unit_price)}` : "", d.amount])
    : [["Tiền phòng", "", inv.rent_amount], ["Tiền điện", "", inv.electric_amount], ["Tiền nước", "", inv.water_amount],
       ["Dịch vụ", "", inv.service_amount]].filter((x) => num(x[2]));
  if (num(inv.late_fee_amount)) lines.push(["Phí trễ hạn", "", inv.late_fee_amount]);
  if (num(inv.discount_amount)) lines.push(["Giảm trừ", "", -num(inv.discount_amount)]);
  if (num(inv.deposit_deducted)) lines.push(["Trừ vào tiền cọc", "", -num(inv.deposit_deducted)]);
  return `<table>
    ${lines.map(([d, q, a]) => `<tr><td>${esc(d)}</td><td class="sub right num">${q}</td><td class="right">${money(a)}</td></tr>`).join("")}
    <tr class="total"><td>Tổng cộng</td><td></td><td class="right">${money(inv.total_amount)}</td></tr>
    ${num(inv.paid_amount) ? `<tr><td class="sub">Đã trả</td><td></td><td class="right sub">${money(inv.paid_amount)}</td></tr>
      <tr class="remain"><td>Còn lại</td><td></td><td class="right">${money(num(inv.total_amount) - num(inv.paid_amount))}</td></tr>` : ""}
  </table>`;
}

/* ======================================================================
   5. HỢP ĐỒNG
   ====================================================================== */
VIEWS.contracts = async (v) => {
  const pid = await propertyId();
  const arg = state.arg; state.arg = null;
  let mode = arg === "expiring" ? "expiring" : arg === "EXPIRED" ? "EXPIRED" : "ACTIVE";
  v.innerHTML = head("Hợp đồng", "Soạn, kích hoạt và theo dõi thời hạn hợp đồng thuê",
      `<button class="btn" id="new">${ico("plus", "sm")}Tạo hợp đồng</button>`) + `
    <div class="card"><div class="toolbar">${filterBar("seg", "m", [["ACTIVE", "Đang hiệu lực"], ["expiring", "Sắp hết hạn"], ["EXPIRED", "Đã hết hạn"], ["draft", "Đang soạn"], ["", "Tất cả"]], mode)}</div>
    <div class="tbl-wrap" id="tbl">${skeleton()}</div></div>`;
  const load = async () => {
    markFilter("seg", "m", mode);
    const rooms = await roomMap();
    let list;
    if (mode === "expiring") list = items(await api("GET", "/api/v1/contracts/expiring?days=60"));
    else if (mode === "draft") {
      const [a, b] = await Promise.all([api("GET", "/api/v1/contracts?status=DRAFT&page_size=100"),
                                        api("GET", "/api/v1/contracts?status=PENDING_SIGN&page_size=100")]);
      list = [...items(a), ...items(b)];
    } else {
      const res = await api("GET", "/api/v1/contracts?" + qs({ status: mode, page_size: 100 }));
      if (!res.ok) throw new Error(apiErr(res));
      list = items(res);
    }
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Hợp đồng</th><th>Phòng</th><th>Người thuê</th><th>Thời hạn</th><th class="right">Giá thuê</th><th>Trạng thái</th></tr>
      ${list.map((c) => `<tr class="click" data-id="${c.id}">
        <td class="sub num">${esc(c.contract_no)}</td>
        <td class="num strong">${esc((rooms[c.room_id] || {}).room_number || c.room_number || "—")}</td>
        <td>${esc(c.primary_tenant_name)}<div class="sub small num">${esc(c.primary_tenant_phone)}</div></td>
        <td class="nowrap num">${fmtDate(c.start_date)} – ${fmtDate(c.end_date)}
          ${c.days_remaining !== null && c.days_remaining !== undefined && c.days_remaining <= 60
            ? `<div class="small strong warn-t">còn ${c.days_remaining} ngày</div>` : ""}</td>
        <td class="right">${money(c.monthly_price)}</td><td>${pill(LABEL.contract, c.status)}</td></tr>`).join("")}</table>`
      : empty(mode === "expiring" ? "Không có hợp đồng nào sắp hết hạn" : "Không có hợp đồng nào");
    rowsOpen($("#tbl"), (id) => contractDetail(id, load));
  };
  $$("#seg button").forEach((b) => b.addEventListener("click", () => { mode = b.dataset.m; load(); }));
  $("#new").addEventListener("click", () => newContract(pid, () => { mode = "draft"; load(); }));
  await load();
};

async function newContract(pid, after) {
  const [avail, tenants] = await Promise.all([
    api("GET", "/api/v1/rooms?" + qs({ status: "AVAILABLE", page_size: 100 })),
    api("GET", "/api/v1/tenants?" + qs({ is_active: true, page_size: 100 })),
  ]);
  const rooms = items(avail).sort((a, b) => a.room_number.localeCompare(b.room_number));
  const people = items(tenants).filter((t) => !t.current_contract_id);
  if (!rooms.length) return toast("Không còn phòng trống để tạo hợp đồng.", "err");
  if (!people.length) return toast("Chưa có người thuê nào chưa có hợp đồng. Hãy thêm người thuê trước.", "err");
  const start = today();
  const m = modal({
    title: "Tạo hợp đồng",
    body: `
      <div class="row2"><div class="field"><label>Phòng</label><select name="room">${rooms.map((r) =>
          `<option value="${r.id}" data-price="${num(r.base_price)}">${esc(r.room_number)} · ${fmtMoney(r.base_price)}</option>`).join("")}</select></div>
        <div class="field"><label>Người thuê</label><select name="tenant">${people.map((t) =>
          `<option value="${t.id}">${esc(t.full_name)} · ${esc(t.phone)}</option>`).join("")}</select></div></div>
      <div class="row2"><div class="field"><label>Ngày bắt đầu</label><input type="date" name="start" value="${start}"></div>
        <div class="field"><label>Ngày kết thúc</label><input type="date" name="end" value="${addMonths(start, 12)}"></div></div>
      <div class="row2"><div class="field"><label>Giá thuê / tháng</label><input type="number" step="1000" name="price" value="${num(rooms[0].base_price)}"></div>
        <div class="field"><label>Tiền cọc</label><input type="number" step="1000" name="deposit" value="${num(rooms[0].base_price)}"></div></div>
      <div class="help muted">Hợp đồng được tạo ở trạng thái nháp. Sau khi thu cọc, bấm “Kích hoạt” để phòng chuyển sang đang thuê.</div>`,
    submit: "Tạo hợp đồng",
    onSubmit: async (form) => {
      const t = people.find((x) => x.id === val(form, "tenant"));
      const created = await must("POST", "/api/v1/contracts", {
        property_id: pid, room_id: val(form, "room"), primary_tenant_id: t.id,
        primary_tenant_name: t.full_name, primary_tenant_phone: t.phone, primary_tenant_email: t.email || null,
        start_date: val(form, "start"), end_date: val(form, "end"),
        monthly_price: val(form, "price"), deposit_amount: val(form, "deposit") || "0", room_id_confirmed: true,
      });
      // Bảng chuyển sang "Đang soạn" và dòng hợp đồng nháp vừa tạo lóe lên — không cần thông báo
      state.rooms = null;
      state.flash = created.id;
      after();
    },
  });
  m.form.elements.room.addEventListener("change", (e) => {
    const p = e.target.selectedOptions[0].dataset.price;
    m.form.elements.price.value = p; m.form.elements.deposit.value = p;
  });
}

async function contractDetail(id, after) {
  const c = await must("GET", "/api/v1/contracts/" + id);
  const rooms = await roomMap();
  const act = (label, cls, fn) => ({ label, cls, fn });
  const acts = [];
  const run = async (fn, ok) => { try { await fn(); toast(ok); state.rooms = null; state.flash = id; m.close(); after(); } catch (e) { toast(e.message, "err"); } };
  if (c.status === "DRAFT") acts.push(act("Gửi người thuê ký", "", () => run(() => must("POST", `/api/v1/contracts/${id}/send`), "Đã chuyển sang chờ ký.")));
  if (["DRAFT", "PENDING_SIGN"].includes(c.status) && !c.deposit_paid_at && num(c.deposit_amount) > 0)
    acts.push(act("Thu tiền cọc", "ghost", () => { m.close(); depositForm(c, after); }));
  if (c.status === "PENDING_SIGN" && (c.deposit_paid_at || !num(c.deposit_amount)))
    acts.push(act("Kích hoạt", "", () => run(() => must("POST", `/api/v1/contracts/${id}/activate`, { confirm_deposit: true }), "Hợp đồng đã có hiệu lực.")));
  if (["DRAFT", "PENDING_SIGN"].includes(c.status))
    acts.push(act("Hủy hợp đồng", "danger", () => { m.close(); reasonForm("Hủy hợp đồng", 5, (r) => must("POST", `/api/v1/contracts/${id}/cancel?` + qs({ reason: r })), "Đã hủy hợp đồng.", after); }));
  if (c.status === "ACTIVE")
    acts.push(act("Chấm dứt sớm", "danger", () => { m.close(); reasonForm("Chấm dứt hợp đồng", 10, (r) => must("POST", `/api/v1/contracts/${id}/terminate`, { reason: r, refund_deposit: true }), "Đã chấm dứt hợp đồng.", after); }));

  const m = modal({
    title: `Hợp đồng ${esc(c.contract_no)} ${pill(LABEL.contract, c.status)}`,
    body: `<dl class="kv">
        <dt>Phòng</dt><dd class="num strong">${esc((rooms[c.room_id] || {}).room_number || "—")}</dd>
        <dt>Người thuê</dt><dd>${esc(c.primary_tenant_name)} · <span class="num">${esc(c.primary_tenant_phone)}</span></dd>
        <dt>Thời hạn</dt><dd class="num">${fmtDate(c.start_date)} – ${fmtDate(c.end_date)}</dd>
        <dt>Giá thuê</dt><dd>${money(c.monthly_price)} / tháng</dd>
        <dt>Tiền cọc</dt><dd>${money(c.deposit_amount)} ${c.deposit_paid_at ? `<span class="tag g">đã thu ${fmtDate(c.deposit_paid_at)}</span>` : num(c.deposit_amount) ? '<span class="tag a">chưa thu</span>' : ""}</dd>
        ${num(c.deposit_deducted) ? `<dt>Cọc còn lại</dt><dd>${money(c.remaining_deposit)}</dd>` : ""}
        ${c.terminated_reason ? `<dt>Lý do kết thúc</dt><dd>${esc(c.terminated_reason)}</dd>` : ""}
      </dl>
      ${acts.length ? `<div class="acts">${acts.map((a, i) =>
        `<button type="button" class="btn ${a.cls}" data-act="${i}">${a.label}</button>`).join("")}</div>` : ""}`,
  });
  $$("[data-act]", m.el).forEach((b) => b.addEventListener("click", () => acts[b.dataset.act].fn()));
  actsToFooter(m);
}

function depositForm(c, after) {
  modal({
    title: "Thu tiền cọc",
    body: `<div class="row2"><div class="field"><label>Số tiền</label><input name="amount" type="number" step="1000" value="${num(c.deposit_amount)}"></div>
      <div class="field"><label>Hình thức</label><select name="method">${options({ CASH: "Tiền mặt", BANK_TRANSFER: "Chuyển khoản", MOMO: "MoMo" }, "BANK_TRANSFER")}</select></div></div>
      <div class="field"><label>Số phiếu thu</label><input name="receipt_no" maxlength="50"></div>`,
    submit: "Ghi nhận",
    onSubmit: async (form) => {
      await must("POST", `/api/v1/contracts/${c.id}/deposit`, { amount: val(form, "amount"), method: val(form, "method"), receipt_no: val(form, "receipt_no") || null });
      toast("Đã ghi nhận tiền cọc — mở lại hợp đồng để kích hoạt.");
      state.flash = c.id;
      after();
    },
  });
}

function reasonForm(title, minLen, call, ok, after) {
  modal({
    title,
    body: `<div class="field"><label>Lý do</label><textarea name="reason" minlength="${minLen}" required></textarea>
      <div class="help">Tối thiểu ${minLen} ký tự. Lý do được lưu vào lịch sử hợp đồng.</div></div>`,
    submit: "Xác nhận", danger: true,
    onSubmit: async (form) => {
      const r = val(form, "reason");
      if (r.length < minLen) throw new Error(`Lý do cần ít nhất ${minLen} ký tự.`);
      await call(r);
      toast(ok);
      state.rooms = null;
      after();
    },
  });
}

/* ======================================================================
   6. NGƯỜI THUÊ
   ====================================================================== */
VIEWS.tenants = async (v) => {
  const pid = await propertyId();
  v.innerHTML = head("Người thuê", "Hồ sơ người thuê. Số CCCD được mã hóa và chỉ hiện 4 số cuối.",
      `<button class="btn" id="new">${ico("plus", "sm")}Thêm người thuê</button>`) + `
    <div class="card"><div class="toolbar"><div class="search">${ico("search", "sm")}<input id="q" type="search" aria-label="Tìm người thuê" placeholder="Tìm theo tên, số điện thoại, email"></div></div>
    <div class="tbl-wrap" id="tbl">${skeleton()}</div></div>`;
  const load = async () => {
    const [res, rooms] = await Promise.all([api("GET", "/api/v1/tenants?" + qs({ page_size: 100, search: $("#q").value.trim() })), roomMap()]);
    if (!res.ok) throw new Error(apiErr(res));
    const list = items(res);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Họ tên</th><th>Điện thoại</th><th>CCCD</th><th>Phòng</th><th>Đánh giá</th></tr>
      ${list.map((t) => `<tr class="click" data-id="${t.id}">
        <td><div class="strong">${esc(t.full_name)}</div><div class="sub small">${esc(t.occupation || t.email || "")}</div></td>
        <td class="nowrap num">${esc(t.phone)}</td><td class="sub num">${esc(t.id_card_masked || "—")}</td>
        <td class="num strong">${t.current_room_id ? esc((rooms[t.current_room_id] || {}).room_number || "—") : '<span class="sub">—</span>'}</td>
        <td>${t.is_active ? pill(LABEL.risk, t.risk_level) : '<span class="tag quiet">Đã rời đi</span>'}</td></tr>`).join("")}</table>`
      : empty("Không tìm thấy người thuê nào");
    rowsOpen($("#tbl"), (id) => tenantDetail(list.find((x) => x.id === id), rooms));
  };
  $("#q").addEventListener("input", debounce(load, 250));
  $("#new").addEventListener("click", () => newTenant(pid, load));
  await load();
};

function tenantDetail(t, rooms) {
  modal({
    title: esc(t.full_name),
    body: `<dl class="kv">
      <dt>Điện thoại</dt><dd class="num">${esc(t.phone)}</dd><dt>Email</dt><dd>${esc(t.email || "—")}</dd>
      <dt>Ngày sinh</dt><dd class="num">${fmtDate(t.date_of_birth)}</dd><dt>Quê quán</dt><dd>${esc(t.address || "—")}</dd>
      <dt>Nghề nghiệp</dt><dd>${esc(t.occupation || "—")}</dd>
      <dt>CCCD</dt><dd class="num">${esc(t.id_card_masked || "—")}</dd>
      <dt>Phòng hiện tại</dt><dd class="num">${t.current_room_id ? esc((rooms[t.current_room_id] || {}).room_number || "—") : "—"}</dd>
      <dt>Liên hệ khẩn cấp</dt><dd>${t.emergency_contact_name ? `${esc(t.emergency_contact_name)} · ${esc(t.emergency_contact_phone || "")}` : "—"}</dd>
      <dt>Đánh giá</dt><dd>${pill(LABEL.risk, t.risk_level)} ${t.risk_note ? `<span class="sub">${esc(t.risk_note)}</span>` : ""}</dd></dl>`,
  });
}

function newTenant(pid, after) {
  modal({
    title: "Thêm người thuê",
    body: `
      <div class="field"><label>Họ và tên</label><input name="full_name" required minlength="2"></div>
      <div class="row2"><div class="field"><label>Số điện thoại</label><input name="phone" required inputmode="tel" placeholder="09xxxxxxxx"></div>
        <div class="field"><label>Số CCCD</label><input name="id_card" inputmode="numeric" maxlength="12" placeholder="12 chữ số"></div></div>
      <div class="row2"><div class="field"><label>Ngày sinh</label><input name="dob" type="date"></div>
        <div class="field"><label>Giới tính</label><select name="gender"><option value="">—</option><option value="M">Nam</option><option value="F">Nữ</option><option value="OTHER">Khác</option></select></div></div>
      <div class="row2"><div class="field"><label>Email</label><input name="email" type="email"></div>
        <div class="field"><label>Nghề nghiệp</label><input name="occupation" maxlength="100"></div></div>
      <div class="field"><label>Quê quán / địa chỉ thường trú</label><input name="address"></div>
      <div class="row2"><div class="field"><label>Người liên hệ khẩn cấp</label><input name="ec_name"></div>
        <div class="field"><label>SĐT liên hệ khẩn cấp</label><input name="ec_phone" inputmode="tel"></div></div>`,
    submit: "Lưu hồ sơ",
    onSubmit: async (form) => {
      const idc = val(form, "id_card");
      if (idc && !/^(\d{9}|\d{12})$/.test(idc)) throw new Error("Số CCCD phải gồm 12 chữ số (hoặc CMND 9 số).");
      const created = await must("POST", "/api/v1/tenants", {
        property_id: pid, full_name: val(form, "full_name"), phone: val(form, "phone"),
        id_card_number: idc || null, date_of_birth: val(form, "dob") || null, gender: val(form, "gender") || null,
        email: val(form, "email") || null, occupation: val(form, "occupation") || null, address: val(form, "address") || null,
        emergency_contact_name: val(form, "ec_name") || null, emergency_contact_phone: val(form, "ec_phone") || null,
      });
      state.flash = created.id;
      after();   // người mới hiện ngay trong bảng và lóe lên — không cần thông báo
    },
  });
}

/* ======================================================================
   7. SỰ CỐ (quản lý)
   ====================================================================== */
VIEWS.incidents = async (v) => {
  let open = false;   // mặc định xem tất cả phiếu
  v.innerHTML = head("Sự cố", "Phiếu báo hỏng từ người thuê và quản lý") + `
    <div class="card"><div class="toolbar">${filterBar("seg", "o", [["", "Tất cả"], ["1", 'Chưa xử lý xong<span class="count hidden" id="open-count"></span>']], "")}</div>
    <div class="tbl-wrap" id="tbl">${skeleton()}</div></div>`;
  const load = async () => {
    const res = await api("GET", "/api/v1/incidents?" + qs({ page_size: 100, is_open: open || "" }));
    if (!res.ok) throw new Error(apiErr(res));
    const list = items(res);
    /* Số phiếu chưa xử lý xong: hiện ở nút lọc và ở tab "Sự cố" (cùng một số) */
    const openCount = open ? list.length : list.filter((x) => x.is_open).length;
    setBadge("incidents", openCount);
    $("#open-count").textContent = openCount;
    $("#open-count").classList.toggle("hidden", !openCount);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Sự cố</th><th>Phòng</th><th>Người báo</th><th>Mức độ</th><th>Báo lúc</th><th>Trạng thái</th></tr>
      ${list.map((i) => `<tr class="click" data-id="${i.id}">
        <td><div class="strong">${esc(i.title)}</div><div class="sub small"><span class="num">${esc(i.ticket_no)}</span> · ${LABEL.category[i.category] || esc(i.category)}</div></td>
        <td class="num strong">${esc(i.room_number || "—")}</td><td>${esc(i.reported_by_name)}</td>
        <td>${pill(LABEL.priority, i.priority)}</td><td class="nowrap num">${fmtDate(i.created_at)}</td>
        <td>${pill(LABEL.incident, i.status)}</td></tr>`).join("")}</table>`
      : empty(open ? "Không có sự cố nào đang chờ" : "Chưa có phiếu sự cố nào");
    rowsOpen($("#tbl"), (id) => incidentDetail(id, load));
  };
  $$("#seg button").forEach((b) => b.addEventListener("click", () => {
    markFilter("seg", "o", b.dataset.o); open = !!b.dataset.o; load();
  }));
  await load();
};

async function incidentDetail(id, after) {
  const i = await must("GET", "/api/v1/incidents/" + id);
  const call = async (path, body, ok) => {
    const btns = $$("[data-a]", m.el);
    btns.forEach((b) => { b.disabled = true; });   // chống bấm nhiều lần gửi nhiều request
    try { await must("POST", `/api/v1/incidents/${id}/${path}`, body); if (ok) toast(ok); state.flash = id; m.close(); after(); }
    catch (e) { toast(e.message, "err"); btns.forEach((b) => { b.disabled = false; }); }
  };
  const isOpen = !["RESOLVED", "CLOSED", "CANCELLED"].includes(i.status);
  const m = modal({
    wide: true,
    title: `${esc(i.title)} ${pill(LABEL.incident, i.status)}`,
    body: `<dl class="kv">
        <dt>Mã phiếu</dt><dd class="num">${esc(i.ticket_no)}</dd>
        <dt>Phòng</dt><dd class="strong">${esc(i.room_number || "Khu vực chung")}</dd>
        <dt>Loại · mức độ</dt><dd>${LABEL.category[i.category] || esc(i.category)} · ${pill(LABEL.priority, i.priority)}</dd>
        <dt>Người báo</dt><dd>${esc(i.reported_by_name)}${i.reported_by_phone ? " · " + esc(i.reported_by_phone) : ""}</dd>
        <dt>Báo lúc</dt><dd>${new Date(i.created_at).toLocaleString("vi-VN")}</dd>
        ${i.description ? `<dt>Mô tả</dt><dd class="pre">${esc(i.description)}</dd>` : ""}
        ${i.assigned_to_name ? `<dt>Người xử lý</dt><dd>${esc(i.assigned_to_name)}</dd>` : ""}
        ${i.resolution ? `<dt>Kết quả</dt><dd class="pre">${esc(i.resolution)}</dd>` : ""}
        ${i.cost ? `<dt>Chi phí</dt><dd>${money(i.cost)}</dd>` : ""}
        ${i.rating ? `<dt>Người thuê đánh giá</dt><dd>${i.rating}/5 ${esc(i.rating_comment || "")}</dd>` : ""}
      </dl>
      ${i.status === "IN_PROGRESS" ? `<div class="section-t">Báo đã xử lý xong</div>
        ${i.is_safety_critical ? `<div class="note alarm">${ico("alert")}<div>
          <b>Sự cố nguy hiểm (điện / gas / kết cấu).</b> Phải có người kiểm tra an toàn mới được đánh dấu xong —
          tên tài khoản của bạn sẽ được ghi vào phiếu làm người xác nhận.
          <label class="check"><input type="checkbox" name="safe"> Tôi đã kiểm tra an toàn sau khi sửa</label></div></div>` : ""}
        <div class="field narrow"><label for="cost">Chi phí (nếu có)</label><input id="cost" name="cost" type="number" step="1000" min="0"></div>` : ""}
      <div class="acts">
        ${["OPEN", "ASSIGNED"].includes(i.status) ? `<button type="button" class="btn" data-a="start">Bắt đầu xử lý</button>` : ""}
        ${i.status === "IN_PROGRESS" ? `<button type="button" class="btn" data-a="resolve">Đã xử lý xong</button>` : ""}
        ${i.status === "RESOLVED" ? `<button type="button" class="btn" data-a="close">Đóng phiếu</button>` : ""}
        ${isOpen ? `<button type="button" class="btn danger" data-a="cancel">Hủy phiếu (báo nhầm)</button>` : ""}
      </div>`,
  });
  actsToFooter(m);
  const on = (a, fn) => { const b = $(`[data-a="${a}"]`, m.el); if (b) b.addEventListener("click", fn); };
  on("start", () => call("start", undefined, null));   // trạng thái đổi ngay trong bảng — im lặng
  on("resolve", () => {
    const body = { cost: val(m.form, "cost") || null };
    if (i.is_safety_critical) {
      if (!m.form.elements.safe.checked) return toast("Hãy xác nhận đã kiểm tra an toàn trước khi đánh dấu xong.", "err");
      // Server ghi người ký theo JWT; id gửi lên chỉ để báo "có xác nhận"
      body.verified_by = state.user.id;
    }
    call("resolve", body, "Đã đánh dấu xử lý xong.");
  });
  on("close", () => call("close", {}, "Đã đóng phiếu."));
  on("cancel", () => { m.close(); reasonForm("Hủy phiếu sự cố", 3, (r) => must("POST", `/api/v1/incidents/${id}/cancel?` + qs({ reason: r })), "Đã hủy phiếu.", after); });
}

/* ======================================================================
   8. NGƯỜI THUÊ — hóa đơn của tôi (GET /invoices/mine)
   ====================================================================== */
/* ======================================================================
   7b. NGƯỜI THUÊ — "Phòng của tôi": một màn trả lời 5 câu hay hỏi chủ trọ
       (trả bao nhiêu · hợp đồng còn bao lâu · điện nước có tăng · sự cố tới
       đâu · có tin gì mới). Mọi API lọc theo tenant_id trong JWT.
   ====================================================================== */
const fmtAgo = (iso) => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} ngày trước`;
  return fmtDate(iso);
};
/* Thông báo chưa đọc → số đếm trên tab "Thông báo" */
const inboxBadge = (list) => setBadge("inbox", list.filter((n) => !n.read_at).length);
const noteTitle = (n) => n.subject || (n.body || "").split("\n")[0].slice(0, 90) || "Thông báo";

/* Lượng điện / nước theo kỳ, lấy từ chi tiết hóa đơn (item_type ELECTRIC / WATER) */
function usageSeries(invoices, type) {
  return invoices.map((i) => {
    const d = (i.details || []).find((x) => x.item_type === type);
    return { period: i.period, qty: d && d.quantity !== null ? num(d.quantity) : null };
  }).filter((x) => x.qty !== null).sort((a, b) => a.period.localeCompare(b.period)).slice(-6);
}
function usageCard(series, label, unit, icon) {
  if (!series.length) return `<div class="usage"><div class="label">${ico(icon, "sm")}${label}</div><div class="sub">Chưa có số liệu.</div></div>`;
  const last = series[series.length - 1], prev = series[series.length - 2];
  const diff = prev && prev.qty ? Math.round(((last.qty - prev.qty) / prev.qty) * 100) : null;
  const trend = diff === null ? "" : diff > 0
    ? `<span class="warn-t">tăng ${diff}% so với ${fmtPeriod(prev.period).toLowerCase()}</span>`
    : diff < 0 ? `<span class="ok-t">giảm ${-diff}% so với ${fmtPeriod(prev.period).toLowerCase()}</span>`
    : `<span class="sub">bằng ${fmtPeriod(prev.period).toLowerCase()}</span>`;
  return `<div class="usage">
    <div class="label">${ico(icon, "sm")}${label}</div>
    <div class="usage-now"><span class="num">${fmtQty(last.qty)}</span> ${unit} <span class="sub">· ${fmtPeriod(last.period).toLowerCase()}</span></div>
    <div class="small">${trend}</div>
    ${usageLine(series, `${label} ${series.length} kỳ gần nhất: ${series.map((x) => `${fmtPeriod(x.period)} ${fmtQty(x.qty)} ${unit}`).join(", ")}`)}
  </div>`;
}

/* Biểu đồ đường SVG tự vẽ (không thư viện — CSP chỉ cho script cùng nguồn).
   Trục dọc không bắt đầu từ 0 mà ôm sát khoảng giá trị: thứ người thuê cần thấy
   là XU HƯỚNG lên/xuống giữa các tháng. Đường vẽ dần một lần (pathLength=1). */
function usageLine(series, aria) {
  const W = 320, H = 140, L = 18, R = 18, T = 26, B = 24;
  const vals = series.map((x) => x.qty);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || Math.max(hi, 1);          // mọi tháng bằng nhau → đường nằm giữa
  const pad = span * 0.25;
  const x = (k) => series.length === 1 ? W / 2 : L + (k * (W - L - R)) / (series.length - 1);
  const y = (v) => T + (1 - (v - (lo - pad)) / (span + 2 * pad)) * (H - T - B);
  const pts = series.map((p, k) => [x(k), y(p.qty)]);
  const line = pts.map(([px, py], k) => `${k ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${H - B} L${pts[0][0].toFixed(1)},${H - B} Z`;
  const now = series.length - 1;
  return `<svg class="uline" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(aria)}">
    <line class="base" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
    <path class="area" d="${area}"/>
    <path class="stroke" d="${line}" pathLength="1"/>
    ${pts.map(([px, py], k) => `<circle class="${k === now ? "pt now" : "pt"}" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${k === now ? 4.5 : 3}"/>
      <text class="${k === now ? "v now" : "v"}" x="${px.toFixed(1)}" y="${(py - 9).toFixed(1)}">${fmtQty(series[k].qty)}</text>
      <text class="m" x="${px.toFixed(1)}" y="${H - 6}">T${Number(series[k].period.slice(5, 7))}</text>`).join("")}
  </svg>`;
}

/* Lưới 2×2 dưới ô tiền — mọi số tính từ /invoices/mine + /contracts/mine, không cần API mới.
   Hai ô là ƯỚC TÍNH và ghi rõ cách tính, để không ai hiểu nhầm là số chính thức. */
const FACT_PARTS = [["RENT", "Phòng", "rent"], ["ELECTRIC", "Điện", "elec"], ["WATER", "Nước", "water"], ["SERVICE", "Dịch vụ", "svc"]];
function moneyFacts(invoices, contract) {
  const list = invoices.filter((i) => i.status !== "CANCELLED").sort((a, b) => b.period.localeCompare(a.period));
  if (!list.length) return "";
  const latest = list[0];
  const sumType = (inv, types) => (inv.details || []).filter((d) => types.includes(d.item_type)).reduce((a, d) => a + num(d.amount), 0);

  // 1 · Tiền đi đâu (kỳ gần nhất): phòng / điện / nước / dịch vụ / khác
  const parts = FACT_PARTS.map(([t, label, cls]) => [label, cls, sumType(latest, [t])]);
  const other = num(latest.total_amount) - parts.reduce((a, p) => a + p[2], 0);
  if (Math.abs(other) >= 1000) parts.push(["Khác", "other", other]);
  const positive = parts.filter((p) => p[2] > 0), base = positive.reduce((a, p) => a + p[2], 0) || 1;
  const short = (v) => v >= 1e6 ? `${(v / 1e6).toLocaleString("vi-VN", { maximumFractionDigits: 2 })}tr` : `${Math.round(v / 1000).toLocaleString("vi-VN")}k`;

  // 2 · Dự kiến tháng tới = tiền phòng + trung bình (điện + nước + dịch vụ) tối đa 3 kỳ gần nhất
  const recent = list.slice(0, 3);
  const variable = recent.reduce((a, i) => a + sumType(i, ["ELECTRIC", "WATER", "SERVICE"]), 0) / recent.length;
  const rent = contract && contract.status !== "EXPIRED" ? num(contract.monthly_price) : sumType(latest, ["RENT"]);
  const forecast = Math.round((rent + variable) / 1000) * 1000;
  const nextPeriod = shiftPeriod(latest.period, 1);

  // 3 · Trả đúng hạn: kỳ đã trả đủ mà không bị tính phí trễ hạn (hệ thống không lưu ngày trả)
  const paid = list.filter((i) => i.status === "PAID");
  const onTime = paid.filter((i) => !(i.details || []).some((d) => d.item_type === "LATE_FEE")).length;

  // 4 · Đã trả trong năm nay
  const year = String(new Date().getFullYear());
  const thisYear = list.filter((i) => i.period.startsWith(year) && num(i.paid_amount) > 0);
  const paidYear = thisYear.reduce((a, i) => a + num(i.paid_amount), 0);

  return `<div class="facts">
    <div class="fact">
      <div class="k">Tiền đi đâu · ${fmtPeriod(latest.period).toLowerCase()}</div>
      <div class="segbar" role="img" aria-label="${positive.map((p) => `${p[0]} ${fmtMoney(p[2])}`).join(", ")}">
        ${positive.map((p) => `<i class="seg-${p[1]}" style="width:${((p[2] / base) * 100).toFixed(1)}%"></i>`).join("")}</div>
      <div class="seglegend">${parts.map((p) => `<span><i class="sw seg-${p[1]}"></i>${p[0]} <b class="num">${p[2] < 0 ? "−" : ""}${short(Math.abs(p[2]))}</b></span>`).join("")}</div>
    </div>
    <div class="fact">
      <div class="k">Dự kiến ${fmtPeriod(nextPeriod).toLowerCase()}</div>
      <div class="v">≈ ${fmtMoney(forecast)}</div>
      <div class="s">hạn khoảng ${fmtDate(addMonths(latest.due_date, 1))} · ước tính từ ${recent.length} tháng gần nhất</div>
    </div>
    <div class="fact">
      <div class="k">Trả đúng hạn</div>
      <div class="v">${paid.length ? `${onTime}/${paid.length} tháng` : "—"}</div>
      <div class="s">tính theo tháng không bị phí trễ hạn</div>
    </div>
    <div class="fact">
      <div class="k">Đã trả năm ${year}</div>
      <div class="v">${fmtMoney(paidYear)}</div>
      <div class="s">${thisYear.length} tháng</div>
    </div>
  </div>`;
}

VIEWS.room = async (v) => {
  const [inv, con, inc, noti] = await Promise.all([
    api("GET", "/api/v1/invoices/mine?limit=12"),
    api("GET", "/api/v1/contracts/mine"),
    api("GET", "/api/v1/incidents?page_size=50"),
    api("GET", "/api/v1/notifications/mine?limit=30"),
  ]);
  const invoices = inv.ok && Array.isArray(inv.data) ? inv.data : [];
  const contract = con.ok && Array.isArray(con.data) ? con.data[0] : null;
  const incidents = items(inc).filter((x) => x.is_open);
  const notes = noti.ok && Array.isArray(noti.data) ? noti.data : [];
  if (noti.ok) inboxBadge(notes);
  if (invoices.length) state.myRoom = { id: invoices[0].room_id, number: invoices[0].room_number };
  const roomNo = (contract && contract.room_number) || (state.myRoom && state.myRoom.number);

  // Tiền cần trả
  const due = invoices.filter((i) => !["PAID", "CANCELLED"].includes(i.status));
  const owed = due.reduce((a, i) => a + num(i.total_amount) - num(i.paid_amount), 0);
  const next = due.slice().sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  const late = next && next.days_overdue;

  // Hợp đồng: thanh thời gian (đã ở bao lâu / tổng thời hạn)
  let contractHtml = empty("Chưa có hợp đồng hiệu lực", "Liên hệ chủ trọ nếu bạn nghĩ đây là nhầm lẫn.");
  if (contract) {
    const start = new Date(contract.start_date), end = new Date(contract.end_date);
    const pct = Math.min(100, Math.max(0, ((Date.now() - start) / (end - start)) * 100));
    const left = contract.days_remaining;
    const expired = contract.status === "EXPIRED";
    contractHtml = `<div class="card-b">
      ${contract.status === "PENDING_SIGN" ? `<div class="note">${ico("file")}<div>Hợp đồng đang <b>chờ bạn ký</b>. Liên hệ chủ trọ để hoàn tất.</div></div>` : ""}
      ${expired ? `<div class="note alarm">${ico("alert")}<div><b>Hợp đồng đã hết hạn ngày ${fmtDate(contract.end_date)}.</b>
          Liên hệ chủ trọ để gia hạn hoặc thỏa thuận ngày trả phòng và hoàn cọc.</div></div>
        <div class="meter-key"><span>Thời hạn cũ</span><span class="num">${fmtDate(contract.start_date)} – ${fmtDate(contract.end_date)}</span></div>`
      : `<div class="contract-left"><span class="num ${left !== null && left <= 30 ? "warn-t" : ""}">${left ?? "—"}</span> ngày còn lại</div>
      <div class="meter" role="img" aria-label="Đã ở ${pct.toFixed(0)}% thời hạn hợp đồng"><i class="m-ok" style="width:${pct.toFixed(1)}%"></i></div>
      <div class="meter-key"><span class="num">${fmtDate(contract.start_date)}</span><span class="num">${fmtDate(contract.end_date)}</span></div>`}
      <dl class="kv compact">
        <dt>Mã hợp đồng</dt><dd class="num">${esc(contract.contract_no)}</dd>
        <dt>Giá thuê</dt><dd>${money(contract.monthly_price)} / tháng</dd>
        <dt>Tiền cọc</dt><dd>${money(contract.deposit_amount)} ${contract.deposit_paid_at ? '<span class="tag g">đã đóng</span>' : num(contract.deposit_amount) ? '<span class="tag a">chưa đóng</span>' : ""}</dd>
        ${contract.roommates && contract.roommates.length ? `<dt>Ở cùng</dt><dd>${contract.roommates.map((r) => esc(r.full_name)).join(", ")}</dd>` : ""}
      </dl></div>`;
  }

  v.innerHTML = head("Phòng của tôi", roomNo ? `Phòng <span class="num">${esc(roomNo)}</span>` : "") + `
    ${!inv.ok || !con.ok || !noti.ok ? `<div class="note alarm">${ico("alert")}<div>Một số mục chưa tải được — tải lại trang sau ít phút.</div></div>` : ""}
    <div class="room-grid">
      <section class="card amount-due ${owed > 0 ? "" : "paid"}">
        <div class="pay-head"><div>
        ${owed > 0 ? `<div class="label">${ico("cash")}Cần thanh toán</div>
            <span class="big ${late ? "due" : ""}" data-count="${owed}">${fmtMoney(owed)}</span>
            <div class="${late ? "due strong" : "sub"}">${late ? `Đã quá hạn ${next.days_overdue} ngày` : `Hạn trả ${fmtDate(next.due_date)}`}</div>`
          : `<div class="label">${ico("check")}Bạn đã thanh toán đủ</div><div class="sub">Không có khoản nào cần trả.</div>`}
        </div>
        <button class="btn ${owed > 0 ? "" : "ghost"}" data-go="my-invoices">${ico("receipt", "sm")}${owed > 0 ? "Xem hóa đơn & cách trả" : "Xem các tháng đã trả"}</button></div>
        ${moneyFacts(invoices, contract)}
      </section>
      <section class="card">
        <div class="card-h">${ico("file")}<h2>Hợp đồng</h2>${contract ? pill(LABEL.contract, contract.status) : ""}</div>
        ${contractHtml}
      </section>
      <section class="card span-2">
        <div class="card-h">${ico("gauge")}<h2>Điện nước của tôi</h2><span class="sub">6 kỳ gần nhất</span></div>
        <div class="card-b usage-grid">
          ${usageCard(usageSeries(invoices, "ELECTRIC"), "Điện", "kWh", "zap")}
          ${usageCard(usageSeries(invoices, "WATER"), "Nước", "m³", "drop")}
        </div>
      </section>
      <section class="card">
        <div class="card-h">${ico("wrench")}<h2>Sự cố đang xử lý</h2><span class="sub">${incidents.length || ""}</span></div>
        ${incidents.length ? `<ul class="list">${incidents.slice(0, 4).map((i) => `<li><button type="button" data-go="my-incidents">
            <span class="strong">${esc(i.title)}</span>${pill(LABEL.incident, i.status)}</button></li>`).join("")}</ul>`
          : `<div class="card-b"><div class="sub">Không có sự cố nào đang mở.</div>
             <button class="btn ghost sm room-cta" data-go="my-incidents">${ico("plus", "sm")}Báo sự cố</button></div>`}
      </section>
      <section class="card">
        <div class="card-h">${ico("bell")}<h2>Thông báo mới</h2></div>
        ${notes.length ? `<ul class="list">${notes.slice(0, 3).map((n) => `<li><button type="button" data-go="inbox" class="${n.read_at ? "" : "unread"}">
            <span><span class="strong">${esc(noteTitle(n))}</span><span class="sub small"><br>${fmtAgo(n.queued_at)}</span></span>
            ${n.read_at ? "" : '<span class="tag b">Mới</span>'}</button></li>`).join("")}</ul>`
          : `<div class="card-b sub">Chưa có thông báo nào.</div>`}
      </section>
    </div>`;
  $$("[data-go]", v).forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));
};

/* ======================================================================
   7c. NGƯỜI THUÊ — Hộp thông báo
   ====================================================================== */
VIEWS.inbox = async (v) => {
  v.innerHTML = head("Thông báo", "Nhắc hạn trả tiền, hóa đơn mới, kết quả xử lý sự cố",
      `<button class="btn ghost" id="read-all">${ico("check", "sm")}Đánh dấu đã đọc hết</button>`) + `
    <div class="card" id="list">${skeleton()}</div>`;
  let list = [];
  const render = () => {
    inboxBadge(list);
    $("#read-all").disabled = !list.some((n) => !n.read_at);
    $("#list").innerHTML = list.length ? `<ul class="list inbox">${list.map((n) => `<li>
        <button type="button" data-id="${n.id}" class="${n.read_at ? "" : "unread"}" aria-expanded="false">
          <span><span class="strong">${esc(noteTitle(n))}</span><span class="sub small"><br>${fmtAgo(n.queued_at)}</span></span>
          ${n.read_at ? "" : '<span class="tag b">Mới</span>'}</button>
        <div class="note-body pre hidden">${esc(n.body || "")}</div></li>`).join("")}</ul>`
      : empty("Chưa có thông báo nào", "Khi có hóa đơn mới hoặc sự cố được xử lý, thông báo sẽ hiện ở đây.");
    $$(".inbox button[data-id]", $("#list")).forEach((b) => b.addEventListener("click", async () => {
      const body = b.nextElementSibling;
      const open = body.classList.toggle("hidden") === false;
      b.setAttribute("aria-expanded", String(open));
      const n = list.find((x) => x.id === b.dataset.id);
      if (open && n && !n.read_at) {
        // Lạc quan: đổi ngay trên màn hình, gửi API sau; lỗi thì trả lại như cũ
        n.read_at = new Date().toISOString();
        b.classList.remove("unread"); const t = $(".tag", b); if (t) t.remove();
        inboxBadge(list); $("#read-all").disabled = !list.some((x) => !x.read_at);
        const res = await api("POST", `/api/v1/notifications/mine/${n.id}/read`, {});
        if (!res.ok) { n.read_at = null; toast("Chưa đánh dấu được đã đọc — thử lại sau.", "err"); render(); }
      }
    }));
  };
  $("#read-all").addEventListener("click", async () => {
    const unread = list.filter((n) => !n.read_at);
    unread.forEach((n) => { n.read_at = new Date().toISOString(); });
    render();
    const results = await Promise.all(unread.map((n) => api("POST", `/api/v1/notifications/mine/${n.id}/read`, {})));
    if (results.some((r) => !r.ok)) { toast("Một số thông báo chưa đánh dấu được — thử lại sau.", "err"); load(); }
  });
  const load = async () => {
    list = await must("GET", "/api/v1/notifications/mine?limit=50");
    render();
  };
  await load();
};

VIEWS["my-invoices"] = async (v) => {
  const list = await must("GET", "/api/v1/invoices/mine");
  state.myRoom = list.length ? { id: list[0].room_id, number: list[0].room_number } : null;
  const due = list.filter((i) => !["PAID", "CANCELLED"].includes(i.status));
  const owed = due.reduce((a, i) => a + num(i.total_amount) - num(i.paid_amount), 0);
  const next = due.sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  const late = next && next.days_overdue;
  v.innerHTML = head("Hóa đơn của tôi", state.myRoom ? `Phòng <span class="num">${esc(state.myRoom.number)}</span>` : "") + `
    <div class="card amount-due ${owed > 0 ? "" : "paid"}">
      ${owed > 0 ? `<div class="label">${ico("cash")}Cần thanh toán</div><span class="big ${late ? "due" : ""}">${fmtMoney(owed)}</span>
          <div class="${late ? "due strong" : "sub"}">${late ? `Đã quá hạn ${next.days_overdue} ngày` : `Hạn trả ${fmtDate(next.due_date)}`}</div>
          <button class="btn" id="pay">${ico("send", "sm")}Xem cách thanh toán</button>`
        : `<div class="label">${ico("check")}Bạn đã thanh toán đủ</div><div class="sub">Không có khoản nào cần trả.</div>`}
    </div>
    <section class="card"><div class="card-h">${ico("receipt")}<h2>Các kỳ gần đây</h2></div>
      ${list.length ? `<ul class="list">${list.map((i) => `<li><button type="button" data-id="${i.id}">
          <span><span class="strong">${fmtPeriod(i.period)}</span><span class="sub small"> · hạn ${fmtDate(i.due_date)}</span></span>
          <span class="right">${money(i.total_amount)} ${pill(LABEL.invoice, i.status)}</span></button></li>`).join("")}</ul>`
        : empty("Chưa có hóa đơn nào")}
    </section>`;
  $$(".list button[data-id]", v).forEach((el) => el.addEventListener("click", () => {
    const inv = list.find((x) => x.id === el.dataset.id);
    printButton(modal({ title: `${fmtPeriod(inv.period)} ${pill(LABEL.invoice, inv.status)}`, body: receipt(inv) }));
  }));
  const pay = $("#pay");
  if (pay) pay.addEventListener("click", () => modal({
    title: "Cách thanh toán",
    body: `<p>Chuyển khoản <b class="num">${fmtMoney(owed)}</b> với nội dung:</p>
      <div class="transfer">${esc((state.myRoom && state.myRoom.number) || "")} ${esc(next.invoice_no)}</div>
      <p class="sub">Hoặc trả tiền mặt trực tiếp cho quản lý. Hóa đơn chuyển sang “Đã thanh toán” sau khi quản lý xác nhận.</p>`,
  }));
};

/* ======================================================================
   9. NGƯỜI THUÊ — báo sự cố
   ====================================================================== */
VIEWS["my-incidents"] = async (v) => {
  if (state.myRoom === undefined) {
    const inv = items(await api("GET", "/api/v1/invoices/mine?limit=1"));
    state.myRoom = inv.length ? { id: inv[0].room_id, number: inv[0].room_number } : null;
  }
  v.innerHTML = head("Báo sự cố", "Báo hỏng hóc trong phòng, quản lý sẽ liên hệ xử lý",
      `<button class="btn" id="new">${ico("plus", "sm")}Báo sự cố mới</button>`) + `
    <div class="card" id="list">${skeleton()}</div>`;
  const load = async () => {
    const list = items(await api("GET", "/api/v1/incidents?page_size=50"));
    $("#list").innerHTML = list.length ? `<ul class="list">${list.map((i) => `<li><button type="button" data-id="${i.id}">
        <span><span class="strong">${esc(i.title)}</span>
          <span class="sub small"><br>${LABEL.category[i.category] || esc(i.category)} · ${fmtDate(i.created_at)}</span></span>
        ${pill(LABEL.incident, i.status)}</button></li>`).join("")}</ul>`
      : empty("Bạn chưa báo sự cố nào", "Có gì hỏng trong phòng, bấm “Báo sự cố mới”.");
    $$(".list button[data-id]", $("#list")).forEach((el) => el.addEventListener("click", () => myIncident(el.dataset.id, load)));
    flashChanged($("#list"));
  };
  $("#new").addEventListener("click", () => modal({
    title: "Báo sự cố mới",
    body: `
      <div class="field"><label>Vấn đề gặp phải</label><input name="title" required minlength="3" maxlength="200" placeholder="VD: Vòi nước nhà tắm bị rỉ"></div>
      <div class="row2"><div class="field"><label>Loại</label><select name="category">${options(LABEL.category, "PLUMBING")}</select></div>
        <div class="field"><label>Mức độ</label><select name="priority">
          <option value="NORMAL">Bình thường</option><option value="HIGH">Cần sửa sớm</option><option value="URGENT">Khẩn cấp (nguy hiểm)</option></select></div></div>
      <div class="field"><label>Mô tả thêm</label><textarea name="description" maxlength="5000" placeholder="Hỏng từ khi nào, ở vị trí nào…"></textarea></div>
      ${state.myRoom ? `<div class="help">Phiếu được gắn với phòng ${esc(state.myRoom.number)}.</div>` : ""}`,
    submit: "Gửi báo cáo",
    onSubmit: async (form) => {
      if (val(form, "title").length < 3) throw new Error("Vui lòng mô tả vấn đề (ít nhất 3 ký tự).");
      const created = await must("POST", "/api/v1/incidents", {
        title: val(form, "title"), category: val(form, "category"), priority: val(form, "priority"),
        description: val(form, "description") || null, room_id: state.myRoom ? state.myRoom.id : null,
        reported_by_phone: state.user.phone || null,
      });
      state.flash = created.id;
      load();   // phiếu mới hiện ngay đầu danh sách và lóe lên — không cần thông báo
    },
  }));
  await load();
};

async function myIncident(id, after) {
  const i = await must("GET", "/api/v1/incidents/" + id);
  const canRate = ["RESOLVED", "CLOSED"].includes(i.status) && !i.rating;
  modal({
    title: `${esc(i.title)} ${pill(LABEL.incident, i.status)}`,
    body: `<dl class="kv"><dt>Mã phiếu</dt><dd class="num">${esc(i.ticket_no)}</dd>
        <dt>Gửi lúc</dt><dd class="num">${new Date(i.created_at).toLocaleString("vi-VN")}</dd>
        ${i.description ? `<dt>Mô tả</dt><dd class="pre">${esc(i.description)}</dd>` : ""}
        ${i.assigned_to_name ? `<dt>Người xử lý</dt><dd>${esc(i.assigned_to_name)}</dd>` : ""}
        ${i.resolution ? `<dt>Kết quả</dt><dd class="pre">${esc(i.resolution)}</dd>` : ""}
        ${i.rating ? `<dt>Bạn đã đánh giá</dt><dd>${i.rating}/5</dd>` : ""}</dl>
      ${canRate ? `<div class="section-t">Bạn hài lòng với việc xử lý chứ?</div>
        <div class="field"><label for="rt">Mức hài lòng</label><select id="rt" name="rating"><option value="5">5 — Rất hài lòng</option><option value="4">4 — Hài lòng</option>
          <option value="3">3 — Tạm được</option><option value="2">2 — Chưa tốt</option><option value="1">1 — Rất tệ</option></select></div>
        <div class="field"><label for="cm">Góp ý thêm</label><input id="cm" name="comment" maxlength="2000" placeholder="Không bắt buộc"></div>` : ""}`,
    submit: canRate ? "Gửi đánh giá" : null,
    onSubmit: canRate ? async (form) => {
      await must("POST", `/api/v1/incidents/${id}/rating`, { rating: Number(val(form, "rating")), comment: val(form, "comment") || null });
      state.flash = id;
      after();
    } : null,
  });
}

/* ======================================================================
   10. HỒ SƠ + ĐỔI MẬT KHẨU
   ====================================================================== */
VIEWS.profile = async (v) => {
  const u = await must("GET", "/api/v1/auth/me");
  v.innerHTML = head(esc(u.full_name), `${esc(u.username)} · ${LABEL.role[u.role] || u.role}`) + `
    <div class="card narrow-page"><div class="card-b pad-top"><dl class="kv">
      <dt>Email</dt><dd>${esc(u.email)}</dd><dt>Điện thoại</dt><dd class="num">${esc(u.phone || "—")}</dd>
      <dt>Đăng nhập gần nhất</dt><dd class="num">${u.last_login_at ? new Date(u.last_login_at).toLocaleString("vi-VN") : "—"}</dd></dl>
      <div class="acts"><button class="btn ghost" id="pw">${ico("key", "sm")}Đổi mật khẩu</button></div>
    </div></div>`;
  $("#pw").addEventListener("click", () => modal({
    title: "Đổi mật khẩu",
    body: `<div class="field"><label>Mật khẩu hiện tại</label><input type="password" name="old" autocomplete="current-password" required></div>
      <div class="field"><label>Mật khẩu mới</label><input type="password" name="new" autocomplete="new-password" required>
        <div class="help">Ít nhất 8 ký tự, gồm chữ hoa, chữ thường và chữ số.</div></div>
      <div class="field"><label>Nhập lại mật khẩu mới</label><input type="password" name="new2" autocomplete="new-password" required></div>`,
    submit: "Đổi mật khẩu",
    onSubmit: async (form) => {
      if (val(form, "new") !== val(form, "new2")) throw new Error("Hai lần nhập mật khẩu mới không khớp.");
      await must("POST", "/api/v1/auth/change-password", { old_password: form.elements.old.value, new_password: form.elements.new.value });
      toast("Đã đổi mật khẩu.");
    },
  }));
};

/* ------------------------------ Tiện ích ------------------------------ */
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ------------------------------ Khởi động ----------------------------- */
/* Màn đăng nhập ẩn sẵn trong HTML để không nháy lên trong lúc thử khôi phục
   phiên bằng cookie. */
(async () => {
  ["qlpt.access", "qlpt.refresh", "qlpt.user"].forEach((k) => localStorage.removeItem(k));
  if (await doRefresh()) return enterApp();
  $("#login-wrap").classList.remove("hidden");
  const msg = sessionStorage.getItem("qlpt.msg");
  if (msg) { sessionStorage.removeItem("qlpt.msg"); $("#login-err").textContent = msg; }
})();
