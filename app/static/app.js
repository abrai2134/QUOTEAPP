/* Well Worth quotation app - click-based quote builder (AppSheet replacement). */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  screen: 'quotes',
  companies: [],
  salespersons: [],
  defaultTerms: '',
  defaultCompany: '',
  mailConfigured: false,
  headings: ['QUOTATION'],
  stdFiles: ['NON STD FILE'],
  sheet: { url: '', secret: '', configured: false, pending: 0 },
  editingClient: null,
  editingMachine: null,
  quote: null,       // the quote being edited (null = new)
  items: [],         // working item rows
  clientId: null,
};

const money = (n) => '₹' + (Number(n) || 0).toLocaleString('en-IN', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.toggle('err', isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
}

function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ------------------------------------------------------------------ nav */

const TITLES = {
  quotes: 'Quotations', form: 'Quotation', detail: 'Quotation',
  clients: 'Parties', 'party-edit': 'Party', machines: 'Machines & Rates',
  'machine-edit': 'Machine', settings: 'Setup',
};

function show(screen) {
  state.screen = screen;
  $$('.screen').forEach((s) => { s.hidden = s.dataset.screen !== screen; });
  $('#screenTitle').textContent = TITLES[screen] || 'Quotation';
  const tabFor = { quotes: 'quotes', form: 'new', detail: 'quotes',
                   clients: 'clients', 'party-edit': 'clients',
                   machines: 'machines', 'machine-edit': 'machines',
                   settings: 'settings' };
  $$('.tabbar button').forEach((b) => b.classList.toggle('active', b.dataset.go === tabFor[screen]));
  const action = $('#topAction');
  if (screen === 'quotes') {
    action.hidden = false;
    action.textContent = '+ New';
    action.onclick = () => newQuote();
  } else {
    action.hidden = true;
  }
  window.scrollTo(0, 0);
}

$$('.tabbar button').forEach((btn) => {
  btn.onclick = () => {
    const go = btn.dataset.go;
    if (go === 'new') return newQuote();
    if (go === 'quotes') loadQuotes();
    if (go === 'clients') loadClients();
    if (go === 'machines') loadMachines();
    if (go === 'settings') loadSettings();
    show(go);
  };
});

/* ------------------------------------------------------- bottom sheet */

let sheetPick = null;
function openSheet({ placeholder, search, render, onPick }) {
  sheetPick = { search, render, onPick };
  $('#sheetSearch').value = '';
  $('#sheetSearch').placeholder = placeholder || 'Search…';
  $('#sheetBackdrop').hidden = false;
  runSheetSearch('');
  setTimeout(() => $('#sheetSearch').focus(), 60);
}

function closeSheet() {
  $('#sheetBackdrop').hidden = true;
  sheetPick = null;
}

async function runSheetSearch(query) {
  if (!sheetPick) return;
  const body = $('#sheetBody');
  body.innerHTML = '<p class="hint" style="padding:16px">Searching…</p>';
  try {
    const rows = await sheetPick.search(query);
    if (!rows.length) {
      body.innerHTML = '<p class="hint" style="padding:16px">Nothing found.</p>';
      return;
    }
    body.innerHTML = '';
    rows.forEach((row) => {
      const btn = document.createElement('button');
      btn.className = 'sheet-row';
      btn.innerHTML = sheetPick.render(row);
      btn.onclick = () => { const cb = sheetPick.onPick; closeSheet(); cb(row); };
      body.appendChild(btn);
    });
  } catch (err) {
    body.innerHTML = `<p class="hint" style="padding:16px">${err.message}</p>`;
  }
}

$('#sheetSearch').addEventListener('input', debounce((e) => runSheetSearch(e.target.value)));
$('#sheetClose').onclick = closeSheet;
$('#sheetBackdrop').onclick = (e) => { if (e.target.id === 'sheetBackdrop') closeSheet(); };

/* ----------------------------------------------------------- quotes list */

async function loadQuotes(query = '') {
  const rows = await api(`/api/quotes?q=${encodeURIComponent(query)}`);
  const list = $('#quoteList');
  list.innerHTML = '';
  $('#quotesEmpty').hidden = rows.length > 0 || Boolean(query);
  rows.forEach((q) => {
    const card = document.createElement('button');
    card.className = 'card';
    const status = (q.order_status || '').toUpperCase();
    const cls = status === 'PENDING' ? 'warn' : 'ok';
    const unsynced = !q.synced_at;
    card.innerHTML = `
      <span class="amt">${money(q.grand_total)}</span>
      <div class="t">${escapeHtml(q.party_name || '(no party)')}</div>
      <div class="s">
        <span class="pill">${escapeHtml(q.heading || 'QUOTATION')}</span>
        <span class="pill ${cls}">${escapeHtml(status || 'PENDING')}</span>
        ${unsynced ? '<span class="pill err">NOT IN SHEET</span>' : ''}
        <br>${escapeHtml(q.company_name || '')}${q.city ? ' · ' + escapeHtml(q.city) : ''}<br>
        ${escapeHtml((q.quote_date || '').slice(0, 16))} · by ${escapeHtml(q.salesperson || '-')}
      </div>`;
    card.onclick = () => openQuote(q.id);
    list.appendChild(card);
  });
}

$('#quoteSearch').addEventListener('input', debounce((e) => loadQuotes(e.target.value)));

/* ---------------------------------------------------------- quote detail */

let currentQuoteId = null;

async function openQuote(id) {
  const q = await api(`/api/quotes/${id}`);
  currentQuoteId = id;
  const rows = q.items.map((it, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${escapeHtml(it.description)}<div class="model">${escapeHtml(it.model)}</div></td>
      <td class="num">${it.qty}</td>
      <td class="num">${money(it.rate)}</td>
      <td class="num">${money(it.amount)}</td>
    </tr>`).join('');

  $('#detailBody').innerHTML = `
    <div class="detail-head">
      <h3>${escapeHtml(q.party_name)}</h3>
      <div class="meta">${escapeHtml(q.company.name || '')}
${escapeHtml((q.quote_date || '').slice(0, 16))} · Prepared by ${escapeHtml(q.salesperson || '-')}
Order: ${escapeHtml(q.order_status || '')} · Payment: ${escapeHtml(q.payment_status || '')} · Dispatch: ${escapeHtml(q.dispatch || '')}
${q.synced_at ? 'In the Order items sheet · ' + escapeHtml(q.synced_at)
              : 'Not in the sheet yet' + (q.sync_error ? ' · ' + escapeHtml(q.sync_error) : '')}</div>
    </div>
    <div class="block">
      <h2>Items</h2>
      <table class="items">
        <thead><tr><th>#</th><th>Description</th><th class="num">Qty</th>
        <th class="num">Rate</th><th class="num">Amount</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="totals">
        <div><span>Sub total</span><b>${money(q.subtotal)}</b></div>
        <div><span>GST amount</span><b>${money(q.gst_amount)}</b></div>
        <div class="grand"><span>G. Total</span><b>${money(q.grand_total)}</b></div>
        <div><span>Advance</span><b>${money(q.advance)}</b></div>
        <div><span>Balance payable</span><b>${money(q.balance)}</b></div>
      </div>
    </div>`;
  show('detail');
}

$('#btnSyncQuote').onclick = async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  try {
    const res = await api(`/api/quotes/${currentQuoteId}/sync`, { method: 'POST' });
    toast(res.message);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    await refreshSettings();
    await openQuote(currentQuoteId);
  }
};

$('#btnXlsx').onclick = () => { window.location = `/api/quotes/${currentQuoteId}/download?fmt=xlsx`; };
$('#btnPrint').onclick = () => {
  // Opens the A4 layout; the browser's Print dialog saves it as a PDF.
  window.open(`/api/quotes/${currentQuoteId}/print`, '_blank');
};
$('#btnPdf').onclick = () => {
  toast('Building PDF…');
  window.location = `/api/quotes/${currentQuoteId}/download?fmt=pdf`;
};
$('#btnEditQuote').onclick = async () => {
  const q = await api(`/api/quotes/${currentQuoteId}`);
  fillForm(q);
  show('form');
};
$('#btnDeleteQuote').onclick = async () => {
  if (!confirm('Delete this quotation?')) return;
  await api(`/api/quotes/${currentQuoteId}`, { method: 'DELETE' });
  toast('Quotation deleted');
  await loadQuotes();
  show('quotes');
};

$('#btnEmail').onclick = async () => {
  const q = await api(`/api/quotes/${currentQuoteId}`);
  let suggested = '';
  if (q.client_id) {
    try {
      const client = await api(`/api/clients/${q.client_id}`);
      suggested = [client.email, client.email2].filter(Boolean).join(', ');
    } catch (_) { /* client may have been removed */ }
  }
  const to = prompt('Send the quotation to (comma separated e-mails):', suggested);
  if (!to) return;
  toast('Sending…');
  try {
    const res = await api(`/api/quotes/${currentQuoteId}/email`, {
      method: 'POST',
      body: JSON.stringify({ to, pdf: true }),
    });
    toast(`Sent to ${res.sent_to.join(', ')}`);
  } catch (err) {
    toast(err.message, true);
  }
};

/* ------------------------------------------------------------- the form */

function newQuote() {
  state.quote = null;
  state.clientId = null;
  state.items = [];
  $('#fHeading').value = state.headings[0] || 'QUOTATION';
  $('#fStdFile').value = state.stdFiles[0] || 'NON STD FILE';
  $('#fParty').value = '';
  $('#fPartyAddress').value = '';
  $('#fCity').value = '';
  $('#fWhatsapp').value = '';
  $('#fPartyEmail').value = '';
  $('#fCcClient').value = 'NO';
  $('#fPaymentStatus').value = 'PENDING';
  $('#fDispatchQty').value = 0;
  $('#fReminder').value = defaultReminder();
  $('#fFollow1').value = todayISO();
  $('#fRemarks1').value = '';
  $('#fAdvance').value = 0;
  $('#fGst').value = 18;
  $('#fOrderStatus').value = 'PENDING';
  $('#fDispatch').value = 'PENDING';
  $('#fTerms').value = state.defaultTerms;
  $('#btnPickParty .picker-label').textContent = 'Tap to choose a party';
  const preferred = state.companies.find((c) => c.name === state.defaultCompany);
  if (preferred) $('#fCompany').value = preferred.id;
  addItem();
  renderCompanyPreview();
  show('form');
}

function fillForm(q) {
  state.quote = q;
  state.clientId = q.client_id;
  $('#fCompany').value = q.company_id || '';
  $('#fSalesperson').value = q.salesperson || '';
  $('#fSalesPhone').value = q.salesperson_phone || '';
  $('#fParty').value = q.party_name || '';
  $('#fPartyAddress').value = q.party_address || '';
  $('#fHeading').value = q.heading || 'QUOTATION';
  $('#fStdFile').value = q.std_file || 'NON STD FILE';
  $('#fCity').value = q.city || '';
  $('#fWhatsapp').value = q.whatsapp_no || '';
  $('#fPartyEmail').value = q.party_email || '';
  $('#fCcClient').value = q.cc_to_client || 'NO';
  $('#fPaymentStatus').value = q.payment_status || 'PENDING';
  $('#fDispatchQty').value = q.dispatch_qty || 0;
  $('#fReminder').value = (q.reminder_date || '').slice(0, 10);
  $('#fFollow1').value = (q.followup1 || '').slice(0, 10);
  $('#fRemarks1').value = q.remarks1 || '';
  $('#fGst').value = q.gst_percent;
  $('#fAdvance').value = q.advance;
  $('#fOrderStatus').value = q.order_status || 'PENDING';
  $('#fDispatch').value = q.dispatch || 'PENDING';
  $('#fTerms').value = q.terms || state.defaultTerms;
  $('#btnPickParty .picker-label').textContent = q.party_name || 'Tap to choose a party';
  state.items = q.items.map((it) => ({
    model: it.model, description: it.description,
    qty: it.qty, rate: it.rate, gst_percent: it.gst_percent,
  }));
  renderItems();
  renderCompanyPreview();
}

function renderCompanyPreview() {
  const company = state.companies.find((c) => String(c.id) === $('#fCompany').value);
  $('#companyPreview').textContent = company
    ? [company.address, company.address2].filter(Boolean).join('\n')
    : '';
}

$('#fCompany').onchange = renderCompanyPreview;

$('#fSalesperson').onchange = () => {
  const person = state.salespersons.find((s) => s.name === $('#fSalesperson').value);
  if (person && person.phone) $('#fSalesPhone').value = person.phone;
};

/* --- party picker --- */

$('#btnPickParty').onclick = () => openSheet({
  placeholder: 'Search party, city, phone, GST…',
  search: (q) => api(`/api/clients?q=${encodeURIComponent(q)}&limit=50`),
  render: (c) => `<div class="t">${escapeHtml(c.party)}</div>
    <div class="s">${escapeHtml(c.city || '')} ${c.cell_no ? '· ' + escapeHtml(c.cell_no) : ''}
    ${c.gst_no ? '<br>GST ' + escapeHtml(c.gst_no) : ''}</div>`,
  onPick: (c) => applyClientToForm(c),
});

function applyClientToForm(c) {
  state.clientId = c.id;
  $('#fParty').value = c.party;
  $('#fPartyAddress').value = buildPartyAddress(c);
  $('#fCity').value = c.city || '';
  $('#fWhatsapp').value = c.cell_no || '';
  $('#fPartyEmail').value = c.email || '';
  $('#btnPickParty .picker-label').textContent = c.party;
}

function buildPartyAddress(c) {
  // Mirrors how the AppSheet template filled the ADD box: address lines, then
  // GST no, then the contact number.
  const parts = [c.address, c.address2].filter(Boolean);
  if (c.gst_no) parts.push(`GST NO:- ${c.gst_no}`);
  const phones = [c.cell_no, c.cell_no2].filter(Boolean).join(' / ');
  const joined = parts.join('\n');
  if (phones && !joined.includes(phones.split(' / ')[0])) parts.push(phones);
  return parts.join('\n');
}

$('#btnNewParty').onclick = async () => {
  const party = $('#fParty').value.trim();
  if (!party) return toast('Type the party name first', true);
  try {
    const client = await api('/api/clients', {
      method: 'POST',
      body: JSON.stringify({
        party,
        address: $('#fPartyAddress').value,
        entry_by: $('#fSalesperson').value,
      }),
    });
    state.clientId = client.id;
    toast(`${party} saved to the party database`);
  } catch (err) {
    toast(err.message, true);
  }
};

/* --- items --- */

function addItem(item) {
  state.items.push(item || { model: '', description: '', qty: 1, rate: 0,
                             gst_percent: Number($('#fGst').value) || 18 });
  renderItems();
}

function renderItems() {
  const list = $('#itemList');
  list.innerHTML = '';
  state.items.forEach((item, index) => {
    const el = document.createElement('div');
    el.className = 'item';
    el.innerHTML = `
      <div class="item-head">
        <span class="item-no">Item ${index + 1}</span>
        <button class="item-del" data-del="${index}" title="Remove">✕</button>
      </div>
      <button class="picker-btn" data-pick="${index}">
        <span class="picker-label">${item.description
          ? escapeHtml(item.description) : 'Tap to choose a machine / part'}</span>
        <span class="chev">›</span>
      </button>
      <label>Description
        <input type="text" data-f="description" data-i="${index}" value="${escapeAttr(item.description)}">
      </label>
      <label>Model code (prints under the description)
        <input type="text" data-f="model" data-i="${index}" value="${escapeAttr(item.model)}">
      </label>
      <div class="row-3">
        <label>Qty
          <input type="number" data-f="qty" data-i="${index}" value="${item.qty}" min="0" step="1" inputmode="decimal">
        </label>
        <label>GST %
          <input type="number" data-f="gst_percent" data-i="${index}" value="${item.gst_percent}" min="0" step="0.01" inputmode="decimal">
        </label>
        <label>Rate
          <input type="number" data-f="rate" data-i="${index}" value="${item.rate}" min="0" step="0.01" inputmode="decimal">
        </label>
      </div>
      <div class="line-amt">${money((Number(item.qty) || 0) * (Number(item.rate) || 0))}</div>`;
    list.appendChild(el);
  });

  list.querySelectorAll('[data-del]').forEach((btn) => {
    btn.onclick = () => {
      state.items.splice(Number(btn.dataset.del), 1);
      if (!state.items.length) addItem(); else renderItems();
      recalc();
    };
  });
  list.querySelectorAll('[data-pick]').forEach((btn) => {
    btn.onclick = () => pickMachine(Number(btn.dataset.pick));
  });
  list.querySelectorAll('[data-f]').forEach((input) => {
    input.oninput = () => {
      const item = state.items[Number(input.dataset.i)];
      const field = input.dataset.f;
      item[field] = ['qty', 'rate', 'gst_percent'].includes(field)
        ? Number(input.value) : input.value;
      const amt = input.closest('.item').querySelector('.line-amt');
      amt.textContent = money((Number(item.qty) || 0) * (Number(item.rate) || 0));
      recalc();
    };
  });
  recalc();
}

function pickMachine(index) {
  openSheet({
    placeholder: 'Search model or machine…',
    search: (q) => api(`/api/machines?q=${encodeURIComponent(q)}&limit=60`),
    render: (m) => `<div class="r">${money(m.rate)}</div>
      <div class="t">${escapeHtml(m.description || m.model)}</div>
      <div class="s">${escapeHtml(m.model)}</div>`,
    onPick: (m) => {
      const item = state.items[index];
      item.model = m.model;
      item.description = m.description || m.model;
      item.rate = m.rate;
      if (!item.qty) item.qty = 1;
      renderItems();
    },
  });
}

$('#btnAddItem').onclick = () => addItem();

function recalc() {
  const gstDefault = Number($('#fGst').value) || 0;
  let subtotal = 0;
  let gst = 0;
  state.items.forEach((item) => {
    if (!item.description && !item.model) return;
    const amount = (Number(item.qty) || 0) * (Number(item.rate) || 0);
    subtotal += amount;
    const rate = item.gst_percent === undefined || item.gst_percent === null
      ? gstDefault : Number(item.gst_percent);
    gst += amount * rate / 100;
  });
  const total = subtotal + gst;
  const balance = total - (Number($('#fAdvance').value) || 0);
  $('#tSub').textContent = money(subtotal);
  $('#tGst').textContent = money(gst);
  $('#tTotal').textContent = money(total);
  $('#tBalance').textContent = money(balance);
}

$('#fGst').oninput = () => {
  // Changing the header GST re-applies to every line that still carries the old
  // default, which is how the AppSheet form behaved.
  const value = Number($('#fGst').value) || 0;
  state.items.forEach((item) => { item.gst_percent = value; });
  renderItems();
};
$('#fAdvance').oninput = recalc;

/* --- save --- */

$('#btnSaveQuote').onclick = async () => {
  const payload = {
    company_id: Number($('#fCompany').value) || null,
    client_id: state.clientId,
    heading: $('#fHeading').value,
    std_file: $('#fStdFile').value,
    party_name: $('#fParty').value.trim(),
    party_address: $('#fPartyAddress').value,
    city: $('#fCity').value.trim(),
    whatsapp_no: $('#fWhatsapp').value.trim(),
    party_email: $('#fPartyEmail').value.trim(),
    cc_to_client: $('#fCcClient').value,
    salesperson: $('#fSalesperson').value,
    salesperson_phone: $('#fSalesPhone').value,
    order_status: $('#fOrderStatus').value,
    payment_status: $('#fPaymentStatus').value,
    dispatch: $('#fDispatch').value,
    dispatch_qty: Number($('#fDispatchQty').value) || 0,
    reminder_date: $('#fReminder').value,
    followup1: $('#fFollow1').value,
    remarks1: $('#fRemarks1').value,
    advance: Number($('#fAdvance').value) || 0,
    gst_percent: Number($('#fGst').value) || 0,
    terms: $('#fTerms').value,
    items: state.items,
  };
  if (!payload.party_name) return toast('Party name is required', true);
  if (!payload.items.some((i) => i.description || i.model)) {
    return toast('Add at least one item', true);
  }
  try {
    const saved = state.quote
      ? await api(`/api/quotes/${state.quote.id}`, { method: 'PUT', body: JSON.stringify(payload) })
      : await api('/api/quotes', { method: 'POST', body: JSON.stringify(payload) });
    toast(saved.synced ? 'Saved and added to the Order items sheet'
                       : 'Saved · ' + (saved.sync_message || 'not synced yet'),
          !saved.synced && state.sheet.configured);
    await loadQuotes();
    await openQuote(saved.id);
  } catch (err) {
    toast(err.message, true);
  }
};

$('#btnCancelQuote').onclick = async () => { await loadQuotes(); show('quotes'); };

$('#btnSaveTerms').onclick = async () => {
  await api('/api/settings', { method: 'PUT', body: JSON.stringify({ default_terms: $('#fTerms').value }) });
  state.defaultTerms = $('#fTerms').value;
  toast('Default terms updated');
};

/* ------------------------------------------------------------- clients */

async function loadClients(query = '') {
  const rows = await api(`/api/clients?q=${encodeURIComponent(query)}&limit=60`);
  const list = $('#clientList');
  list.innerHTML = '';
  rows.forEach((c) => {
    const card = document.createElement('button');
    card.className = 'card';
    card.innerHTML = `<div class="t">${escapeHtml(c.party)}</div>
      <div class="s">${escapeHtml(c.city || '')}${c.cell_no ? ' · ' + escapeHtml(c.cell_no) : ''}
      ${c.email ? '<br>' + escapeHtml(c.email) : ''}
      ${c.gst_no ? '<br>GST ' + escapeHtml(c.gst_no) : ''}</div>`;
    card.onclick = () => openPartyEditor(c);
    list.appendChild(card);
  });
}
$('#clientSearch').addEventListener('input', debounce((e) => loadClients(e.target.value)));



/* -------------------------------------------------------- party editor */

const PARTY_FIELDS = {
  pParty: 'party', pAddress: 'address', pCity: 'city', pGst: 'gst_no',
  pCell: 'cell_no', pCell2: 'cell_no2', pEmail: 'email', pEmail2: 'email2',
  pRemarks: 'remarks',
};

function openPartyEditor(client) {
  state.editingClient = client || null;
  $('#partyEditTitle').textContent = client ? client.party : 'New party';
  Object.entries(PARTY_FIELDS).forEach(([id, key]) => {
    $('#' + id).value = client ? (client[key] || '') : '';
  });
  $('#btnDeleteParty').hidden = !client;
  show('party-edit');
}

function partyPayload() {
  const data = {};
  Object.entries(PARTY_FIELDS).forEach(([id, key]) => {
    data[key] = $('#' + id).value.trim();
  });
  data.entry_by = $('#fSalesperson').value || '';
  return data;
}

async function saveParty() {
  const data = partyPayload();
  if (!data.party) { toast('Party name is required', true); return null; }
  const saved = state.editingClient
    ? await api(`/api/clients/${state.editingClient.id}`,
                { method: 'PUT', body: JSON.stringify(data) })
    : await api('/api/clients', { method: 'POST', body: JSON.stringify(data) });
  state.editingClient = saved;
  return saved;
}

$('#btnAddParty').onclick = () => openPartyEditor(null);

$('#btnSaveParty').onclick = async () => {
  try {
    const saved = await saveParty();
    if (!saved) return;
    toast(`${saved.party} saved`);
    await loadClients($('#clientSearch').value);
    show('clients');
  } catch (err) { toast(err.message, true); }
};

$('#btnPartyQuote').onclick = async () => {
  try {
    const saved = await saveParty();
    if (!saved) return;
    newQuote();
    applyClientToForm(saved);
    toast(`New quotation for ${saved.party}`);
  } catch (err) { toast(err.message, true); }
};

$('#btnCancelParty').onclick = () => show('clients');

$('#btnDeleteParty').onclick = async () => {
  if (!state.editingClient) return;
  if (!confirm(`Remove ${state.editingClient.party} from the party list?`)) return;
  await api(`/api/clients/${state.editingClient.id}`, { method: 'DELETE' });
  toast('Party removed');
  await loadClients($('#clientSearch').value);
  show('clients');
};

/* ------------------------------------------------------ machine editor */

function openMachineEditor(machine) {
  state.editingMachine = machine || null;
  $('#machineEditTitle').textContent = machine ? machine.model : 'New machine';
  $('#mModel').value = machine ? machine.model : '';
  $('#mDesc').value = machine ? machine.description : '';
  $('#mRate').value = machine ? machine.rate : 0;
  $('#btnHideMachine').hidden = !machine;
  show('machine-edit');
}

$('#btnAddMachine').onclick = () => openMachineEditor(null);
$('#btnCancelMachine').onclick = () => show('machines');

$('#btnSaveMachine').onclick = async () => {
  const data = {
    model: $('#mModel').value.trim(),
    description: $('#mDesc').value.trim(),
    rate: Number($('#mRate').value) || 0,
    entry_by: $('#fSalesperson').value || '',
  };
  if (!data.model) return toast('Model code is required', true);
  try {
    if (state.editingMachine) {
      await api(`/api/machines/${state.editingMachine.id}`,
                { method: 'PUT', body: JSON.stringify(data) });
    } else {
      await api('/api/machines', { method: 'POST', body: JSON.stringify(data) });
    }
    toast(`${data.model} saved`);
    await loadMachines($('#machineSearch').value);
    show('machines');
  } catch (err) { toast(err.message, true); }
};

$('#btnHideMachine').onclick = async () => {
  if (!state.editingMachine) return;
  if (!confirm(`Hide ${state.editingMachine.model} from the item picker?`)) return;
  await api(`/api/machines/${state.editingMachine.id}`, { method: 'DELETE' });
  toast('Hidden from the picker');
  await loadMachines($('#machineSearch').value);
  show('machines');
};

/* ------------------------------------------------------------ machines */

async function loadMachines(query = '') {
  const rows = await api(`/api/machines?q=${encodeURIComponent(query)}&limit=60`);
  const list = $('#machineList');
  list.innerHTML = '';
  rows.forEach((m) => {
    const card = document.createElement('button');
    card.className = 'card';
    card.innerHTML = `<span class="amt">${money(m.rate)}</span>
      <div class="t">${escapeHtml(m.description || m.model)}</div>
      <div class="s">${escapeHtml(m.model)}${m.entry_by ? ' · ' + escapeHtml(m.entry_by) : ''}</div>`;
    card.onclick = () => openMachineEditor(m);
    list.appendChild(card);
  });
}
$('#machineSearch').addEventListener('input', debounce((e) => loadMachines(e.target.value)));

/* ------------------------------------------------------------ settings */

function paintSheetStatus() {
  const el = $('#sheetStatus');
  if (state.sheet.configured) {
    el.textContent = state.sheet.pending
      ? `Connected · ${state.sheet.pending} quotation(s) still waiting to be sent.`
      : 'Connected · every saved quotation goes straight into the sheet.';
  } else {
    el.textContent = 'Not connected yet. Quotations are still recorded in '
      + 'instance/order_items.csv until you connect the sheet.';
  }
}

async function refreshSettings() {
  const s = await api('/api/settings');
  state.defaultTerms = s.default_terms || '';
  state.defaultCompany = s.default_company || '';
  state.mailConfigured = s.mail_configured;
  state.headings = s.headings || state.headings;
  state.stdFiles = s.std_files || state.stdFiles;
  state.sheet = {
    url: s.sheet_url || '', secret: s.sheet_secret || '',
    configured: s.sheet_configured, pending: s.pending_sync || 0,
  };
  return s;
}

async function loadSettings() {
  await refreshSettings();
  $('#sSheetUrl').value = state.sheet.url;
  $('#sSheetSecret').value = state.sheet.secret;
  paintSheetStatus();
  $('#sTerms').value = state.defaultTerms;
  $('#mailStatus').textContent = state.mailConfigured
    ? '✅ E-mail is configured — the ✉ button on a quotation will send it.'
    : '⚠️ E-mail is not configured yet. Downloads still work.';

  const list = $('#salesList');
  list.innerHTML = '';
  state.salespersons.forEach((person) => {
    const row = document.createElement('div');
    row.className = 'row-2';
    row.innerHTML = `<label>${escapeHtml(person.name)}
        <input type="text" value="${escapeAttr(person.phone || '')}" placeholder="Phone" data-sp="${person.id}">
      </label>
      <label>E-mail
        <input type="text" value="${escapeAttr(person.email || '')}" placeholder="E-mail" data-spm="${person.id}">
      </label>`;
    list.appendChild(row);
  });
  list.querySelectorAll('[data-sp],[data-spm]').forEach((input) => {
    input.onchange = async () => {
      const id = Number(input.dataset.sp || input.dataset.spm);
      const phone = list.querySelector(`[data-sp="${id}"]`).value;
      const email = list.querySelector(`[data-spm="${id}"]`).value;
      await api(`/api/salespersons/${id}`, { method: 'PUT', body: JSON.stringify({ phone, email }) });
      const person = state.salespersons.find((s) => s.id === id);
      if (person) { person.phone = phone; person.email = email; }
      toast('Saved');
    };
  });

  const defaultSelect = $('#sDefaultCompany');
  defaultSelect.innerHTML = state.companies
    .map((c) => `<option value="${escapeAttr(c.name)}">${escapeHtml(c.name)}</option>`).join('');
  defaultSelect.value = state.defaultCompany;
  defaultSelect.onchange = async () => {
    await api('/api/settings', {
      method: 'PUT', body: JSON.stringify({ default_company: defaultSelect.value }),
    });
    state.defaultCompany = defaultSelect.value;
    toast('Default company saved');
  };

  const companies = $('#companyList');
  companies.innerHTML = '';
  state.companies.forEach((c) => {
    const div = document.createElement('div');
    div.className = 'block';
    div.innerHTML = `<h2>${escapeHtml(c.name)}</h2>
      <p class="hint">${escapeHtml(c.address || '').replace(/\n/g, '<br>')}</p>
      <label>Contact strip printed under the bank box
        <input type="text" data-cl="${c.id}" value="${escapeAttr(c.contact_line || '')}">
      </label>
      <label>Bank details
        <textarea rows="4" data-bd="${c.id}">${escapeHtml(c.bank_details || '')}</textarea>
      </label>`;
    companies.appendChild(div);
  });
  companies.querySelectorAll('[data-cl],[data-bd]').forEach((input) => {
    input.onchange = async () => {
      const id = Number(input.dataset.cl || input.dataset.bd);
      const updated = await api(`/api/companies/${id}`, {
        method: 'PUT',
        body: JSON.stringify({
          contact_line: companies.querySelector(`[data-cl="${id}"]`).value,
          bank_details: companies.querySelector(`[data-bd="${id}"]`).value,
        }),
      });
      const company = state.companies.find((c) => c.id === id);
      if (company) Object.assign(company, updated);
      toast('Company saved');
    };
  });
}

$('#btnSettingsSave').onclick = async () => {
  await api('/api/settings', { method: 'PUT', body: JSON.stringify({ default_terms: $('#sTerms').value }) });
  state.defaultTerms = $('#sTerms').value;
  toast('Default terms saved');
};


$('#btnSheetTest').onclick = async (e) => {
  const btn = e.currentTarget;
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Testing…';
  try {
    const res = await api('/api/sheet/test', {
      method: 'POST',
      body: JSON.stringify({
        sheet_webapp_url: $('#sSheetUrl').value.trim(),
        sheet_secret: $('#sSheetSecret').value.trim(),
      }),
    });
    toast(res.message);
    await refreshSettings();
    paintSheetStatus();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
};

$('#btnSyncPending').onclick = async (e) => {
  const btn = e.currentTarget;
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Sending…';
  try {
    const res = await api('/api/sync-pending', { method: 'POST' });
    toast(res.failed
      ? `${res.synced} sent, ${res.failed} failed · ${res.error}`
      : `${res.synced} quotation(s) added to the sheet`, Boolean(res.failed));
    await refreshSettings();
    paintSheetStatus();
    await loadQuotes();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
};

$('#btnMirror').onclick = () => { window.location = '/api/order-items.csv'; };

$('#btnAddSales').onclick = async () => {
  const name = $('#newSalesName').value.trim();
  if (!name) return toast('Enter a name', true);
  await api('/api/salespersons', {
    method: 'POST',
    body: JSON.stringify({ name, phone: $('#newSalesPhone').value.trim() }),
  });
  $('#newSalesName').value = '';
  $('#newSalesPhone').value = '';
  await bootstrapLists();
  await loadSettings();
  toast('Salesperson added');
};

/* ----------------------------------------------------------- utilities */

function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

// The AppSheet rows carried a reminder about a week out; keep that habit.
function defaultReminder(days = 6) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function fillPickLists() {
  $('#fHeading').innerHTML = state.headings
    .map((h) => `<option value="${escapeAttr(h)}">${escapeHtml(h)}</option>`).join('');
  $('#fStdFile').innerHTML = state.stdFiles
    .map((f) => `<option value="${escapeAttr(f)}">${escapeHtml(f)}</option>`).join('');
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}
const escapeAttr = escapeHtml;

/* --------------------------------------------------------------- boot */

async function bootstrapLists() {
  const [companies, salespersons] = await Promise.all([
    api('/api/companies'), api('/api/salespersons'),
  ]);
  state.companies = companies;
  state.salespersons = salespersons;

  const companySelect = $('#fCompany');
  companySelect.innerHTML = companies
    .map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
  const preferred = companies.find((c) => c.name === state.defaultCompany);
  if (preferred) companySelect.value = preferred.id;

  const salesSelect = $('#fSalesperson');
  salesSelect.innerHTML = '<option value=""></option>' + salespersons
    .map((s) => `<option value="${escapeAttr(s.name)}">${escapeHtml(s.name)}</option>`).join('');
}

(async function boot() {
  try {
    await refreshSettings();
    fillPickLists();
    await bootstrapLists();
    await loadQuotes();
    show('quotes');
  } catch (err) {
    toast(err.message, true);
  }
})();
