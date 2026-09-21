/**
 * Well Worth Quote App -> Order items sheet.  Part 2 of 6.
 *
 * Split across six small files only so each one pastes into the editor in a
 * single go; Apps Script runs them together as one project.
 */

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
