/* Accounts Desk - one page, no build step. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const rs = (n) => "₹" + inr.format(Math.round(n || 0));
const day = (d) => {
  if (!d) return "";
  const [y, m, dd] = d.slice(0, 10).split("-");
  return `${dd}-${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+m - 1]}-${y.slice(2)}`;
};
const WORD = { payable: "paid", receivable: "received" };
const STATUS = { open: "To do", part: "Part done", done: "Marked", cleared: "Cleared" };

const S = {
  me: null, users: [], firms: [], kind: "payable", mine: true, tab: "work",
  bills: [], selected: new Map(), alertState: "open",
};

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-Requested-With": "accounts-desk" } };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (res.status === 401) { location.href = "/login"; throw new Error("signed out"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok && res.status !== 409) throw new Error(data.error || `Error ${res.status}`);
  data._status = res.status;
  return data;
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
const fail = (e) => toast(e.message || String(e), 4500);

function openModal(title, html) {
  $("#mTitle").textContent = title;
  $("#mBody").innerHTML = html;
  $("#modal").hidden = false;
  return $("#mBody");
}
const closeModal = () => ($("#modal").hidden = true);

/* ============================================================ start */

async function start() {
  S.me = await api("/api/me");
  document.body.classList.toggle("admin", S.me.role === "admin");
  $("#whoami").textContent = `Signed in as ${S.me.name}`;
  await loadPeople();
  bindAll();
  showTab("work", true);
  refreshAlertBadge();
}

async function loadPeople() {
  [S.users, S.firms] = await Promise.all([api("/api/users"), api("/api/firms")]);
  const firmOpts = S.firms.filter((f) => f.active)
    .map((f) => `<option value="${f.id}">${esc(f.code)} – ${esc(f.name)}</option>`).join("");
  for (const id of ["#fFirm", "#sFirm"]) {
    const keep = $(id).value;
    $(id).innerHTML = `<option value="">All firms</option>` + firmOpts;
    $(id).value = keep;
  }
  $("#upFirm").innerHTML = `<option value="">Read from file</option>` + firmOpts;
  const keep = $("#fWho").value;
  $("#fWho").innerHTML = `<option value="">Everyone</option><option value="me">Given to me</option>` +
    `<option value="none">Given to nobody</option>` +
    S.users.filter((u) => u.active).map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("");
  $("#fWho").value = keep;
}

function bindAll() {
  $$(".tabs button").forEach((b) => b.addEventListener("click", () =>
    showTab(b.dataset.tab, b.dataset.mine === "1")));
  $$("#kindSeg button").forEach((b) => b.addEventListener("click", () => {
    S.kind = b.dataset.kind;
    $$("#kindSeg button").forEach((x) => x.classList.toggle("on", x === b));
    clearSelection(); loadBills();
  }));
  ["#fFirm", "#fWho", "#fStatus"].forEach((id) => $(id).addEventListener("change", () => {
    clearSelection(); loadBills();
  }));
  let t; $("#fSearch").addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadBills, 250); });

  $("#sPeriod").addEventListener("change", () => {
    const custom = $("#sPeriod").value === "custom";
    $("#sFrom").hidden = $("#sTo").hidden = !custom;
    loadScore();
  });
  ["#sFirm", "#sFrom", "#sTo"].forEach((id) => $(id).addEventListener("change", loadScore));

  $$("#alertSeg button").forEach((b) => b.addEventListener("click", () => {
    S.alertState = b.dataset.state;
    $$("#alertSeg button").forEach((x) => x.classList.toggle("on", x === b));
    loadAlerts();
  }));

  $("#uploadBtn").addEventListener("click", () => { showTab("more"); $("#upFiles").focus(); });
  $("#upGo").addEventListener("click", doUpload);
  $("#nuGo").addEventListener("click", addPerson);
  $("#nfGo").addEventListener("click", addFirm);
  $("#pwGo").addEventListener("click", changePassword);
  $$("[data-redis]").forEach((b) => b.addEventListener("click", () => redistribute(b.dataset.redis)));

  $("#selClear").addEventListener("click", clearSelection);
  $("#selMark").addEventListener("click", () => openMark([...S.selected.values()]));
  $("#mClose").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
}

