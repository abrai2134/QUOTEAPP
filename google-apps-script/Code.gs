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

// The tab the rows are appended to.
var SHEET_NAME = 'Order items';

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);

    if (SHARED_SECRET && payload.secret !== SHARED_SECRET) {
      return reply({ ok: false, error: 'Wrong secret word.' });
    }

    var book = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = book.getSheetByName(SHEET_NAME);
    if (!sheet) {
      return reply({ ok: false, error: 'No sheet named "' + SHEET_NAME + '" in this file.' });
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
    return reply({ ok: true, row: sheet.getLastRow(), id: row.ID || '' });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  }
}

function doGet() {
  // Opening the URL in a browser confirms the deployment is live.
  return reply({ ok: true, message: 'Well Worth quote sync is running.' });
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
