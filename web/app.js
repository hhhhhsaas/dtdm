"use strict";
/* ==========================================================================
   QLPT — SPA tĩnh (không build, không CDN). Mọi API gọi qua đường dẫn tương
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
const ico = (name, cls = "") => `<svg class="ic ${cls}"><use href="#i-${name}"/></svg>`;
const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
const fmtMoney = (v) => (v === null || v === undefined || v === "") ? "—" : num(v).toLocaleString("vi-VN") + " đ";
const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso).slice(0, 10) : d.toLocaleDateString("vi-VN");
};
const fmtPeriod = (iso) => iso ? `Tháng ${Number(iso.slice(5, 7))}/${iso.slice(0, 4)}` : "—";
const fmtQty = (v) => v === null || v === undefined ? "—" : num(v).toLocaleString("vi-VN");
const initials = (name) => (name || "?").trim().split(/\s+/).slice(-2).map((w) => w[0]).join("").toUpperCase();

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
const pill = (map, v) => { const x = map[v]; return x ? `<span class="pill ${x[1]}">${x[0]}</span>` : `<span class="pill n">${esc(v || "—")}</span>`; };
const options = (map, sel) => Object.entries(map).map(([k, v]) =>
  `<option value="${k}" ${k === sel ? "selected" : ""}>${Array.isArray(v) ? v[0] : v}</option>`).join("");

const skeleton = (n = 5) => `<div class="card-b">${Array.from({ length: n }, (_, i) =>
  `<div class="skel" style="width:${90 - (i % 3) * 15}%"></div>`).join("")}</div>`;
const empty = (icon, title, sub = "") => `<div class="empty">${ico(icon)}<b>${title}</b>${sub}</div>`;

function toast(msg, type = "ok") {
  const el = document.createElement("div");
  el.className = "toast " + (type === "err" ? "err" : "");
  el.innerHTML = ico(type === "err" ? "alert" : "check", "sm") + `<span>${esc(msg)}</span>`;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "err" ? 6000 : 3500);
}

/* ------------------------------ API core ------------------------------ */
const apiErr = (res) => {
  const d = res.data || {};
  if (d.error && d.error.message) return d.error.message;
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
    <form class="modal ${wide ? "wide" : ""}" novalidate>
      <div class="modal-h"><h3>${title}</h3>
        <button type="button" class="icon-btn" data-close aria-label="Đóng">${ico("x")}</button></div>
      <div class="modal-b">${body}<div class="err" data-err></div></div>
      <div class="modal-f">
        <button type="button" class="btn ghost" data-close>${cancel}</button>
        ${submit ? `<button type="submit" class="btn ${danger ? "danger" : ""}">${submit}</button>` : ""}
      </div>
    </form>`;
  const close = () => bg.remove();
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
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
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
$$(".demo .chip").forEach((b) => b.addEventListener("click", () => {
  $("#u").value = b.dataset.user;
  $("#p").value = b.dataset.user === "khach01" ? "Tenant@12345" : "";
  $("#p").focus();
}));

/* ---------------------------- Điều hướng ------------------------------ */
const NAV = {
  manager: [
    ["Vận hành", [["home", "dash", "Việc cần làm"], ["meters", "gauge", "Chỉ số điện nước"], ["invoices", "receipt", "Hóa đơn"], ["incidents", "wrench", "Sự cố"]]],
    ["Quản lý", [["rooms", "door", "Phòng"], ["contracts", "file", "Hợp đồng"], ["tenants", "users", "Người thuê"]]],
    ["Tài khoản", [["profile", "user", "Hồ sơ"]]],
  ],
  tenant: [
    ["", [["my-invoices", "receipt", "Hóa đơn của tôi"], ["my-incidents", "wrench", "Báo sự cố"], ["profile", "user", "Hồ sơ"]]],
  ],
};
const isTenant = () => state.user && state.user.role === "TENANT";
const navDef = () => NAV[isTenant() ? "tenant" : "manager"];
const allowedTabs = () => navDef().flatMap(([, list]) => list.map((x) => x[0]));

function enterApp() {
  $("#login-wrap").classList.add("hidden");
  $("#app").classList.remove("hidden");
  const fromHash = location.hash.slice(1);
  state.tab = allowedTabs().includes(fromHash) ? fromHash : allowedTabs()[0];
  renderNav();
  go(state.tab);
}

function renderNav() {
  $("#nav").innerHTML = navDef().map(([group, list]) =>
    (group ? `<div class="nav-group">${group}</div>` : "") +
    list.map(([id, icon, label]) =>
      `<button class="nav-item" data-tab="${id}">${ico(icon)}<span>${label}</span><span class="badge hidden" data-badge="${id}"></span></button>`).join("")
  ).join("");
  $$("#nav .nav-item").forEach((b) => b.addEventListener("click", () => { go(b.dataset.tab); $("#side").classList.remove("open"); }));
  const u = state.user;
  $("#me").innerHTML = `<div class="avatar">${esc(initials(u.full_name))}</div>
    <div class="who"><b>${esc(u.full_name)}</b><span>${LABEL.role[u.role] || u.role}</span></div>
    <button class="icon-btn" id="logout" title="Đăng xuất">${ico("logout")}</button>`;
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

const VIEWS = {};
function go(tab) {
  if (!allowedTabs().includes(tab)) tab = allowedTabs()[0];
  state.tab = tab;
  history.replaceState(null, "", "#" + tab);
  $$("#nav .nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  const v = $("#view");
  v.innerHTML = `<div class="card">${skeleton(6)}</div>`;
  window.scrollTo(0, 0);
  VIEWS[tab](v).catch((err) => {
    v.innerHTML = `<div class="card">${empty("alert", "Không tải được dữ liệu", `<div>${esc(err.message)}</div>`)}</div>`;
  });
}
$("#menu-btn").addEventListener("click", () => $("#side").classList.toggle("open"));

const head = (title, lead, actions = "") =>
  `<div class="page-head"><div><h2>${title}</h2>${lead ? `<div class="lead">${lead}</div>` : ""}</div>
   ${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;

/* ======================================================================
   1. VIỆC CẦN LÀM (chủ trọ / quản lý)
   ====================================================================== */
VIEWS.home = async (v) => {
  const period = curPeriod();
  const [dash, rooms, inv, overdue, expiring, incidents, readings, occupied, periodInv] = await Promise.all([
    api("GET", "/api/v1/reports/dashboard"),
    api("GET", "/api/v1/rooms/stats"),
    api("GET", "/api/v1/invoices/stats"),
    api("GET", "/api/v1/invoices/overdue"),
    api("GET", "/api/v1/contracts/expiring?days=30"),
    api("GET", "/api/v1/incidents?" + qs({ is_open: true, page_size: 100 })),
    api("GET", "/api/v1/meter-readings?" + qs({ period, utility_type: "ELECTRIC", page_size: 100 })),
    api("GET", "/api/v1/rooms?" + qs({ status: "OCCUPIED", page_size: 100 })),
    api("GET", "/api/v1/invoices?" + qs({ period, page_size: 1 })),
  ]);
  /* ⭐ API lỗi KHÔNG được coi là "danh sách rỗng": nếu API hóa đơn quá hạn
     chết mà vẫn hiện "Mọi việc đã xong" thì chủ trọ yên tâm sai. Ghi nhận
     nguồn nào lỗi, hiện cảnh báo, và không kết luận gì từ nguồn đó. */
  const failed = [[dash, "báo cáo doanh thu"], [rooms, "thống kê phòng"], [inv, "thống kê hóa đơn"],
    [overdue, "hóa đơn quá hạn"], [expiring, "hợp đồng sắp hết hạn"], [incidents, "sự cố"],
    [readings, "chỉ số điện nước"], [occupied, "danh sách phòng"], [periodInv, "hóa đơn kỳ này"]]
    .filter(([res]) => !res.ok).map(([, name]) => name);
  const NA = "—";
  const kpi = (dash.data && dash.data.kpi) || {};
  const r = rooms.ok ? rooms.data || {} : {}, s = inv.ok ? inv.data || {} : {};
  const occRate = r.total ? Math.round((r.occupied / r.total) * 100) : null;
  const od = items(overdue), ex = items(expiring), inc = items(incidents);
  const done = new Set(items(readings).map((x) => x.room_id));
  const missing = items(occupied).filter((x) => !done.has(x.id));
  const issued = periodInv.ok && periodInv.data && periodInv.data.meta ? periodInv.data.meta.total : 0;
  if (incidents.ok) setBadge("incidents", inc.length);

  const hour = new Date().getHours();
  const hi = hour < 11 ? "Chào buổi sáng" : hour < 18 ? "Chào buổi chiều" : "Chào buổi tối";
  const todos = [];
  const metersKnown = readings.ok && occupied.ok;
  if (metersKnown && missing.length) todos.push(["a", "gauge", `${missing.length} phòng chưa nhập chỉ số ${fmtPeriod(period).toLowerCase()}`,
    missing.slice(0, 6).map((x) => x.room_number).join(", ") + (missing.length > 6 ? "…" : ""), "meters", "Nhập chỉ số"]);
  else if (metersKnown && periodInv.ok && !issued && items(occupied).length) todos.push(["b", "receipt", `Chỉ số ${fmtPeriod(period).toLowerCase()} đã đủ, chưa phát hành hóa đơn`,
    "Phát hành một lần cho tất cả hợp đồng đang hiệu lực", "invoices", "Phát hành"]);
  if (od.length) {
    const sum = od.reduce((a, x) => a + num(x.total_amount) - num(x.paid_amount), 0);
    todos.push(["r", "alert", `${od.length} hóa đơn quá hạn · ${fmtMoney(sum)}`,
      od.slice(0, 3).map((x) => `${x.tenant_name} (${x.room_number || "—"})`).join(", "), "invoices:OVERDUE", "Xem"]);
  }
  if (inc.length) todos.push(["r", "wrench", `${inc.length} sự cố chưa xử lý xong`,
    inc.slice(0, 3).map((x) => x.title).join(" · "), "incidents", "Xử lý"]);
  if (ex.length) todos.push(["a", "cal", `${ex.length} hợp đồng hết hạn trong 30 ngày tới`,
    ex.slice(0, 3).map((x) => `${x.primary_tenant_name} · còn ${x.days_remaining} ngày`).join(", "), "contracts:expiring", "Xem"]);

  const pts = ((dash.data && dash.data.revenue_30d) || []).slice(-14);
  const max = Math.max(...pts.map((p) => num(p.collected)), 1);
  const total30 = pts.reduce((a, p) => a + num(p.collected), 0);

  v.innerHTML = head(`${hi}, ${esc(state.user.full_name.split(" ").pop())}`,
      `${new Date().toLocaleDateString("vi-VN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}`) + `
    ${failed.length ? `<div class="note warn">${ico("alert", "sm")}<div><b>Chưa tải được: ${esc(failed.join(", "))}.</b>
      Các số liệu liên quan đang hiện “—” và danh sách việc cần làm có thể chưa đầy đủ. Tải lại trang sau ít phút.</div></div>` : ""}
    <div class="grid kpis">
      <div class="card kpi"><div class="k">${ico("cash", "sm")}Doanh thu tháng này</div>
        <div class="v">${dash.ok ? fmtMoney(kpi.revenue_month) : NA}</div><div class="s">${inv.ok ? `Thu được ${s.collection_rate ?? 0}% tổng đã lập` : NA}</div></div>
      <div class="card kpi"><div class="k">${ico("door", "sm")}Tỷ lệ lấp đầy</div>
        <div class="v">${occRate ?? NA}${occRate !== null ? "%" : ""}</div><div class="s">${rooms.ok ? `${r.occupied ?? 0}/${r.total ?? 0} phòng đang có người` : NA}</div></div>
      <div class="card kpi"><div class="k">${ico("receipt", "sm")}Còn phải thu</div>
        <div class="v" style="color:${num(s.total_outstanding) > 0 ? "var(--amber)" : "inherit"}">${fmtMoney(s.total_outstanding)}</div>
        <div class="s">${inv.ok ? `${s.pending ?? 0} chờ thanh toán · ${s.overdue ?? 0} quá hạn` : NA}</div></div>
      <div class="card kpi"><div class="k">${ico("wrench", "sm")}Sự cố đang mở</div>
        <div class="v" style="color:${inc.length ? "var(--red)" : "inherit"}">${incidents.ok ? inc.length : NA}</div>
        <div class="s">${incidents.ok ? `${inc.filter((x) => x.priority === "URGENT").length} khẩn cấp` : NA}</div></div>
    </div>
    <div class="grid two">
      <div class="card">
        <div class="card-h">${ico("check")}<h3>Việc cần làm</h3><span class="muted">${todos.length ? todos.length + " việc" : ""}</span></div>
        ${todos.length ? todos.map(([c, i, t, sub, target, btn]) => `
          <div class="todo"><div class="dot ${c}">${ico(i)}</div>
            <div class="txt"><b>${esc(t)}</b><span>${esc(sub)}</span></div>
            <button class="btn ghost sm" data-go="${target}">${btn} ${ico("chev", "sm")}</button></div>`).join("")
          : failed.length ? empty("alert", "Chưa kiểm tra được đầy đủ", "Một số dữ liệu chưa tải được nên chưa thể kết luận.")
          : empty("check", "Mọi việc đã xong", "Không có hóa đơn quá hạn, sự cố hay hợp đồng cần xử lý.")}
      </div>
      <div class="card">
        <div class="card-h">${ico("cash")}<h3>Tiền thu được</h3><span class="muted">${pts.length ? "14 ngày gần nhất" : ""}</span></div>
        <div class="card-b">${pts.length ? `
          <div style="font-size:22px;font-weight:700">${fmtMoney(total30)}</div>
          <div class="chart">${pts.map((p) => `<div class="col" title="${fmtDate(p.stat_date)}: ${fmtMoney(p.collected)}">
              <div class="bar" style="height:${Math.max(2, (num(p.collected) / max) * 100)}%"></div>
              <div class="lab">${new Date(p.stat_date).getDate()}</div></div>`).join("")}</div>
          <div class="legend"><span>${fmtDate(pts[0].stat_date)}</span><span>${fmtDate(pts[pts.length - 1].stat_date)}</span></div>`
          : empty("cash", "Chưa có khoản thu nào", "Số liệu sẽ hiện khi có thanh toán đầu tiên.")}
        </div>
      </div>
    </div>`;
  $$("[data-go]", v).forEach((b) => b.addEventListener("click", () => {
    const [tab, arg] = b.dataset.go.split(":");
    state.arg = arg || null;
    go(tab);
  }));
};

/* ======================================================================
   2. PHÒNG
   ====================================================================== */
VIEWS.rooms = async (v) => {
  const statsRes = await api("GET", "/api/v1/rooms/stats");
  const st = statsRes.data || {};
  v.innerHTML = head("Phòng", `${st.total ?? 0} phòng · ${st.occupied ?? 0} đang thuê · ${st.available ?? 0} còn trống`) + `
    <div class="card">
      <div class="toolbar">
        <div class="search">${ico("search", "sm")}<input id="q" placeholder="Tìm số phòng"></div>
        <div class="seg" id="seg">
          <button data-s="" class="on">Tất cả</button><button data-s="OCCUPIED">Đang thuê</button>
          <button data-s="AVAILABLE">Còn trống</button><button data-s="MAINTENANCE">Bảo trì</button></div>
      </div>
      <div class="tbl-wrap" id="tbl">${skeleton()}</div>
    </div>`;
  let status = "";
  const load = async () => {
    const res = await api("GET", "/api/v1/rooms?" + qs({ page_size: 100, search: $("#q").value.trim(), status }));
    if (!res.ok) throw new Error(apiErr(res));
    const list = items(res);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Phòng</th><th>Tòa · tầng</th><th>Diện tích</th><th class="right">Giá thuê</th><th>Trạng thái</th></tr>
      ${list.map((r) => `<tr class="click" data-id="${r.id}">
        <td class="strong">${esc(r.room_number)}</td>
        <td class="muted">${esc(r.building_name || "—")} · Tầng ${r.floor ?? "—"}</td>
        <td>${r.area_m2 ? num(r.area_m2) + " m²" : "—"}</td>
        <td class="right money">${fmtMoney(r.base_price)}</td>
        <td>${pill(LABEL.room, r.status)}</td></tr>`).join("")}</table>`
      : empty("door", "Không tìm thấy phòng nào", "Thử bỏ bộ lọc hoặc đổi từ khóa.");
    $$("tr[data-id]", $("#tbl")).forEach((tr) => tr.addEventListener("click", () =>
      roomDetail(list.find((x) => x.id === tr.dataset.id))));
  };
  $("#q").addEventListener("input", debounce(load, 250));
  $$("#seg button").forEach((b) => b.addEventListener("click", () => {
    $$("#seg button").forEach((x) => x.classList.toggle("on", x === b));
    status = b.dataset.s; load();
  }));
  await load();
};

async function roomDetail(r) {
  const c = items(await api("GET", "/api/v1/contracts?" + qs({ room_id: r.id, active_only: true, page_size: 1 })))[0];
  modal({
    title: `Phòng ${esc(r.room_number)}`,
    body: `<dl class="kv">
      <dt>Trạng thái</dt><dd>${pill(LABEL.room, r.status)}</dd>
      <dt>Vị trí</dt><dd>${esc(r.building_name || "—")} · Tầng ${r.floor ?? "—"}</dd>
      <dt>Diện tích</dt><dd>${r.area_m2 ? num(r.area_m2) + " m²" : "—"}</dd>
      <dt>Giá thuê</dt><dd class="money">${fmtMoney(r.base_price)}</dd>
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
  v.innerHTML = head("Chỉ số điện nước", "Ghi số công tơ cuối kỳ cho các phòng đang có người thuê",
      `<input type="month" id="per" value="${period.slice(0, 7)}" style="width:auto">
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
      $("#msg").innerHTML = `<div class="note ok">${ico("check", "sm")}<div>Đã nhập đủ chỉ số ${fmtPeriod(period).toLowerCase()} cho ${rows.length} phòng.
        <a href="#" id="to-inv" style="color:inherit;font-weight:600">Phát hành hóa đơn →</a></div></div>`;
      $("#to-inv").addEventListener("click", (e) => { e.preventDefault(); state.arg = "issue"; go("invoices"); });
    }
    const cell = (r, t, d) => {
      const prevV = d.prev ? num(d.prev.reading_value) : null;
      if (d.cur) return `<td class="right money">${fmtQty(d.cur.reading_value)}<div class="use g">dùng ${fmtQty(d.cur.consumption)} ${t === "ELECTRIC" ? "kWh" : "m³"}</div></td>`;
      return `<td class="right"><input class="meter-in" type="number" min="0" step="0.01" inputmode="decimal"
                data-room="${r.id}" data-type="${t}" data-prev="${prevV ?? ""}" placeholder="${prevV ?? "Số mới"}">
              <div class="use" data-use></div></td>`;
    };
    $("#tbl").innerHTML = rows.length ? `<table>
      <tr><th>Phòng</th><th class="right">${ico("zap", "sm")} Điện kỳ trước</th><th class="right">Điện kỳ này</th>
          <th class="right">${ico("drop", "sm")} Nước kỳ trước</th><th class="right">Nước kỳ này</th><th>Tình trạng</th></tr>
      ${rows.map(({ room, e, w }) => `<tr>
        <td class="strong">${esc(room.room_number)}</td>
        <td class="right muted money">${e.prev ? fmtQty(e.prev.reading_value) : "—"}</td>${cell(room, "ELECTRIC", e)}
        <td class="right muted money">${w.prev ? fmtQty(w.prev.reading_value) : "—"}</td>${cell(room, "WATER", w)}
        <td>${e.cur && w.cur ? '<span class="pill g">Đã nhập</span>' : '<span class="pill a">Chưa nhập</span>'}</td></tr>`).join("")}</table>`
      : empty("door", "Chưa có phòng nào đang cho thuê");
    $$(".meter-in", $("#tbl")).forEach((inp) => inp.addEventListener("input", () => {
      const prevV = inp.dataset.prev === "" ? null : num(inp.dataset.prev);
      const out = inp.nextElementSibling;
      if (inp.value === "") { inp.classList.remove("bad"); out.textContent = ""; return; }
      const used = num(inp.value) - (prevV ?? 0);
      const bad = prevV !== null && used < 0;
      inp.classList.toggle("bad", bad);
      out.className = "use " + (bad ? "" : "g");
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
        $("#msg").insertAdjacentHTML("afterbegin", `<div class="note warn">${ico("alert", "sm")}<div>
          Đã lưu ${res.inserted} chỉ số, ${res.skipped} chỉ số bị từ chối:<br>${res.errors.map((e) => esc(e.reason)).join("<br>")}</div></div>`);
      } else toast(`Đã lưu ${res.inserted} chỉ số.`);
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
  v.innerHTML = head("Hóa đơn", "Theo dõi hóa đơn từng kỳ và ghi nhận tiền người thuê đã trả",
      `<button class="btn" id="issue">${ico("send", "sm")}Phát hành hóa đơn</button>`) + `
    <div class="grid kpis" id="sum"></div>
    <div class="card">
      <div class="toolbar">
        <input type="month" id="per" style="width:auto" title="Lọc theo kỳ">
        <div class="seg" id="seg">
          <button data-s="">Tất cả</button><button data-s="PENDING">Chờ thanh toán</button>
          <button data-s="OVERDUE">Quá hạn</button><button data-s="PAID">Đã thanh toán</button></div>
      </div>
      <div class="tbl-wrap" id="tbl">${skeleton()}</div>
    </div>`;
  const markSeg = () => $$("#seg button").forEach((x) => x.classList.toggle("on", x.dataset.s === status));
  markSeg();

  const load = async () => {
    const [res, stats] = await Promise.all([
      api("GET", "/api/v1/invoices?" + qs({ page_size: 100, status, period })),
      api("GET", "/api/v1/invoices/stats?" + qs({ period })),
    ]);
    if (!res.ok) throw new Error(apiErr(res));
    const s = stats.data || {};
    $("#sum").innerHTML = `
      <div class="card kpi"><div class="k">Tổng đã lập</div><div class="v">${fmtMoney(s.total_billed)}</div><div class="s">${s.total_invoices ?? 0} hóa đơn</div></div>
      <div class="card kpi"><div class="k">Đã thu</div><div class="v" style="color:var(--acc-txt)">${fmtMoney(s.total_collected)}</div><div class="s">${s.paid ?? 0} hóa đơn đã trả đủ</div></div>
      <div class="card kpi"><div class="k">Còn phải thu</div><div class="v" style="color:var(--amber)">${fmtMoney(s.total_outstanding)}</div><div class="s">${s.overdue ?? 0} quá hạn</div></div>`;
    const list = items(res);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Kỳ</th><th>Phòng</th><th>Người thuê</th><th class="right">Tổng tiền</th><th class="right">Còn nợ</th><th>Hạn trả</th><th>Trạng thái</th></tr>
      ${list.map((i) => `<tr class="click" data-id="${i.id}">
        <td class="nowrap">${fmtPeriod(i.period)}<div class="muted" style="font-size:12px">${esc(i.invoice_no)}</div></td>
        <td class="strong">${esc(i.room_number || "—")}</td><td>${esc(i.tenant_name)}</td>
        <td class="right money">${fmtMoney(i.total_amount)}</td>
        <td class="right money">${num(i.total_amount) - num(i.paid_amount) > 0 ? fmtMoney(num(i.total_amount) - num(i.paid_amount)) : '<span class="muted">0 đ</span>'}</td>
        <td class="nowrap">${fmtDate(i.due_date)}${i.days_overdue ? `<div style="color:var(--red);font-size:12px">trễ ${i.days_overdue} ngày</div>` : ""}</td>
        <td>${pill(LABEL.invoice, i.status)}</td></tr>`).join("")}</table>`
      : empty("receipt", "Chưa có hóa đơn nào", "Nhập chỉ số rồi bấm “Phát hành hóa đơn” để tạo hóa đơn cho kỳ mới.");
    $$("tr[data-id]", $("#tbl")).forEach((tr) => tr.addEventListener("click", () => invoiceDetail(tr.dataset.id, load)));
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
      <div class="note info">${ico("alert", "sm")}<div>Hệ thống tạo hóa đơn cho mọi hợp đồng đang hiệu lực: tiền phòng, điện nước theo bậc thang và phí dịch vụ.
        Hợp đồng nào đã có hóa đơn kỳ này sẽ được bỏ qua, bấm lại nhiều lần cũng không bị trùng.</div></div>
      <div id="job" class="hidden"><div class="progress"><i style="width:0"></i></div><div class="muted" id="job-t" style="margin-top:8px"></div></div>`,
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
  modal({
    wide: true,
    title: `Hóa đơn ${esc(inv.invoice_no)} ${pill(LABEL.invoice, inv.status)}`,
    body: `
      <dl class="kv"><dt>Người thuê</dt><dd>${esc(inv.tenant_name)} · phòng ${esc(inv.room_number || "—")}</dd>
        <dt>Kỳ</dt><dd>${fmtPeriod(inv.period)}</dd><dt>Hạn thanh toán</dt><dd>${fmtDate(inv.due_date)}</dd></dl>
      ${invoiceLines(inv)}
      ${pays.length ? `<div class="section-t">Lịch sử thanh toán</div><table class="lines">${pays.map((p) => `<tr>
          <td>${fmtDate(p.received_at)}</td><td class="muted">${LABEL.method[p.method] || esc(p.method)}${p.receipt_no ? " · " + esc(p.receipt_no) : ""}</td>
          <td class="right money">${fmtMoney(p.amount)}</td></tr>`).join("")}</table>` : ""}
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
        $("[data-confirm]", form).innerHTML = `<div class="note warn">${ico("alert", "sm")}<div>
          Xác nhận đã nhận <b class="money">${fmtMoney(amount)}</b> bằng <b>${esc(LABEL.method[val(form, "method")])}</b>
          từ ${esc(inv.tenant_name)} (phòng ${esc(inv.room_number || "—")})?<br>
          Sau khi ghi nhận sẽ không xóa được trên phần mềm.</div></div>`;
        $("button[type=submit]", form).textContent = "Xác nhận đã nhận tiền";
        return false;
      }
      await must("POST", `/api/v1/invoices/${id}/payments`, {
        amount, method: val(form, "method"), receipt_no: val(form, "receipt_no") || null, note: val(form, "note") || null,
      });
      toast(`Đã ghi nhận ${fmtMoney(amount)}. Trang Việc cần làm sẽ cập nhật sau vài giây.`);
      after && after();
    } : null,
  });
}

