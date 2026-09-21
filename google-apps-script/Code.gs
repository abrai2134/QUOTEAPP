/**
 * Well Worth Quote App -> Order items sheet
 *
 * Paste this into the Apps Script editor of the spreadsheet that holds your
 * "Order items" sheet, deploy it as a Web app, and paste the deployment URL
 * into the quotation app under Setup.  Every quotation you save is then
 * appended as a row, in the same columns AppSheet used.
 *
 * Setup instructions are in README.md next to this file.
 */

// Leave blank to accept any request, or set a word of your own and put the
// same word into the app under Setup.
var SHARED_SECRET = '';

// The tab the rows are appended to.  If your tab has another name, either
// change it here or just leave it - when the file has only one tab, that one
// is used, and any other mismatch reports the tab names it did find.
var SHEET_NAME = 'Order items';

/** Find the tab to work on, and say what is there when it cannot be found. */
function pickSheet(book) {
  var sheet = book.getSheetByName(SHEET_NAME);
  if (sheet) return sheet;

  var sheets = book.getSheets();
  if (sheets.length === 1) return sheets[0];

  var names = sheets.map(function (s) { return '"' + s.getName() + '"'; }).join(', ');
  throw new Error('No tab named "' + SHEET_NAME + '". This file has: ' + names +
                  '. Rename the tab, or change SHEET_NAME at the top of the script.');
}

/** A tab by name, saying what is there when it cannot be found. */
function tabNamed(book, name) {
  var sheet = book.getSheetByName(name);
  if (sheet) return sheet;
  var names = book.getSheets().map(function (s) { return '"' + s.getName() + '"'; });
  throw new Error('No tab named "' + name + '". This file has: ' + names.join(', '));
}

/**
 * Write one record into a tab, matched on that tab's own header row.
 *
 * A row whose key column already holds this value is updated in place, and
 * only the fields sent are touched - anything else on that row, and any column
 * the app does not know about, is left exactly as it was.  Otherwise the
 * record is appended.
 */
function upsertRecord(record) {
  var book = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = tabNamed(book, record.tab);
  var lastCol = sheet.getLastColumn();
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(String);

  var values = record.values || {};
  var lookup = {};
  Object.keys(values).forEach(function (k) { lookup[norm(k)] = values[k]; });

  var keyCol = -1;
  for (var i = 0; i < headers.length; i++) {
    if (norm(headers[i]) === norm(record.key)) { keyCol = i; break; }
  }
  if (keyCol < 0) {
    throw new Error('The "' + record.tab + '" tab has no "' + record.key +
                    '" column. It has: ' + headers.join(', '));
  }

  var target = 0;
  var wanted = norm(record.match);
  var lastRow = sheet.getLastRow();
  if (wanted && lastRow > 1) {
    var column = sheet.getRange(2, keyCol + 1, lastRow - 1, 1).getValues();
    for (var r = 0; r < column.length; r++) {
      if (norm(column[r][0]) === wanted) { target = r + 2; break; }
    }
  }

  if (!target) {
    var fresh = headers.map(function (header) {
      var v = lookup[norm(header)];
      return (v === undefined || v === null) ? '' : v;
    });
    sheet.appendRow(fresh);
    return reply({ ok: true, via: 'doPost', tab: sheet.getName(),
                   row: sheet.getLastRow(), added: true });
  }

  var existing = sheet.getRange(target, 1, 1, lastCol).getValues()[0];
  headers.forEach(function (header, i) {
    var v = lookup[norm(header)];
    if (v !== undefined && v !== null) existing[i] = v;
  });
  sheet.getRange(target, 1, 1, lastCol).setValues([existing]);
  return reply({ ok: true, via: 'doPost', tab: sheet.getName(),
                 row: target, added: false });
}

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);

    if (SHARED_SECRET && payload.secret !== SHARED_SECRET) {
      return reply({ ok: false, error: 'Wrong secret word.' });
    }

    // Parties and machines go to their own tabs, not the Order items row.
    if (payload.record) {
      if (payload.test) {
        return reply({ ok: true, via: 'doPost', test: true,
                       tab: tabNamed(SpreadsheetApp.getActiveSpreadsheet(),
                                     payload.record.tab).getName() });
      }
      return upsertRecord(payload.record);
    }

    var sheet = pickSheet(SpreadsheetApp.getActiveSpreadsheet());

    // "Test the connection" sends a row with test:true. Everything above has
    // run - the URL, the deployment, the secret and the tab are all good - so
    // answer and write nothing.
    if (payload.test) {
      return reply({ ok: true, via: 'doPost', test: true,
                     tab: sheet.getName(),
                     timezone: SpreadsheetApp.getActiveSpreadsheet()
                                             .getSpreadsheetTimeZone() });
    }

    // Match on the sheet's own header row, so the app never depends on column
    // order and extra columns you add by hand are left untouched.
    var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn())
                       .getValues()[0].map(String);
    var row = payload.row || {};
    var lookup = {};
    Object.keys(row).forEach(function (key) { lookup[norm(key)] = row[key]; });

    var values = headers.map(function (header) {
      var value = lookup[norm(header)];
      if (value === undefined || value === null) return '';
      if (isIsoDate(value)) return new Date(value);
      return value;
    });

    sheet.appendRow(values);
    return reply({ ok: true, via: 'doPost', row: sheet.getLastRow(), id: row.ID || '' });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

