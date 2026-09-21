/**
 * Well Worth Quote App -> Order items sheet.  Part 1 of 6.
 *
 * Split across six small files only so each one pastes into the editor in a
 * single go; Apps Script runs them together as one project.
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