function invoiceLines(inv) {
  const lines = (inv.details && inv.details.length) ? inv.details.map((d) => [d.description,
      d.quantity !== null && d.unit_price !== null ? `${fmtQty(d.quantity)} × ${fmtMoney(d.unit_price)}` : "", d.amount])
    : [["Tiền phòng", "", inv.rent_amount], ["Tiền điện", "", inv.electric_amount], ["Tiền nước", "", inv.water_amount],
       ["Dịch vụ", "", inv.service_amount]].filter((x) => num(x[2]));
  if (num(inv.late_fee_amount)) lines.push(["Phí trễ hạn", "", inv.late_fee_amount]);
  if (num(inv.discount_amount)) lines.push(["Giảm trừ", "", -num(inv.discount_amount)]);
  if (num(inv.deposit_deducted)) lines.push(["Trừ vào tiền cọc", "", -num(inv.deposit_deducted)]);
  return `<div class="section-t">Chi tiết</div><table class="lines">
    ${lines.map(([d, q, a]) => `<tr><td>${esc(d)}</td><td class="muted right">${q}</td><td class="right money">${fmtMoney(a)}</td></tr>`).join("")}
    <tr class="total-row"><td>Tổng cộng</td><td></td><td class="right money">${fmtMoney(inv.total_amount)}</td></tr>
    ${num(inv.paid_amount) ? `<tr><td class="muted">Đã trả</td><td></td><td class="right money muted">${fmtMoney(inv.paid_amount)}</td></tr>
      <tr><td class="strong">Còn lại</td><td></td><td class="right money strong">${fmtMoney(num(inv.total_amount) - num(inv.paid_amount))}</td></tr>` : ""}
  </table>`;
}

