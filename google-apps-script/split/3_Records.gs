/**
 * Well Worth Quote App -> Order items sheet.  Part 3 of 6.
 *
 * Split across six small files only so each one pastes into the editor in a
 * single go; Apps Script runs them together as one project.
 */

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
