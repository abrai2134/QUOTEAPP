"""A4 print view of a quotation.

Renders the same layout as the .xlsx as a plain HTML page sized for A4, so a
quotation can be turned into a PDF straight from the browser (Print > Save as
PDF) on a phone or a desktop, with no LibreOffice installed.
"""

from html import escape

CSS = """
@page { size: A4 portrait; margin: 10mm; }
* { box-sizing: border-box; }
body {
  font-family: Cambria, "Times New Roman", serif; font-size: 10pt;
  color: #000; margin: 0; background: #f1f3f7;
}
.sheet {
  width: 190mm; min-height: 277mm; margin: 8mm auto; padding: 6mm;
  background: #fff; box-shadow: 0 2px 12px rgba(0,0,0,.18);
}
.title {
  background: #000; color: #fff; font-family: "Times New Roman", serif;
  font-size: 12pt; font-weight: bold; text-align: center; padding: 3px;
}
.datebar { display: flex; gap: 10px; font-size: 10pt; padding: 3px 0; }
.datebar b { font-weight: bold; }
.firm { font-family: "Times New Roman", serif; font-size: 24pt; font-weight: bold; text-align: center; }
.firm-add {
  font-family: Arial, sans-serif; font-size: 8pt; text-align: center;
  white-space: pre-line; line-height: 1.35; margin-bottom: 4px;
}
.party { display: flex; gap: 6px; margin: 2px 0; }
.party .lbl { font-weight: bold; width: 34px; flex: none; }
.party .val { flex: 1; text-align: center; font-size: 14pt; }
.party .val.add { font-size: 9pt; white-space: pre-line; line-height: 1.35; }
.status { margin: 4px 0; }
.status div { display: flex; font-weight: bold; }
.status .lbl { width: 45%; text-align: right; padding-right: 8px; }
table { width: 100%; border-collapse: collapse; }
table.items th, table.items td { border: 1px solid #000; padding: 2px 4px; }
table.items th { font-weight: bold; text-align: center; }
table.items td.c { text-align: center; }
table.items .model { font-weight: bold; }
table.items tr.spacer td { height: 12px; border-top: 0; border-bottom: 0; }
.footer-grid { display: flex; border: 1px solid #000; border-top: 0; }
.footer-left { width: 62%; border-right: 1px solid #000; }
.footer-right { width: 38%; }
.terms-head { background: #f00; color: #fff; font-weight: bold; padding: 2px 4px; }
.terms-body {
  background: #000; color: #fff; font-weight: bold; white-space: pre-line;
  padding: 4px; font-size: 9.5pt; line-height: 1.35; min-height: 26mm;
}
.bank-head { background: #00f; color: #fff; font-weight: bold; padding: 2px 4px; text-align: center; }
.bank-body { font-size: 8pt; font-weight: bold; white-space: pre-line; padding: 4px; line-height: 1.35; }
.totrow { display: flex; border-bottom: 1px solid #000; }
.totrow span { width: 45%; text-align: center; padding: 2px; border-right: 1px solid #000; }
.totrow b { width: 55%; text-align: center; padding: 2px; }
.contact { font-weight: bold; text-align: center; padding: 4px 0; }
.notes { display: flex; margin-top: 2px; }
.notes ol { margin: 0; padding-left: 16px; width: 62%; font-size: 9.5pt; line-height: 1.5; }
.sign { width: 38%; text-align: center; font-weight: bold; }
.decl { font-size: 9pt; line-height: 1.45; margin-top: 8px; display: flex; }
.decl p { margin: 0; width: 62%; }
.decl .sig { width: 38%; align-self: flex-end; }
.toolbar {
  position: sticky; top: 0; background: #0f2d52; color: #fff; padding: 10px;
  text-align: center; font-family: system-ui, sans-serif; font-size: 14px;
}
.toolbar button {
  background: #fff; color: #0f2d52; border: 0; border-radius: 7px;
  padding: 8px 18px; font-weight: 700; font-size: 14px; margin-left: 8px; cursor: pointer;
}
@media print {
  body { background: #fff; }
  .toolbar { display: none; }
  .sheet { margin: 0; box-shadow: none; width: auto; padding: 0; }
}
"""

NOTES = [
    "Goods Once sold will not be taken back",
    "Our responsibility ceases once the goods leave our godown",
    "Payment by crossed cheque is requested",
    "Subject to Mumbai jurisdiction (s) E. &amp; O.E",
]