/* ======================================================================
   5. HỢP ĐỒNG
   ====================================================================== */
VIEWS.contracts = async (v) => {
  const pid = await propertyId();
  const arg = state.arg; state.arg = null;
  let mode = arg === "expiring" ? "expiring" : "ACTIVE";
  v.innerHTML = head("Hợp đồng", "Soạn, kích hoạt và theo dõi thời hạn hợp đồng thuê",
      `<button class="btn" id="new">${ico("plus", "sm")}Tạo hợp đồng</button>`) + `
    <div class="card">
      <div class="toolbar"><div class="seg" id="seg">
        <button data-m="ACTIVE">Đang hiệu lực</button><button data-m="expiring">Sắp hết hạn</button>
        <button data-m="draft">Đang soạn</button><button data-m="">Tất cả</button></div></div>
      <div class="tbl-wrap" id="tbl">${skeleton()}</div>
    </div>`;
  const load = async () => {
    $$("#seg button").forEach((x) => x.classList.toggle("on", x.dataset.m === mode));
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
        <td class="muted">${esc(c.contract_no)}</td>
        <td class="strong">${esc((rooms[c.room_id] || {}).room_number || c.room_number || "—")}</td>
        <td>${esc(c.primary_tenant_name)}<div class="muted" style="font-size:12px">${esc(c.primary_tenant_phone)}</div></td>
        <td class="nowrap">${fmtDate(c.start_date)} → ${fmtDate(c.end_date)}
          ${c.days_remaining !== null && c.days_remaining !== undefined && c.days_remaining <= 60
            ? `<div style="color:var(--amber);font-size:12px">còn ${c.days_remaining} ngày</div>` : ""}</td>
        <td class="right money">${fmtMoney(c.monthly_price)}</td><td>${pill(LABEL.contract, c.status)}</td></tr>`).join("")}</table>`
      : empty("file", mode === "expiring" ? "Không có hợp đồng nào sắp hết hạn" : "Không có hợp đồng nào");
    $$("tr[data-id]", $("#tbl")).forEach((tr) => tr.addEventListener("click", () => contractDetail(tr.dataset.id, load)));
  };
  $$("#seg button").forEach((b) => b.addEventListener("click", () => { mode = b.dataset.m; load(); }));
  $("#new").addEventListener("click", () => newContract(pid, load));
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
      const c = await must("POST", "/api/v1/contracts", {
        property_id: pid, room_id: val(form, "room"), primary_tenant_id: t.id,
        primary_tenant_name: t.full_name, primary_tenant_phone: t.phone, primary_tenant_email: t.email || null,
        start_date: val(form, "start"), end_date: val(form, "end"),
        monthly_price: val(form, "price"), deposit_amount: val(form, "deposit") || "0", room_id_confirmed: true,
      });
      toast(`Đã tạo hợp đồng ${c.contract_no}.`);
      state.rooms = null;
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
  const run = async (fn, ok) => { try { await fn(); toast(ok); state.rooms = null; m.close(); after(); } catch (e) { toast(e.message, "err"); } };
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
        <dt>Phòng</dt><dd class="strong">${esc((rooms[c.room_id] || {}).room_number || "—")}</dd>
        <dt>Người thuê</dt><dd>${esc(c.primary_tenant_name)} · ${esc(c.primary_tenant_phone)}</dd>
        <dt>Thời hạn</dt><dd>${fmtDate(c.start_date)} → ${fmtDate(c.end_date)}</dd>
        <dt>Giá thuê</dt><dd class="money">${fmtMoney(c.monthly_price)} / tháng</dd>
        <dt>Tiền cọc</dt><dd class="money">${fmtMoney(c.deposit_amount)} ${c.deposit_paid_at ? `<span class="pill g">đã thu ${fmtDate(c.deposit_paid_at)}</span>` : num(c.deposit_amount) ? '<span class="pill a">chưa thu</span>' : ""}</dd>
        ${num(c.deposit_deducted) ? `<dt>Cọc còn lại</dt><dd class="money">${fmtMoney(c.remaining_deposit)}</dd>` : ""}
        ${c.terminated_reason ? `<dt>Lý do kết thúc</dt><dd>${esc(c.terminated_reason)}</dd>` : ""}
      </dl>
      ${acts.length ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:18px">${acts.map((a, i) =>
        `<button type="button" class="btn ${a.cls}" data-act="${i}">${a.label}</button>`).join("")}</div>` : ""}`,
  });
  $$("[data-act]", m.el).forEach((b) => b.addEventListener("click", () => acts[b.dataset.act].fn()));
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
      toast("Đã ghi nhận tiền cọc.");
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
    <div class="card">
      <div class="toolbar"><div class="search">${ico("search", "sm")}<input id="q" placeholder="Tìm theo tên, số điện thoại, email"></div></div>
      <div class="tbl-wrap" id="tbl">${skeleton()}</div>
    </div>`;
  const load = async () => {
    const [res, rooms] = await Promise.all([api("GET", "/api/v1/tenants?" + qs({ page_size: 100, search: $("#q").value.trim() })), roomMap()]);
    if (!res.ok) throw new Error(apiErr(res));
    const list = items(res);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Họ tên</th><th>Điện thoại</th><th>CCCD</th><th>Phòng</th><th>Đánh giá</th></tr>
      ${list.map((t) => `<tr class="click" data-id="${t.id}">
        <td><div style="display:flex;gap:10px;align-items:center"><div class="avatar" style="width:30px;height:30px;font-size:11.5px">${esc(initials(t.full_name))}</div>
          <div><div class="strong">${esc(t.full_name)}</div><div class="muted" style="font-size:12px">${esc(t.occupation || t.email || "")}</div></div></div></td>
        <td class="nowrap">${esc(t.phone)}</td><td class="muted"><code>${esc(t.id_card_masked || "—")}</code></td>
        <td class="strong">${t.current_room_id ? esc((rooms[t.current_room_id] || {}).room_number || "—") : '<span class="muted">—</span>'}</td>
        <td>${t.is_active ? pill(LABEL.risk, t.risk_level) : '<span class="pill n">Đã rời đi</span>'}</td></tr>`).join("")}</table>`
      : empty("users", "Không tìm thấy người thuê nào");
    $$("tr[data-id]", $("#tbl")).forEach((tr) => tr.addEventListener("click", () =>
      tenantDetail(list.find((x) => x.id === tr.dataset.id), rooms)));
  };
  $("#q").addEventListener("input", debounce(load, 250));
  $("#new").addEventListener("click", () => newTenant(pid, load));
  await load();
};

