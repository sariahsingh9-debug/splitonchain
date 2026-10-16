# Make the invoice scanning workflow clear, without database changes.
from pathlib import Path
root=Path(__file__).resolve().parent

def rep(rel,old,new):
    f=root/rel
    s=f.read_text(encoding='utf-8')
    if new in s and old not in s:return
    if s.count(old)!=1:
        raise RuntimeError(f'{rel}: cannot find unique expected marker: {old[:90]!r}')
    f.write_text(s.replace(old,new,1),encoding='utf-8')

p='templates/photo_import.html'
rep(p,'HISTORICAL RECORDS / DOCUMENT CAPTURE','QUICK INVOICE SCANNER')
rep(p,'<h1>Scan paper invoices</h1>','<h1>Scan invoices</h1>')
rep(p,'Clear, complete documents are saved as invoice drafts automatically; uncertain scans are flagged for correction.',
    'Upload invoice photos. The details fill in automatically. Check them, then save, print or email the invoice.')
rep(p,'<span>Save reliable drafts, flag exceptions</span>','<span>Save, print or email</span>')
rep(p,'<h2>Extracted invoices</h2><p>Automatically created drafts require no typing. Review only the scans the system cannot read confidently.</p>',
    '<h2>Your scanned invoices</h2><p>Saved invoices are ready below. If a photo is unclear, correct the highlighted details and click Save Invoice.</p>')
rep(p,"{{'Draft saved' if s.status=='imported' else 'Needs review'}}","{{'Saved' if s.status=='imported' else 'Check details'}}")
rep(p,'View saved draft →','Open Invoice →')
rep(p,'Zoom in on the original document and verify the numbers and spelling.',
      'Compare these details with the photographed invoice.')
rep(p,'<h4>Automatically filled details <small>Editable</small></h4>',
      '<h4>Invoice details <small>Already filled in — correct only if needed</small></h4>')
rep(p,'Detected services and amounts <small>Correct before saving</small>',
      'Services and amounts <small>Correct only if needed</small>')
rep(p,
'<label class="photo-check"><input type="checkbox" name="override_amount" value="yes">The verified line total differs from the detected total; use my corrected amounts</label>',
'<details class="scan-extra"><summary>My corrected total is different</summary><label class="photo-check"><input type="checkbox" name="override_amount" value="yes">Use the corrected amounts entered above</label></details>')
rep(p,
'<label class="photo-check"><input type="checkbox" name="verified" value="yes" required><strong>I checked the customer, dates, invoice number, division, currency, services and totals against the original paper.</strong></label>',
'<label class="photo-check scan-confirm"><input type="checkbox" name="verified" value="yes" required><strong>The invoice details look correct.</strong></label>')
rep(p,
'<button type="submit" class="btn primary">Save verified invoice as draft <svg><use href="#i-arrow"/></svg></button><p class="photo-safe-note">Saving creates an unissued draft only. No revenue, cash, VAT, or receivable is posted until an authorized user issues it later.</p>',
'<button type="submit" class="btn primary">Save Invoice <svg><use href="#i-arrow"/></svg></button><p class="photo-safe-note">Invoice saved to your records. You can print or email it from the next screen.</p>')
rep(p,
'<div class="photo-finished"><svg><use href="#i-shield"/></svg>Imported as invoice draft. The temporary review image has been discarded.</div>',
'''<div class="photo-finished scan-ready"><h4>Invoice saved successfully</h4>
<p>Print or email it below. Confirm the details before making an invoice official.</p>
<div class="scan-action-row">
<a href="/invoices/{{s.invoice_id}}" class="btn ghost">Open Invoice</a>
<form action="/invoices/{{s.invoice_id}}/finalize-print" method="post" target="_blank" data-confirm="I checked this invoice. Printing will finalize it and record it in the accounts. For old invoices, make sure it has not already been counted. Continue?">
<input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="approved" value="yes">
<button type="submit" class="btn primary">Print Invoice</button></form>
<form action="/invoices/{{s.invoice_id}}/finalize-email" method="post" data-confirm="I checked this invoice. Emailing will finalize it and record it in the accounts. Continue?">
<input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="approved" value="yes">
<input type="email" name="recipient" placeholder="Customer email" aria-label="Customer email" required>
<button type="submit" class="btn soft">Email Invoice</button></form></div></div>''')
rep(p,'Select one or more invoice photographs above and the extracted details will appear here for review.',
      'Upload invoice photos above and the details will fill in automatically.')

p='templates/invoice_detail.html'
rep(p,
'<a class="btn ghost" href="/invoices/{{ invoice.id }}/print" target="_blank" rel="noopener">Print invoice</a>',
'''{% if invoice.status=='draft' and user.role in ['admin','accountant'] %}
<form action="/invoices/{{invoice.id}}/finalize-print" method="post" target="_blank" data-confirm="I checked the invoice. Printing will finalize it and record it in the accounts. For old invoices, make sure it has not already been counted. Continue?">
<input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="approved" value="yes">
<button type="submit" class="btn ghost">Print Invoice</button></form>
{% else %}<a class="btn ghost" href="/invoices/{{ invoice.id }}/print" target="_blank" rel="noopener">Print Invoice</a>{% endif %}''')
rep(p,"{% if invoice.status in ['issued','partial','paid'] and user.role in ['admin','accountant'] %}",
      "{% if user.role in ['admin','accountant'] and invoice.status in ['draft','issued','partial','paid'] %}")
rep(p,'action="/invoices/{{invoice.id}}/email"',
      '''action="/invoices/{{invoice.id}}/{% if invoice.status=='draft' %}finalize-email{% else %}email{% endif %}"''')
rep(p,'<input type="hidden" name="csrf" value="{{csrf}}">\n<input type="email" name="recipient"',
      '<input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="approved" value="yes">\n<input type="email" name="recipient"')
rep(p,'data-confirm="Email the issued invoice PDF to this customer?"',
      'data-confirm="Confirm these invoice details are correct before sending to the customer."')
rep(p,'''{% endif %}{% if invoice.status=='draft' and user.role in ['admin','accountant'] %}<form method="post" action="/invoices/{{ invoice.id }}/issue" data-confirm="Issue this invoice and post the entries to the ledger? This cannot be edited afterward."><input type="hidden" name="csrf" value="{{ csrf }}"><button class="btn primary">Issue invoice →</button></form>{% endif %}''',
      '{% endif %}')

# Reuse the existing delivery implementation and audit logging.
mail=root/'handover_invoice.py'
s=mail.read_text(encoding='utf-8')
if 'app.state.mills_send_invoice = send_invoice' not in s:
    s+='\n    # One-step email action uses the existing invoice delivery handler.\n    app.state.mills_send_invoice = send_invoice\n'
    mail.write_text(s,encoding='utf-8')

app=root/'app.py'
s=app.read_text(encoding='utf-8')
if 'register_simple_invoice_workflow(app' not in s:
    s+='''
# Simple invoice actions require explicit authorization and confirmation.
from simple_invoice_workflow import register as register_simple_invoice_workflow
register_simple_invoice_workflow(app, {
    'require':require, 'check_csrf':check_csrf, 'flash':flash,
    'redirect':redirect, 'invoice_issue':invoice_issue,
})
'''
    app.write_text(s,encoding='utf-8')

base=root/'templates/base.html'
s=base.read_text(encoding='utf-8')
link='<link rel="stylesheet" href="/static/simple_invoice_workflow.css?v=1">'
if link not in s:
    if '</head>' not in s:raise RuntimeError('Missing template head')
    base.write_text(s.replace('</head>',link+'</head>',1),encoding='utf-8')
print('Simplified invoice actions installed.')