DECLARATION = (
    "I / We hereby certify that my / our registration certificate under the GST is in force "
    "on the date on which the sale of the goods specified in this tax invoice is made by me / us "
    "and that the transaction of the sale covered by this tax invoice has been effected by me / us "
    "and it shall be accounted for in the turnover of sales while filing of return and the due tax, "
    "if any, payable on the sale has been paid or shall be paid"
)

MIN_ROWS = 7


def rupees(value):
    return "₹" + f"{float(value or 0):,.2f}"


def render(quote):
    company = quote.get("company") or {}
    items = quote.get("items") or []

    rows = []
    for index, item in enumerate(items, start=1):
        rows.append(
            f"<tr><td class='c'>{index}</td>"
            f"<td>{escape(item.get('description') or '')}"
            f"<div class='model'>{escape(item.get('model') or '')}</div></td>"
            f"<td class='c'>{float(item.get('gst_percent') or 0):.2f}%</td>"
            f"<td class='c'>{float(item.get('qty') or 0):g}</td>"
            f"<td class='c'>{float(item.get('rate') or 0):,.2f}</td>"
            f"<td class='c'>{rupees(item.get('amount'))}</td></tr>")
    for _ in range(max(0, MIN_ROWS - len(items))):
        rows.append("<tr class='spacer'><td></td><td></td><td></td>"
                    "<td></td><td></td><td></td></tr>")

    notes = "".join(f"<li>{note}</li>" for note in NOTES)
    address_block = "\n".join(
        x for x in [company.get("address", ""), company.get("address2", "")] if x)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(quote.get('party_name') or 'Quotation')}</title>
<style>{CSS}</style></head><body>
<div class="toolbar">Use your browser's Print dialog and choose <b>Save as PDF</b>
  <button onclick="window.print()">Print / Save PDF</button></div>
<div class="sheet">
  <div class="title">QUOTATION</div>
  <div class="datebar">
    <span>DATE:-</span><b>{escape(str(quote.get('quote_date') or '')[:16])}</b>
    <span style="margin-left:auto">Prepared by</span>
    <b>{escape(quote.get('salesperson') or '')} {escape(quote.get('salesperson_phone') or '')}</b>
  </div>
  <div class="firm">{escape(company.get('name', ''))}</div>
  <div class="firm-add">{escape(address_block)}</div>
  <div class="party"><span class="lbl">M/S:</span>
    <span class="val">{escape(quote.get('party_name') or '')}</span></div>
  <div class="party"><span class="lbl">ADD:</span>
    <span class="val add">{escape(quote.get('party_address') or '')}</span></div>
  <div class="status">
    <div><span class="lbl">ORDER STATUS:-</span><span>{escape(quote.get('order_status') or '')}</span></div>
    <div><span class="lbl">ADVANCE:-</span><span>{rupees(quote.get('advance'))}</span></div>
    <div><span class="lbl">BALANCE PAYABLE:-</span><span>{rupees(quote.get('balance'))}</span></div>
    <div><span class="lbl">DISPATCH:-</span><span>{escape(quote.get('dispatch') or '')}</span></div>
  </div>
  <table class="items">
    <thead><tr><th style="width:7%">No.</th><th>Description</th><th style="width:9%">GST</th>
      <th style="width:7%">Qty</th><th style="width:13%">Rate</th><th style="width:19%">Amount</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="footer-grid">
    <div class="footer-left">
      <div class="terms-head">TERMS &amp; CONDITIONS:-</div>
      <div class="terms-body">{escape(quote.get('terms') or '')}</div>
    </div>
    <div class="footer-right">
      <div class="totrow"><span>GST AMT</span><b>{rupees(quote.get('gst_amount'))}</b></div>
      <div class="totrow"><span>G.TOTAL</span><b>{rupees(quote.get('grand_total'))}</b></div>
      <div class="bank-head">OUR BANK DETAILS</div>
      <div class="bank-body">{escape(company.get('bank_details', ''))}</div>
    </div>
  </div>
  <div class="contact">{escape(company.get('contact_line') or '')}</div>
  <div class="notes"><ol>{notes}</ol>
    <div class="sign">{escape(company.get('name', ''))}</div></div>
  <div class="decl"><p>{DECLARATION}</p>
    <div class="sig">Proprietor / Authorised Signatory</div></div>
</div></body></html>"""