function tenantDetail(t, rooms) {
  modal({
    title: esc(t.full_name),
    body: `<dl class="kv">
      <dt>Điện thoại</dt><dd>${esc(t.phone)}</dd><dt>Email</dt><dd>${esc(t.email || "—")}</dd>
      <dt>Ngày sinh</dt><dd>${fmtDate(t.date_of_birth)}</dd><dt>Quê quán</dt><dd>${esc(t.address || "—")}</dd>
      <dt>Nghề nghiệp</dt><dd>${esc(t.occupation || "—")}</dd>
      <dt>CCCD</dt><dd><code>${esc(t.id_card_masked || "—")}</code></dd>
      <dt>Phòng hiện tại</dt><dd>${t.current_room_id ? esc((rooms[t.current_room_id] || {}).room_number || "—") : "—"}</dd>
      <dt>Liên hệ khẩn cấp</dt><dd>${t.emergency_contact_name ? `${esc(t.emergency_contact_name)} · ${esc(t.emergency_contact_phone || "")}` : "—"}</dd>
      <dt>Đánh giá</dt><dd>${pill(LABEL.risk, t.risk_level)} ${t.risk_note ? `<span class="muted">${esc(t.risk_note)}</span>` : ""}</dd></dl>`,
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
      const t = await must("POST", "/api/v1/tenants", {
        property_id: pid, full_name: val(form, "full_name"), phone: val(form, "phone"),
        id_card_number: idc || null, date_of_birth: val(form, "dob") || null, gender: val(form, "gender") || null,
        email: val(form, "email") || null, occupation: val(form, "occupation") || null, address: val(form, "address") || null,
        emergency_contact_name: val(form, "ec_name") || null, emergency_contact_phone: val(form, "ec_phone") || null,
      });
      toast(`Đã thêm ${t.full_name}.`);
      after();
    },
  });
}