function showTab(tab, mine) {
  S.tab = tab;
  $$(".tabs button").forEach((b) => b.classList.toggle("on",
    b.dataset.tab === tab && (tab !== "work" || (b.dataset.mine === "1") === !!mine)));
  $$(".screen").forEach((s) => (s.hidden = s.dataset.screen !== tab));
  if (tab !== "work") $("#selbar").hidden = true;
  if (tab === "work") {
    S.mine = !!mine;
    $("#title").textContent = S.mine ? "My work" : "All bills";
    $("#fWho").value = S.mine ? "me" : "";
    $("#fWho").parentElement && ($("#fWho").hidden = S.mine);
    clearSelection(); loadBills();
  } else if (tab === "score") { $("#title").textContent = "Scoreboard"; loadScore(); }
  else if (tab === "alerts") { $("#title").textContent = "Alerts"; loadAlerts(); }
  else if (tab === "more") { $("#title").textContent = "More"; loadMore(); }
  window.scrollTo(0, 0);
}

/* ============================================================ bills */

async function loadBills() {
  const p = new URLSearchParams({
    kind: S.kind, status: $("#fStatus").value, firm: $("#fFirm").value,
    assigned: S.mine ? "me" : $("#fWho").value, q: $("#fSearch").value.trim(),
  });
  try {
    const data = await api("/api/bills?" + p);
    S.bills = data.bills;
    renderBills(data);
  } catch (e) { fail(e); }
}

function overdueChip(d) {
  if (!d || d < 30) return "";
  return `<span class="chip od ${d >= 90 ? "bad" : ""}">${d}d overdue</span>`;
}

function renderBills(data) {
  const list = $("#billList");
  const groups = new Map();
  for (const b of S.bills) {
    const k = b.firm_id + "|" + b.party_key;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(b);
  }
  const todo = S.bills.filter((b) => b.status === "open" || b.status === "part");
  $("#strip").innerHTML =
    `<span><b>${S.bills.length}</b> bills · <b>${groups.size}</b> parties</span>` +
    `<span>Still to ${S.kind === "payable" ? "pay" : "collect"}: <b>${rs(todo.reduce((a, b) => a + b.remaining, 0))}</b></span>` +
    (data.count > S.bills.length ? `<span>showing first ${S.bills.length} of ${data.count}</span>` : "");

  const sorted = [...groups.values()].sort((a, b) =>
    b.reduce((s, x) => s + x.remaining, 0) - a.reduce((s, x) => s + x.remaining, 0));
  list.innerHTML = sorted.map((g) => {
    const f = g[0];
    const total = g.reduce((s, x) => s + (x.status === "cleared" ? x.pending : x.remaining), 0);
    const markable = g.filter((b) => b.status === "open" || b.status === "part");
    return `<div class="party">
      <div class="party-head">
        ${markable.length ? `<input type="checkbox" data-party="${esc(f.firm_id + "|" + f.party_key)}" title="Pick all bills of this party">` : ""}
        <div class="name"><b>${esc(f.party)}</b>
          <small>${esc(f.firm)} · ${g.length} bill${g.length > 1 ? "s" : ""} · given to ${esc(f.assigned_name || "nobody")}</small></div>
        <div class="amt">${rs(total)}</div>
      </div>
      ${g.map(billRow).join("")}
    </div>`;
  }).join("");

  $("#billEmpty").hidden = S.bills.length > 0;
  $("#billEmpty").textContent = S.mine && $("#fStatus").value === "todo"
    ? "Nothing to do here. 🎉" : "No bills match.";

  $$(".bill", list).forEach((row) => row.addEventListener("click", (e) => {
    if (e.target.matches("input")) return;
    openBill(+row.dataset.id);
  }));
  $$(".bill input[type=checkbox]", list).forEach((c) => {
    c.checked = S.selected.has(+c.dataset.id);
    c.addEventListener("change", () => toggleSelect(+c.dataset.id, c.checked));
  });
  $$(".party-head input[type=checkbox]", list).forEach((c) => c.addEventListener("change", () => {
    const [fid, key] = c.dataset.party.split("|");
    S.bills.filter((b) => String(b.firm_id) === fid && b.party_key === key &&
      (b.status === "open" || b.status === "part"))
      .forEach((b) => toggleSelect(b.id, c.checked));
    renderSelectionChecks();
  }));
}

