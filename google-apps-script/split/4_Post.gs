/**
 * Well Worth Quote App -> Order items sheet.  Part 4 of 6.
 *
 * Split across six small files only so each one pastes into the editor in a
 * single go; Apps Script runs them together as one project.
 */

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