/* ======================================================================
   7. SỰ CỐ (quản lý)
   ====================================================================== */
VIEWS.incidents = async (v) => {
  let open = true;
  v.innerHTML = head("Sự cố", "Phiếu báo hỏng từ người thuê và quản lý") + `
    <div class="card">
      <div class="toolbar"><div class="seg" id="seg"><button data-o="1" class="on">Chưa xử lý xong</button><button data-o="">Tất cả</button></div></div>
      <div class="tbl-wrap" id="tbl">${skeleton()}</div>
    </div>`;
  const load = async () => {
    const res = await api("GET", "/api/v1/incidents?" + qs({ page_size: 100, is_open: open || "" }));
    if (!res.ok) throw new Error(apiErr(res));
    const list = items(res);
    if (open) setBadge("incidents", list.length);
    $("#tbl").innerHTML = list.length ? `<table>
      <tr><th>Sự cố</th><th>Phòng</th><th>Người báo</th><th>Mức độ</th><th>Báo lúc</th><th>Trạng thái</th></tr>
      ${list.map((i) => `<tr class="click" data-id="${i.id}">
        <td><div class="strong">${esc(i.title)}</div><div class="muted" style="font-size:12px">${esc(i.ticket_no)} · ${LABEL.category[i.category] || esc(i.category)}</div></td>
        <td class="strong">${esc(i.room_number || "—")}</td><td>${esc(i.reported_by_name)}</td>
        <td>${pill(LABEL.priority, i.priority)}</td><td class="nowrap">${fmtDate(i.created_at)}</td>
        <td>${pill(LABEL.incident, i.status)}</td></tr>`).join("")}</table>`
      : empty("check", open ? "Không có sự cố nào đang chờ" : "Chưa có phiếu sự cố nào");
    $$("tr[data-id]", $("#tbl")).forEach((tr) => tr.addEventListener("click", () => incidentDetail(tr.dataset.id, load)));
  };
  $$("#seg button").forEach((b) => b.addEventListener("click", () => {
    $$("#seg button").forEach((x) => x.classList.toggle("on", x === b)); open = !!b.dataset.o; load();
  }));
  await load();
};

