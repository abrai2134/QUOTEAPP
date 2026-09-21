/**
 * Runs the Apps Script files against stub Google services.
 *
 * The routing inside doGet and doPost is real code with real branches, and a
 * branch placed after a catch-all is simply never reached - which is what
 * happened to the records action.  Stubbing the whole web app in the Python
 * tests could not catch that; running these files can.
 *
 *   node google-apps-script/test/run.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function sheet(name, headers, rows) {
  const grid = [headers.slice(), ...rows.map((r) => r.slice())];
  return {
    getName: () => name,
    getLastRow: () => grid.length,
    getLastColumn: () => headers.length,
    appendRow: (values) => grid.push(values.slice()),
    getRange(row, col, numRows, numCols) {
      return {
        getValues: () => grid.slice(row - 1, row - 1 + numRows)
                             .map((r) => r.slice(col - 1, col - 1 + numCols)),
        setValues: (values) => {
          values.forEach((line, i) => {
            line.forEach((v, j) => { grid[row - 1 + i][col - 1 + j] = v; });
          });
        },
      };
    },
    _grid: grid,
  };
}

function load(tabs) {
  const book = {
    getName: () => 'Order items',
    getSheets: () => Object.values(tabs),
    getSheetByName: (n) => tabs[n] || null,
    getSpreadsheetTimeZone: () => 'Asia/Calcutta',
  };
  const sandbox = {
    SpreadsheetApp: { getActiveSpreadsheet: () => book },
    ContentService: {
      MimeType: { JSON: 'json' },
      createTextOutput: (text) => ({ setMimeType: () => ({ text }) }),
    },
    console,
  };
  vm.createContext(sandbox);
  const dir = path.join(__dirname, '..', 'split');
  fs.readdirSync(dir).filter((f) => f.endsWith('.gs')).sort().forEach((f) => {
    vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), sandbox, { filename: f });
  });
  return { sandbox, tabs, book };
}

const out = (res) => JSON.parse(res.text);
let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`}`);
}

const partyRows = [];
for (let i = 1; i <= 950; i++) partyRows.push([`PARTY ${i}`, `CITY ${i}`, '']);
partyRows.push(['ZAYEN PT LLP', 'RAJKOT', '88660 79022']);

function fresh() {
  return load({
    'Order items': sheet('Order items', ['ID', 'HEADING ', 'PARTY'], [['a1', 'QUOTATION', 'OLD CO']]),
    Party: sheet('Party', ['PARTY', 'CITY', 'CELL NO'], partyRows),
    Machines: sheet('Machines', ['MODEL1', 'MACHINE1', 'RATE1'], [['FT~24BK', 'FILING TABLE', 44500]]),
  });
}

// --- the health check still answers -------------------------------------
let env = fresh();
let health = out(env.sandbox.doGet({ parameter: {} }));
check('health check reports the file', health.file, 'Order items');
check('health check advertises records', health.canRecords, true);

// --- action=records must reach readRecords, not the health check ---------
let res = out(env.sandbox.doGet({ parameter: { action: 'records', tab: 'Party', limit: '3', back: '0' } }));
check('records returns rows, not the health check', Array.isArray(res.rows), true);
check('records reports the tab total', res.total, 951);
check('newest row comes back first page', res.rows[res.rows.length - 1].PARTY, 'ZAYEN PT LLP');
check('page is the size asked for', res.rows.length, 3);

// --- paging backwards covers the tab ------------------------------------
let back = 0, seen = 0, pages = 0;
while (pages < 20) {
  const page = out(env.sandbox.doGet({ parameter: { action: 'records', tab: 'Party', limit: '300', back: String(back) } }));
  seen += page.rows.length;
  back = page.covered;
  pages++;
  if (page.done) break;
}
check('paging backwards reads every row', seen, 951);

// --- action=rows still works --------------------------------------------
res = out(env.sandbox.doGet({ parameter: { action: 'rows', limit: '10' } }));
check('rows action still returns quotations', res.rows.length, 1);

// --- a missing tab is named ---------------------------------------------
res = out(env.sandbox.doGet({ parameter: { action: 'records', tab: 'Nope' } }));
check('unknown tab is refused', res.ok, false);

// --- doPost: a quotation row --------------------------------------------
env = fresh();
res = out(env.sandbox.doPost({ postData: { contents: JSON.stringify({ row: { ID: 'zz', 'HEADING ': 'QUOTATION', PARTY: 'NEW CO' } }) } }));
check('quotation row is appended', res.row, 3);
check('quotation reports doPost', res.via, 'doPost');

// --- doPost: the dry run writes nothing ---------------------------------
env = fresh();
const before = env.tabs['Order items']._grid.length;
res = out(env.sandbox.doPost({ postData: { contents: JSON.stringify({ test: true, row: {} }) } }));
check('dry run answers', res.test, true);
check('dry run writes nothing', env.tabs['Order items']._grid.length, before);

// --- doPost: a party is appended, then updated in place -----------------
env = fresh();
const rec = (values) => ({ record: { tab: 'Party', key: 'PARTY', match: values.PARTY, values } });
res = out(env.sandbox.doPost({ postData: { contents: JSON.stringify(rec({ PARTY: 'BRAND NEW', CITY: 'SURAT' })) } }));
check('new party is added', res.added, true);
res = out(env.sandbox.doPost({ postData: { contents: JSON.stringify(rec({ PARTY: 'BRAND NEW', CITY: 'RAJKOT' })) } }));
check('same party updates, not duplicates', res.added, false);
const grid = env.tabs.Party._grid;
check('only one BRAND NEW row', grid.filter((r) => r[0] === 'BRAND NEW').length, 1);
check('the update took', grid.find((r) => r[0] === 'BRAND NEW')[1], 'RAJKOT');

// --- doPost: a column the app does not know is left alone ---------------
env = load({
  'Order items': sheet('Order items', ['ID'], []),
  Party: sheet('Party', ['PARTY', 'CITY', 'MY OWN NOTE'], [['KEEPER', 'PUNE', 'do not touch']]),
});
env.sandbox.doPost({ postData: { contents: JSON.stringify(rec({ PARTY: 'KEEPER', CITY: 'NASIK' })) } });
check('hand-kept column survives an update', env.tabs.Party._grid[1][2], 'do not touch');

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