function billRow(b) {
  const can = b.status === "open" || b.status === "part";
  const done = b.done_by.length ? ` · ${WORD[b.kind]} by ${esc(b.done_by.join(", "))}` : "";
  return `<div class="bill" data-id="${b.id}">
    ${can ? `<input type="checkbox" data-id="${b.id}">` : `<span style="width:20px"></span>`}
    <div class="main">
      <div class="ref">${esc(b.ref_no || "(no bill no)")} <span class="chip ${b.status}">${STATUS[b.status]}</span>
        ${b.alerts ? `<span class="chip alert">⚠ ${b.alerts}</span>` : ""} ${can ? overdueChip(b.overdue_days) : ""}</div>
      <div class="meta">${day(b.bill_date)}${done}</div>
    </div>
    <div class="right">
      <div class="money">${rs(b.status === "cleared" ? b.pending : b.remaining)}</div>
      ${b.waiting > 0 && b.status !== "cleared" ? `<div class="was">of ${rs(b.pending)} in Tally</div>` : ""}
    </div>
  </div>`;
}

function toggleSelect(id, on) {
  const b = S.bills.find((x) => x.id === id);
  if (!b) return;
  if (on) {
    const first = [...S.selected.values()][0];
    if (first && (first.party_key !== b.party_key || first.firm_id !== b.firm_id)) {
      toast("Pick bills of one party at a time.");
      renderSelectionChecks(); return;
    }
    S.selected.set(id, b);
  } else S.selected.delete(id);
  renderSelectionChecks();
}

function renderSelectionChecks() {
  $$("#billList .bill input[type=checkbox]").forEach((c) => (c.checked = S.selected.has(+c.dataset.id)));
  const sel = [...S.selected.values()];
  $("#selbar").hidden = !sel.length;
  if (sel.length) {
    $("#selText").textContent = `${sel.length} bill${sel.length > 1 ? "s" : ""} · ${rs(sel.reduce((a, b) => a + b.remaining, 0))}`;
    $("#selMark").textContent = `Mark ${WORD[sel[0].kind]}`;
  }
}

function clearSelection() {
  S.selected.clear();
  $$("#billList input[type=checkbox]").forEach((c) => (c.checked = false));
  $("#selbar").hidden = true;
}

/* ============================================================ marking */