/**
 * doGet serves two things:
 *   ?action=rows&limit=500   the most recent rows, so the app can rebuild its
 *                            list after a restart and pick up quotations
 *                            raised by the rest of the team
 *   anything else            a health check you can open in a browser
 */
function doGet(e) {
  try {
    var params = (e && e.parameter) || {};
    if (params.action !== 'rows') {
      var book = SpreadsheetApp.getActiveSpreadsheet();
      return reply({
        ok: true,
        message: 'Well Worth quote sync is running.',
        file: book.getName(),
        tabs: book.getSheets().map(function (s) { return s.getName(); }),
        // Dates are written and read in this timezone.  If it is not India,
        // every quotation lands in the sheet at the wrong time of day, so the
        // app checks it and says so.
        timezone: book.getSpreadsheetTimeZone(),
        // Tells the app this copy understands a test row and will not write
        // it.  Without this it never sends one, so an older copy of the
        // script can never be tricked into appending a blank row.
        canTest: true,
        // This copy also writes parties and machines to their own tabs.
        canRecords: true,
      });
    }
    if (SHARED_SECRET && params.secret !== SHARED_SECRET) {
      return reply({ ok: false, error: 'Wrong secret word.' });
    }

    // Rows from the Party or Machines tab, a page at a time, so the app can
    // pick up records added in the sheet or by AppSheet.
    if (params.action === 'records') {
      return readRecords(SpreadsheetApp.getActiveSpreadsheet(), params);
    }

    var sheet = pickSheet(SpreadsheetApp.getActiveSpreadsheet());

    var lastRow = sheet.getLastRow();
    var lastCol = sheet.getLastColumn();
    if (lastRow < 2) return reply({ ok: true, rows: [] });

    var limit = Math.min(Number(params.limit) || 500, 2000);
    var start = Math.max(2, lastRow - limit + 1);
    var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
    var values = sheet.getRange(start, 1, lastRow - start + 1, lastCol).getValues();

    var rows = values.map(function (line) {
      var row = {};
      headers.forEach(function (header, i) {
        var value = line[i];
        // Dates go back as ISO text so any client can read them.
        row[header] = (value instanceof Date) ? value.toISOString() : value;
      });
      return row;
    });
    return reply({ ok: true, rows: rows, total: lastRow - 1 });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

/** A page of rows from a named tab, as objects keyed by its header row. */
function readRecords(book, params) {
  var sheet = tabNamed(book, params.tab);
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  var total = Math.max(0, lastRow - 1);
  var offset = Math.max(0, Number(params.offset) || 0);
  var limit = Math.min(Number(params.limit) || 1000, 5000);
  if (total === 0 || offset >= total) {
    return reply({ ok: true, rows: [], total: total, offset: offset });
  }

  var start = 2 + offset;
  var count = Math.min(limit, lastRow - start + 1);

  // "back" pages from the bottom instead: back=0 is the newest page, back=300
  // the 300 rows before that.  New records are appended at the end, so this is
  // where the app looks first.
  if (params.back !== undefined && params.back !== '') {
    var back = Math.max(0, Number(params.back) || 0);
    var endRow = lastRow - back;
    if (endRow < 2) {
      return reply({ ok: true, rows: [], total: total,
                     back: back, covered: total, done: true });
    }
    start = Math.max(2, endRow - limit + 1);
    count = endRow - start + 1;
  }
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
  var values = sheet.getRange(start, 1, count, lastCol).getValues();

  var rows = values.map(function (line) {
    var row = {};
    headers.forEach(function (header, i) {
      var value = line[i];
      row[header] = (value instanceof Date) ? value.toISOString() : value;
    });
    return row;
  });
  var covered = (params.back !== undefined && params.back !== '')
    ? (lastRow - start + 1)
    : (offset + count);
  return reply({ ok: true, rows: rows, total: total, limit: limit,
                 offset: offset, covered: covered,
                 done: covered >= total });
}

/** Headers are compared without case, spaces or punctuation. */
function norm(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9]/g, '');
}

function isIsoDate(value) {
  return typeof value === 'string' &&
         /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value);
}

function reply(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
                       .setMimeType(ContentService.MimeType.JSON);
}
