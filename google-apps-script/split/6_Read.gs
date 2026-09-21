/**
 * Well Worth Quote App -> Order items sheet.  Part 6 of 6.
 *
 * Split across six small files only so each one pastes into the editor in a
 * single go; Apps Script runs them together as one project.
 */

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