function openMark(bills, prefill) {
  if (!bills.length) return;
  const kind = bills[0].kind;
  const word = WORD[kind];
  const body = openModal(`Mark ${word} – ${bills[0].party}`, `
    <p class="hint">${kind === "payable" ? "You paid" : "You received"} these bills. Your name goes on the entry.</p>
    ${bills.map((b) => `<div class="mark-line">
        <div class="grow"><b>${esc(b.ref_no || "(no bill no)")}</b> <small>${day(b.bill_date)}</small><br>
          <small>${b.waiting > 0 ? `${rs(b.waiting)} already marked · ` : ""}still ${rs(b.remaining)}</small></div>
        <input type="number" inputmode="decimal" step="0.01" min="0" data-amt="${b.id}" value="${Math.max(b.remaining, 0)}">
      </div>`).join("")}
    <div class="mark-total" id="mkTotal"></div>
    <div class="row2">
      <label>Date ${word} <input type="date" id="mkDate" value="${S.me.today}" max="${S.me.today}"></label>
      <label>Mode <select id="mkMode">${S.me.modes.map((m) => `<option>${m}</option>`).join("")}</select></label>
    </div>
    <label>UTR / cheque no. <input id="mkRef" autocomplete="off" placeholder="needed except for cash"></label>
    <label>Remarks <input id="mkRem" autocomplete="off"></label>
    <div id="mkWarn"></div>
    <button class="btn primary" id="mkGo" style="width:100%">Save – mark ${word}</button>`);
  if (prefill) { $("#mkDate").value = prefill.paid_on; $("#mkMode").value = prefill.mode;
    $("#mkRef").value = prefill.reference; $("#mkRem").value = prefill.remarks; }
  const total = () => {
    const t = $$("[data-amt]", body).reduce((a, i) => a + (+i.value || 0), 0);
    $("#mkTotal").textContent = `Total ${rs(t)}`;
  };
  $$("[data-amt]", body).forEach((i) => i.addEventListener("input", () => { total(); resetConfirm(); }));
  ["#mkDate", "#mkMode", "#mkRef"].forEach((id) => $(id).addEventListener("input", resetConfirm));
  total();

  let confirm = false;
  function resetConfirm() {
    if (!confirm) return;
    confirm = false; $("#mkWarn").innerHTML = "";
    $("#mkGo").className = "btn primary"; $("#mkGo").textContent = `Save – mark ${word}`;
  }
  $("#mkGo").addEventListener("click", async () => {
    const payload = {
      lines: $$("[data-amt]", body).map((i) => ({ bill_id: +i.dataset.amt, amount: +i.value })),
      paid_on: $("#mkDate").value, mode: $("#mkMode").value,
      reference: $("#mkRef").value.trim(), remarks: $("#mkRem").value.trim(), confirm,
    };
    if (confirm && $("#mkSure") && !$("#mkSure").checked) {
      toast("Tick the box to confirm you checked it."); return;
    }
    $("#mkGo").disabled = true;
    try {
      const r = await api("/api/entries", { method: "POST", body: payload });
      if (r._status === 409) {
        confirm = true;
        $("#mkWarn").innerHTML = r.warnings.map((w) =>
          `<div class="warn-box ${w.alert ? "high" : "note"}">${w.alert ? "⚠ " : ""}${esc(w.message)}</div>`).join("") +
          (r.serious ? `<label class="check"><input type="checkbox" id="mkSure"> I have checked – this is NOT a double ${kind === "payable" ? "payment" : "entry"}. Save it and flag it for the admin.</label>` : "");
        $("#mkGo").className = r.serious ? "btn warn" : "btn primary";
        $("#mkGo").textContent = r.serious ? "Save anyway (will be flagged)" : "OK, save";
        $("#mkGo").style.width = "100%";
        return;
      }
      closeModal(); clearSelection();
      toast(r.flagged ? "Saved and flagged for the admin to check." : `Marked ${word}. ✔`);
      loadBills(); refreshAlertBadge();
    } catch (e) { fail(e); }
    finally { $("#mkGo") && ($("#mkGo").disabled = false); }
  });
}

/* ============================================================ one bill */

