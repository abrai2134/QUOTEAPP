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

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);

    if (SHARED_SECRET && payload.secret !== SHARED_SECRET) {
      return reply({ ok: false, error: 'Wrong secret word.' });
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
      });
    }
    if (SHARED_SECRET && params.secret !== SHARED_SECRET) {
      return reply({ ok: false, error: 'Wrong secret word.' });
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
