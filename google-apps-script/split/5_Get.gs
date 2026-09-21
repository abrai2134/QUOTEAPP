/**
 * Well Worth Quote App -> Order items sheet.  Part 5 of 6.
 *
 * Split across six small files only so each one pastes into the editor in a
 * single go; Apps Script runs them together as one project.
 */

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
    var action = params.action || '';

    // Anything that is not asking for data gets the health check.  Both data
    // actions have to be named here: leaving one out sends it the health
    // check instead, and the code meant to answer it never runs.
    if (action !== 'rows' && action !== 'records') {
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
    if (action === 'records') {
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