async function openBill(id) {
  let b;
  try { b = await api(`/api/bills/${id}`); } catch (e) { return fail(e); }
  const word = WORD[b.kind];
  const can = b.status === "open" || b.status === "part";
  const admin = S.me.role === "admin";
  const body = openModal(b.party, `
    <div class="facts">
      <div><small>Firm</small>${esc(b.firm)} – ${b.kind === "payable" ? "Payable" : "Receivable"}</div>
      <div><small>Status</small><span class="chip ${b.status}">${STATUS[b.status]}</span></div>
      <div><small>Bill no.</small>${esc(b.ref_no || "-")}</div>
      <div><small>Bill date / due</small>${day(b.bill_date)} / ${day(b.due_date)}</div>
      <div><small>Pending in Tally</small><b>${rs(b.pending)}</b>${b.original_amount !== b.pending ? ` <small>(first seen ${rs(b.original_amount)})</small>` : ""}</div>
      <div><small>Still to ${b.kind === "payable" ? "pay" : "collect"}</small><b>${rs(b.remaining)}</b></div>
      <div><small>Given to</small>${esc(b.assigned_name || "nobody")}</div>
      <div><small>Overdue</small>${b.overdue_days} days</div>
      ${b.cleared_at ? `<div><small>Gone from Tally on</small>${day(b.cleared_at)}</div>` : ""}
    </div>
    <div class="row2">
      ${can ? `<button class="btn primary" id="bMark">Mark ${word}</button>` : `<button class="btn" id="bMark">Add a late entry</button>`}
      ${admin ? `<select id="bWho"><option value="">Give this party to…</option>${S.users.filter((u) => u.active)
        .map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select>` : ""}
    </div>

    ${b.alerts.length ? `<div class="sec">Alerts</div>` + b.alerts.map((a) => `
      <div class="warn-box ${a.resolved_at ? "note" : "high"}">${esc(a.message)}
        ${a.resolved_at ? `<div class="resolved">✔ ${esc(a.resolved_by_name)}: ${esc(a.resolve_note)}</div>` : ""}</div>`).join("") : ""}

    <div class="sec">${word === "paid" ? "Payments" : "Receipts"} marked</div>
    ${b.entries.length ? b.entries.map((e) => `
      <div class="entry ${e.deleted_at ? "gone" : ""}">
        <div class="top"><b>${rs(e.amount)} – ${esc(e.by_name)}</b><span>${day(e.paid_on)}</span></div>
        <small>${esc(e.mode)} ${esc(e.reference)} ${e.remarks ? "· " + esc(e.remarks) : ""}<br>
          entered ${esc(e.created_at.slice(0, 16))} · ${e.reconciled_at ? "✔ seen in Tally" : "waiting for Tally"}
          ${e.flagged ? ' · <b style="color:var(--red)">flagged</b>' : ""}
          ${e.deleted_at ? `<br>removed by ${esc(e.deleted_by_name)}: ${esc(e.delete_reason)}` : ""}</small>
        ${!e.deleted_at && (e.user_id === S.me.id || admin) ? `<div><button class="btn small danger" data-del="${e.id}">Remove</button></div>` : ""}
      </div>`).join("") : `<p class="hint">Nobody has marked this yet.</p>`}

    <div class="sec">Follow-ups</div>
    <div class="row2">
      <input id="nText" placeholder="${b.kind === "receivable" ? "Called – promised by Friday" : "Asked for revised bill"}">
      <input type="date" id="nDate" title="Promised date (optional)">
    </div>
    <button class="btn" id="nGo" style="margin-top:8px">Add follow-up</button>
    ${b.notes.map((n) => `<div class="entry"><div class="top"><b>${esc(n.by_name)}</b><span>${esc(n.created_at.slice(0, 16))}</span></div>
      ${esc(n.text)}${n.promise_date ? `<br><small>promised by ${day(n.promise_date)}</small>` : ""}</div>`).join("")}

    <div class="sec">History</div>
    ${b.history.map((h) => `<div class="item"><div class="grow">${esc(h.detail)}<small>${esc(h.by_name || "")} · ${esc(h.created_at.slice(0, 16))}</small></div></div>`).join("") || `<p class="hint">-</p>`}
  `);

  $("#bMark").addEventListener("click", () => openMark([b]));
  if ($("#bWho")) $("#bWho").addEventListener("change", async () => {
    const uid = $("#bWho").value; if (!uid) return;
    const name = $("#bWho").selectedOptions[0].textContent;
    if (!confirm(`Give all open ${b.kind} bills of ${b.party} to ${name}?`)) return;
    try { const r = await api(`/api/bills/${b.id}/reassign`, { method: "POST", body: { user_id: +uid } });
      toast(`${r.moved} bill(s) given to ${name}.`); closeModal(); loadBills(); } catch (e) { fail(e); }
  });
  $("#nGo").addEventListener("click", async () => {
    try { await api(`/api/bills/${b.id}/notes`, { method: "POST",
      body: { text: $("#nText").value, promise_date: $("#nDate").value } });
      toast("Follow-up saved."); openBill(b.id); } catch (e) { fail(e); }
  });
  $$("[data-del]", body).forEach((btn) => btn.addEventListener("click", async () => {
    const reason = prompt("Why is this entry being removed? (everyone can see this)");
    if (!reason) return;
    try { await api(`/api/entries/${btn.dataset.del}`, { method: "DELETE", body: { reason } });
      toast("Entry removed."); openBill(b.id); loadBills(); } catch (e) { fail(e); }
  }));
}

/* ============================================================ scoreboard */

async function loadScore() {
  const p = new URLSearchParams({ period: $("#sPeriod").value, firm: $("#sFirm").value,
    from: $("#sFrom").value, to: $("#sTo").value });
  let data;
  try { data = await api("/api/scoreboard?" + p); } catch (e) { return fail(e); }
  $("#scoreRange").textContent = data.from === "2000-01-01" ? "All time" : `${day(data.from)} to ${day(data.to)}`;
  const max = { payable: 1, receivable: 1 };
  for (const p of data.people) for (const k of ["payable", "receivable"]) max[k] = Math.max(max[k], p[k].count);
  const kpi = (p, k) => {
    const x = p[k];
    return `<div class="kpi">
      <h3>${k === "payable" ? "Payments made" : "Receipts collected"}</h3>
      <div class="big">${x.count} <small>entries · ${rs(x.amount)}</small></div>
      <div class="bar"><i style="width:${(x.count / max[k]) * 100}%"></i></div>
      <div class="line">Follow-ups: <b>${x.followups}</b></div>
      <div class="line">Still open with them: <b>${x.open_count}</b> bills · <b>${rs(x.open_amount)}</b></div>
      <div class="line ${x.overdue_60 ? "bad" : ""}">60+ days overdue: <b>${x.overdue_60}</b></div>
      <div class="line ${x.flagged ? "bad" : ""}">Flagged entries: <b>${x.flagged}</b></div>
      <div class="line ${x.unclaimed ? "bad" : ""}">Cleared, not marked: <b>${x.unclaimed}</b></div>
    </div>`;
  };
  $("#scoreList").innerHTML = data.people.map((p) => `
    <div class="person">
      <div class="person-head"><b>${esc(p.name)}</b>
        <small>${p.active ? (p.takes_work ? "gets bills" : "does not get bills") : "no longer active"}</small></div>
      <div class="grid">${kpi(p, "payable")}${kpi(p, "receivable")}</div>
    </div>`).join("") || `<p class="empty">No one yet.</p>`;
}

/* ============================================================ alerts */

async function refreshAlertBadge() {
  try {
    const a = await api("/api/alerts?state=open");
    const high = a.filter((x) => x.severity === "high").length;
    $("#alertBadge").hidden = !a.length;
    $("#alertBadge").textContent = high || a.length;
  } catch (_) { /* badge is optional */ }
}

async function loadAlerts() {
  let list;
  try { list = await api("/api/alerts?state=" + S.alertState); } catch (e) { return fail(e); }
  $("#alertEmpty").hidden = list.length > 0;
  const admin = S.me.role === "admin";
  $("#alertList").innerHTML = list.map((a) => `
    <div class="alert-card ${a.severity}">
      <div><span class="chip ${a.severity}">${a.severity === "high" ? "Possible double" : "Check"}</span>
        <small class="meta">${esc(a.firm || "")} ${a.bill_kind ? (a.bill_kind === "payable" ? "· payable" : "· receivable") : ""}
          · given to ${esc(a.assigned_name || "nobody")} · ${esc(a.created_at.slice(0, 16))}</small></div>
      <div class="msg">${esc(a.message)}</div>
      ${a.resolved_at ? `<div class="resolved">✔ ${esc(a.resolved_by_name)} on ${esc(a.resolved_at.slice(0, 16))}: ${esc(a.resolve_note)}</div>` : ""}
      <div class="acts">
        ${a.bill_id ? `<button class="btn small" data-bill="${a.bill_id}">Open bill</button>` : ""}
        ${admin && !a.resolved_at ? `<button class="btn small primary" data-res="${a.id}">Mark checked</button>` : ""}
      </div>
    </div>`).join("");
  $$("[data-bill]", $("#alertList")).forEach((b) => b.addEventListener("click", () => openBill(+b.dataset.bill)));
  $$("[data-res]", $("#alertList")).forEach((b) => b.addEventListener("click", async () => {
    const note = prompt("What did you find? (e.g. 'Two separate invoices, OK' or 'Double payment – asked vendor for refund')");
    if (!note) return;
    try { await api(`/api/alerts/${b.dataset.res}/resolve`, { method: "POST", body: { note } });
      loadAlerts(); refreshAlertBadge(); } catch (e) { fail(e); }
  }));
}

/* ============================================================ more */

async function loadMore() {
  try {
    await loadPeople();
    const [ups, acts] = await Promise.all([api("/api/uploads"), api("/api/activity?limit=80")]);
    $("#upHistory").innerHTML = ups.map((u) => `<div class="item"><div class="grow">
        <b>${esc(u.firm)} ${u.kind === "payable" ? "Payable" : "Receivable"}</b> – ${esc(u.file_name)}
        <small>report ${day(u.report_date)} · by ${esc(u.by_name)} at ${esc(u.created_at.slice(0, 16))} ·
        ${u.bills_in_file} bills ${rs(u.total_in_file)} · ${u.new_bills} new · ${u.cleared_bills} cleared</small></div></div>`).join("")
      || `<p class="hint">No files yet.</p>`;
    $("#activityList").innerHTML = acts.map((a) => `<div class="item"><div class="grow">${esc(a.detail || a.action)}
        <small>${esc(a.by_name || "")} · ${esc(a.created_at.slice(0, 16))}</small></div></div>`).join("");
    renderTeam(); renderFirms();
  } catch (e) { fail(e); }
}

function renderTeam() {
  $("#teamList").innerHTML = S.users.map((u) => `<div class="item">
      <div class="grow"><b>${esc(u.name)}</b> <small>${esc(u.username)} · ${u.role === "admin" ? "admin" : "accounts team"}${u.active ? "" : " · switched off"}</small></div>
      <div class="tog">
        <label class="check"><input type="checkbox" data-u="${u.id}" data-f="takes_work" ${u.takes_work ? "checked" : ""}> Gets bills</label>
        <label class="check"><input type="checkbox" data-u="${u.id}" data-f="active" ${u.active ? "checked" : ""}> Active</label>
        <button class="btn small" data-pw="${u.id}">Reset password</button>
      </div></div>`).join("");
  $$("[data-u]", $("#teamList")).forEach((c) => c.addEventListener("change", async () => {
    const u = S.users.find((x) => x.id === +c.dataset.u);
    if (!c.checked && !confirm(`${u.name}'s open bills will be shared out to the others. Continue?`)) {
      c.checked = true; return;
    }
    try { const r = await api(`/api/users/${u.id}`, { method: "PUT", body: { [c.dataset.f]: c.checked } });
      toast(r.moved ? `${r.moved} open bill(s) shared out to the others.` : "Saved."); loadMore(); }
    catch (e) { fail(e); c.checked = !c.checked; }
  }));
  $$("[data-pw]", $("#teamList")).forEach((b) => b.addEventListener("click", async () => {
    const pw = prompt("New password (8+ characters). Tell it to the person.");
    if (!pw) return;
    try { await api(`/api/users/${b.dataset.pw}`, { method: "PUT", body: { password: pw } }); toast("Password reset."); }
    catch (e) { fail(e); }
  }));
}

function renderFirms() {
  $("#firmList").innerHTML = S.firms.map((f) => `<div class="item"><div class="grow"><b>${esc(f.code)}</b> ${esc(f.name)}
    ${f.aliases ? `<small>also: ${esc(f.aliases.split("\n").join(", "))}</small>` : ""}</div></div>`).join("");
}

async function addPerson() {
  try {
    await api("/api/users", { method: "POST", body: { name: $("#nuName").value, username: $("#nuUser").value,
      password: $("#nuPass").value, role: $("#nuRole").value, takes_work: $("#nuWork").checked } });
    ["#nuName", "#nuUser", "#nuPass"].forEach((i) => ($(i).value = ""));
    toast("Added. Use 'Share out' below to give them bills."); loadMore();
  } catch (e) { fail(e); }
}

async function addFirm() {
  try { await api("/api/firms", { method: "POST", body: { code: $("#nfCode").value, name: $("#nfName").value } });
    $("#nfCode").value = $("#nfName").value = ""; toast("Firm added."); loadMore(); }
  catch (e) { fail(e); }
}

async function redistribute(kind) {
  if (!confirm(`Share out all open ${kind}s again, evenly?`)) return;
  try { const r = await api("/api/redistribute", { method: "POST", body: { kind } });
    toast(`${r.moved} bill(s) moved.`); } catch (e) { fail(e); }
}

async function changePassword() {
  try { await api("/api/me/password", { method: "PUT", body: { current: $("#pwOld").value, new: $("#pwNew").value } });
    $("#pwOld").value = $("#pwNew").value = ""; toast("Password changed."); }
  catch (e) { fail(e); }
}

async function doUpload() {
  const files = $("#upFiles").files;
  if (!files.length) return toast("Choose the Tally file(s) first.");
  const form = new FormData();
  for (const f of files) form.append("file", f);
  form.append("firm_id", $("#upFirm").value);
  form.append("kind", $("#upKind").value);
  $("#upGo").disabled = true; $("#upGo").textContent = "Uploading…";
  try {
    const res = await api("/api/upload", { method: "POST", form });
    $("#upResult").innerHTML = (Array.isArray(res) ? res : []).map((r) => r.ok ? `
      <div class="result ok"><b>${esc(r.file)}</b><br>
        ${esc(r.firm)} ${r.kind === "payable" ? "Bills Payable" : "Bills Receivable"} dated ${day(r.report_date)} –
        ${r.bills} bills, ${rs(r.total)}${r.tally_total != null && Math.abs(r.tally_total - r.total) > 1 ? ` <b style="color:var(--red)">(Tally total says ${rs(r.tally_total)} – check the file)</b>` : " (matches Tally total)"}<br>
        <b>${r.new}</b> new · <b>${r.updated}</b> already here · <b>${r.cleared}</b> gone from Tally (cleared)
        ${r.alerts ? ` · <b style="color:var(--red)">${r.alerts} alert(s)</b>` : ""}<br>
        ${Object.keys(r.given).length ? "New bills given to: " + Object.entries(r.given).map(([n, c]) => `${esc(n)} ${c}`).join(", ") : ""}
        ${r.unassigned ? `<br><b>${r.unassigned} bill(s) given to nobody</b> – add people under Team and tick “Gets bills”.` : ""}
      </div>` : `<div class="result bad"><b>${esc(r.file)}</b>: ${esc(r.error)}</div>`).join("");
    $("#upFiles").value = "";
    loadMore(); refreshAlertBadge();
  } catch (e) { fail(e); }
  finally { $("#upGo").disabled = false; $("#upGo").textContent = "Upload"; }
}

start().catch(fail);