async function incidentDetail(id, after) {
  const i = await must("GET", "/api/v1/incidents/" + id);
  const call = async (path, body, ok) => {
    try { await must("POST", `/api/v1/incidents/${id}/${path}`, body); toast(ok); m.close(); after(); }
    catch (e) { toast(e.message, "err"); }
  };
  const isOpen = !["RESOLVED", "CLOSED", "CANCELLED"].includes(i.status);
  const m = modal({
    wide: true,
    title: `${esc(i.title)} ${pill(LABEL.incident, i.status)}`,
    body: `<dl class="kv">
        <dt>Mã phiếu</dt><dd>${esc(i.ticket_no)}</dd>
        <dt>Phòng</dt><dd class="strong">${esc(i.room_number || "Khu vực chung")}</dd>
        <dt>Loại · mức độ</dt><dd>${LABEL.category[i.category] || esc(i.category)} · ${pill(LABEL.priority, i.priority)}</dd>
        <dt>Người báo</dt><dd>${esc(i.reported_by_name)}${i.reported_by_phone ? " · " + esc(i.reported_by_phone) : ""}</dd>
        <dt>Báo lúc</dt><dd>${new Date(i.created_at).toLocaleString("vi-VN")}</dd>
        ${i.description ? `<dt>Mô tả</dt><dd style="white-space:pre-wrap">${esc(i.description)}</dd>` : ""}
        ${i.assigned_to_name ? `<dt>Người xử lý</dt><dd>${esc(i.assigned_to_name)}</dd>` : ""}
        ${i.resolution ? `<dt>Kết quả</dt><dd style="white-space:pre-wrap">${esc(i.resolution)}</dd>` : ""}
        ${i.cost ? `<dt>Chi phí</dt><dd class="money">${fmtMoney(i.cost)}</dd>` : ""}
        ${i.rating ? `<dt>Người thuê đánh giá</dt><dd>${"★".repeat(i.rating)}${"☆".repeat(5 - i.rating)} ${esc(i.rating_comment || "")}</dd>` : ""}
      </dl>
      ${i.status === "IN_PROGRESS" ? `<div class="section-t">Báo đã xử lý xong</div>
        <div class="field"><label>Đã làm gì</label><textarea name="resolution" placeholder="VD: Thay vòi nước mới, kiểm tra không rò rỉ"></textarea></div>
        <div class="field" style="max-width:240px"><label>Chi phí (nếu có)</label><input name="cost" type="number" step="1000" min="0"></div>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px">
        ${["OPEN", "ASSIGNED"].includes(i.status) ? `<button type="button" class="btn" data-a="start">Bắt đầu xử lý</button>` : ""}
        ${i.status === "IN_PROGRESS" ? `<button type="button" class="btn" data-a="resolve">Đã xử lý xong</button>` : ""}
        ${i.status === "RESOLVED" ? `<button type="button" class="btn" data-a="close">Đóng phiếu</button>` : ""}
        ${isOpen ? `<button type="button" class="btn danger" data-a="cancel">Hủy phiếu (báo nhầm)</button>` : ""}
      </div>`,
  });
  const on = (a, fn) => { const b = $(`[data-a="${a}"]`, m.el); if (b) b.addEventListener("click", fn); };
  on("start", () => call("start", undefined, "Đã chuyển sang đang xử lý."));
  on("resolve", () => {
    const res = val(m.form, "resolution");
    if (res.length < 3) return toast("Vui lòng ghi ngắn gọn đã xử lý gì.", "err");
    call("resolve", { resolution: res, cost: val(m.form, "cost") || null }, "Đã đánh dấu xử lý xong.");
  });
  on("close", () => call("close", {}, "Đã đóng phiếu."));
  on("cancel", () => { m.close(); reasonForm("Hủy phiếu sự cố", 3, (r) => must("POST", `/api/v1/incidents/${id}/cancel?` + qs({ reason: r })), "Đã hủy phiếu.", after); });
}

/* ======================================================================
   8. NGƯỜI THUÊ — hóa đơn của tôi (GET /invoices/mine)
   ====================================================================== */
VIEWS["my-invoices"] = async (v) => {
  const list = await must("GET", "/api/v1/invoices/mine");
  state.myRoom = list.length ? { id: list[0].room_id, number: list[0].room_number } : null;
  const due = list.filter((i) => !["PAID", "CANCELLED"].includes(i.status));
  const owed = due.reduce((a, i) => a + num(i.total_amount) - num(i.paid_amount), 0);
  const next = due.sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  v.innerHTML = head("Hóa đơn của tôi", state.myRoom ? `Phòng ${esc(state.myRoom.number)}` : "") + `
    <div class="card bill" style="margin-bottom:16px">
      ${owed > 0 ? `<div class="muted">Cần thanh toán</div><div class="amt" style="color:${next && next.days_overdue ? "var(--red)" : "var(--txt)"}">${fmtMoney(owed)}</div>
          <div class="muted">${next.days_overdue ? `Đã quá hạn ${next.days_overdue} ngày` : `Hạn trả ${fmtDate(next.due_date)}`}</div>
          <button class="btn" style="margin-top:14px" id="pay">${ico("cash", "sm")}Xem cách thanh toán</button>`
        : `<div style="display:flex;gap:12px;align-items:center"><div class="todo" style="padding:0;border:0"><div class="dot g">${ico("check")}</div></div>
           <div><b>Bạn đã thanh toán đủ</b><div class="muted">Không có khoản nào cần trả.</div></div></div>`}
    </div>
    <div class="card bill-list">
      <div class="card-h"><h3>Các kỳ gần đây</h3></div>
      ${list.length ? list.map((i) => `<div class="item" data-id="${i.id}">
          <div style="flex:1"><div class="strong">${fmtPeriod(i.period)}</div><div class="muted" style="font-size:12.5px">Hạn ${fmtDate(i.due_date)}</div></div>
          <div class="right"><div class="money strong">${fmtMoney(i.total_amount)}</div>${pill(LABEL.invoice, i.status)}</div>
          ${ico("chev", "sm")}</div>`).join("")
        : empty("receipt", "Chưa có hóa đơn nào")}
    </div>`;
  $$(".item[data-id]", v).forEach((el) => el.addEventListener("click", () => {
    const inv = list.find((x) => x.id === el.dataset.id);
    modal({ title: `${fmtPeriod(inv.period)} ${pill(LABEL.invoice, inv.status)}`, body: invoiceLines(inv) +
      `<div class="muted" style="margin-top:12px;font-size:12.5px">Số hóa đơn ${esc(inv.invoice_no)} · hạn ${fmtDate(inv.due_date)}</div>` });
  }));
  const pay = $("#pay");
  if (pay) pay.addEventListener("click", () => modal({
    title: "Cách thanh toán",
    body: `<p>Chuyển khoản <b class="money">${fmtMoney(owed)}</b> với nội dung:</p>
      <div class="card" style="padding:12px 14px;margin:10px 0;font-family:ui-monospace,monospace">${esc((state.myRoom && state.myRoom.number) || "")} ${esc(next.invoice_no)}</div>
      <p class="muted">Hoặc trả tiền mặt trực tiếp cho quản lý. Hóa đơn sẽ chuyển sang “Đã thanh toán” sau khi quản lý xác nhận.</p>`,
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
    <div class="card bill-list" id="list">${skeleton()}</div>`;
  const load = async () => {
    const list = items(await api("GET", "/api/v1/incidents?page_size=50"));
    $("#list").innerHTML = list.length ? list.map((i) => `<div class="item" data-id="${i.id}">
        <div style="flex:1;min-width:0"><div class="strong">${esc(i.title)}</div>
          <div class="muted" style="font-size:12.5px">${LABEL.category[i.category] || esc(i.category)} · ${fmtDate(i.created_at)}</div></div>
        ${pill(LABEL.incident, i.status)}${ico("chev", "sm")}</div>`).join("")
      : empty("wrench", "Bạn chưa báo sự cố nào", "Có gì hỏng trong phòng, bấm “Báo sự cố mới”.");
    $$(".item[data-id]", $("#list")).forEach((el) => el.addEventListener("click", () => myIncident(el.dataset.id, load)));
  };
  $("#new").addEventListener("click", () => modal({
    title: "Báo sự cố mới",
    body: `
      <div class="field"><label>Vấn đề gặp phải</label><input name="title" required minlength="3" maxlength="200" placeholder="VD: Vòi nước nhà tắm bị rỉ"></div>
      <div class="row2"><div class="field"><label>Loại</label><select name="category">${options(LABEL.category, "PLUMBING")}</select></div>
        <div class="field"><label>Mức độ</label><select name="priority">
          <option value="NORMAL">Bình thường</option><option value="HIGH">Cần sửa sớm</option><option value="URGENT">Khẩn cấp (nguy hiểm)</option></select></div></div>
      <div class="field"><label>Mô tả thêm</label><textarea name="description" maxlength="5000" placeholder="Hỏng từ khi nào, ở vị trí nào…"></textarea></div>
      ${state.myRoom ? `<div class="help muted">Phiếu được gắn với phòng ${esc(state.myRoom.number)}.</div>` : ""}`,
    submit: "Gửi báo cáo",
    onSubmit: async (form) => {
      if (val(form, "title").length < 3) throw new Error("Vui lòng mô tả vấn đề (ít nhất 3 ký tự).");
      await must("POST", "/api/v1/incidents", {
        title: val(form, "title"), category: val(form, "category"), priority: val(form, "priority"),
        description: val(form, "description") || null, room_id: state.myRoom ? state.myRoom.id : null,
        reported_by_phone: state.user.phone || null,
      });
      toast("Đã gửi. Quản lý sẽ liên hệ với bạn sớm.");
      load();
    },
  }));
  await load();
};

async function myIncident(id, after) {
  const i = await must("GET", "/api/v1/incidents/" + id);
  const canRate = ["RESOLVED", "CLOSED"].includes(i.status) && !i.rating;
  modal({
    title: `${esc(i.title)} ${pill(LABEL.incident, i.status)}`,
    body: `<dl class="kv"><dt>Mã phiếu</dt><dd>${esc(i.ticket_no)}</dd>
        <dt>Gửi lúc</dt><dd>${new Date(i.created_at).toLocaleString("vi-VN")}</dd>
        ${i.description ? `<dt>Mô tả</dt><dd style="white-space:pre-wrap">${esc(i.description)}</dd>` : ""}
        ${i.assigned_to_name ? `<dt>Người xử lý</dt><dd>${esc(i.assigned_to_name)}</dd>` : ""}
        ${i.resolution ? `<dt>Kết quả</dt><dd style="white-space:pre-wrap">${esc(i.resolution)}</dd>` : ""}
        ${i.rating ? `<dt>Bạn đã đánh giá</dt><dd>${"★".repeat(i.rating)}${"☆".repeat(5 - i.rating)}</dd>` : ""}</dl>
      ${canRate ? `<div class="section-t">Bạn hài lòng với việc xử lý chứ?</div>
        <div class="field"><select name="rating"><option value="5">★★★★★ Rất hài lòng</option><option value="4">★★★★ Hài lòng</option>
          <option value="3">★★★ Tạm được</option><option value="2">★★ Chưa tốt</option><option value="1">★ Rất tệ</option></select></div>
        <div class="field"><input name="comment" maxlength="2000" placeholder="Góp ý thêm (không bắt buộc)"></div>` : ""}`,
    submit: canRate ? "Gửi đánh giá" : null,
    onSubmit: canRate ? async (form) => {
      await must("POST", `/api/v1/incidents/${id}/rating`, { rating: Number(val(form, "rating")), comment: val(form, "comment") || null });
      toast("Cảm ơn bạn đã đánh giá.");
      after();
    } : null,
  });
}

/* ======================================================================
   10. HỒ SƠ + ĐỔI MẬT KHẨU
   ====================================================================== */
VIEWS.profile = async (v) => {
  const u = await must("GET", "/api/v1/auth/me");
  v.innerHTML = head("Hồ sơ", "") + `
    <div class="card" style="max-width:620px">
      <div class="card-b" style="display:flex;gap:16px;align-items:center;border-bottom:1px solid var(--line)">
        <div class="avatar" style="width:52px;height:52px;font-size:18px">${esc(initials(u.full_name))}</div>
        <div><div style="font-size:17px;font-weight:700">${esc(u.full_name)}</div><div class="muted">@${esc(u.username)} · ${LABEL.role[u.role] || u.role}</div></div>
      </div>
      <div class="card-b"><dl class="kv">
        <dt>Email</dt><dd>${esc(u.email)}</dd><dt>Điện thoại</dt><dd>${esc(u.phone || "—")}</dd>
        <dt>Đăng nhập gần nhất</dt><dd>${u.last_login_at ? new Date(u.last_login_at).toLocaleString("vi-VN") : "—"}</dd></dl>
        <button class="btn ghost" id="pw" style="margin-top:18px">${ico("key", "sm")}Đổi mật khẩu</button></div>
    </div>`;
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
