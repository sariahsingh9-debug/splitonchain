"""Install the 2026 Mills production invoice release, strictly presentation/workflow only.
Preserves existing financial records and every historical invoice/document row.
"""
from pathlib import Path
root=Path(__file__).resolve().parent

def replace_once(rel,old,new):
    f=root/rel;s=f.read_text(encoding='utf-8')
    if new in s:return
    if s.count(old)!=1:raise RuntimeError(f'{rel}: expected marker occurred {s.count(old)} times: {old[:100]}')
    f.write_text(s.replace(old,new,1),encoding='utf-8')

# The provided blank invoice has 5 shipment reference columns, not the original 4.
replace_once('invoice_tools.py',
    "DEFAULT_LABELS=['Shipment reference', 'Tracking / waybill number', 'Package / container', 'Other reference']",
    "DEFAULT_LABELS=['Plane','Container','E.D.A','B/L #','R.O.E']")
replace_once('invoice_tools.py',
    'values=[str(form.get(f\'extra_{i}\',\'\')).strip()[:180] for i in range(1,5)]',
    'values=[str(form.get(f\'extra_{i}\',\'\')).strip()[:180] for i in range(1,6)]')
replace_once('invoice_tools.py',
    'if any(len(str(form.get(f\'extra_{i}\',\'\')).strip())>180 for i in range(1,5)):',
    'if any(len(str(form.get(f\'extra_{i}\',\'\')).strip())>180 for i in range(1,6)):')
replace_once('invoice_tools.py',
    "labels=[str(form.get(f'label_{i}','')).strip() for i in range(1,5)]",
    "labels=[str(form.get(f'label_{i}','')).strip() for i in range(1,6)]")
# Old saved settings may still contain 4 labels. Extend, never discard, them.
replace_once('invoice_tools.py',
    'data=_json(pref.data if pref else None,{})\n    return {**DEFAULT_DESIGN,**{k:v for k,v in data.items() if k in DEFAULT_DESIGN}}',
    '''data=_json(pref.data if pref else None,{})
    config={**DEFAULT_DESIGN,**{k:v for k,v in data.items() if k in DEFAULT_DESIGN}}
    config['labels']=list(config.get('labels') or []) if len(config.get('labels') or [])==5 and all(config.get('labels') or []) else DEFAULT_LABELS.copy()
    return config''')
# Existing issued invoices are never modified: snapshot() uses their historical profile.

# Make the PDF route use the exact Mills stationery for every invoice.
replace_once('app.py',
    'return pdf_invoice(obj,setting,doc,outstanding(obj),cents)',
    '''try: pdf=render_mills_pdf(obj,setting,doc)
        except (RuntimeError,ValueError) as exc:raise HTTPException(422,str(exc))
        filename=re.sub(r'[^A-Za-z0-9_.-]','-',obj.number)
        disposition='inline' if request.query_params.get('inline')=='1' else 'attachment'
        return Response(pdf,media_type='application/pdf',headers={
            'Content-Disposition':f'{disposition}; filename="Mills-Invoice-{filename}.pdf"',
            'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'})''')
# Register additional print and email routes only after the existing core API routes.
app=root/'app.py';src=app.read_text(encoding='utf-8')
marker='# MILLS PAPER STATIONERY AND DELIVERY RELEASE'
if marker not in src:
    src+='''
# MILLS PAPER STATIONERY AND DELIVERY RELEASE
from handover_invoice import render_pdf as render_mills_pdf, register as register_mills_delivery
register_mills_delivery(app, {
    'require':require, 'check_csrf':check_csrf, 'flash':flash,
    'redirect':redirect, 'audit':audit,
})
'''
    app.write_text(src,encoding='utf-8')

# Append the two new actions to the visible invoice page.
replace_once('templates/invoice_detail.html',
    '<a class="btn ghost" href="/invoices/{{ invoice.id }}/pdf"><svg><use href="#i-down"/></svg>Download PDF</a>',
    '''<a class="btn ghost" href="/invoices/{{ invoice.id }}/pdf"><svg><use href="#i-down"/></svg>Download PDF</a>
<a class="btn ghost" href="/invoices/{{ invoice.id }}/print" target="_blank" rel="noopener">Print invoice</a>
{% if invoice.status in ['issued','partial','paid'] and user.role in ['admin','accountant'] %}
<form method="post" action="/invoices/{{invoice.id}}/email" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
<input type="hidden" name="csrf" value="{{csrf}}">
<input type="email" name="recipient" aria-label="Customer email recipient" value="{{ invoice.bill_to_email or '' }}" placeholder="Customer email" required style="width:205px;max-width:100%;padding:10px;border:1px solid #d4e0ec;border-radius:8px;">
<button type="submit" class="btn primary" data-confirm="Email the issued invoice PDF to this customer?">Email invoice</button></form>
{% endif %}''')
# Match the services shown on the customer's example paper invoice.
invoice_form=root/'templates/invoice_new.html'
html=invoice_form.read_text(encoding='utf-8')
if 'id="mills-invoice-services"' not in html:
    html=html.replace('name="desc_{{ n }}"', 'list="mills-invoice-services" name="desc_{{ n }}"')
    options=''.join('<option value="'+x+'">' for x in (
        'BROKERAGE','DOCUMENTATION','TRANSPORT','REIMBURSEMENT','DUTY & VAT',
        'UPLIFTMENT','DELIVERY','RENT','OVERTIME','BUREAU OF STANDARDS',
        'HANDLING CHARGE','SKYBOX','COURIER','FREIGHT FORWARDING'))
    html=html.replace('</form>', '<datalist id="mills-invoice-services">'+options+'</datalist></form>',1)
    invoice_form.write_text(html,encoding='utf-8')

# Existing new invoice form already renders saved custom label values dynamically.

# Scan documents now automatically create safe drafts when the data is complete.
replace_once('photo_import.py',
    'from invoice_tools import InvoiceDocument, active_design',
    'from invoice_tools import InvoiceDocument, active_design\nfrom auto_capture import enrich_extraction,automatic_draft')
replace_once('photo_import.py',
    'result=extract_fields(text,quality)',
    'result=enrich_extraction(text,extract_fields(text,quality))')
replace_once('photo_import.py',
    "recorded=0;failures=[]",
    "recorded=0;automatically_saved=0;failures=[]")
replace_once('photo_import.py',
    '''db.add(PaperScan(created_by=request.state.user.id,filename=fname,content_hash=digest,
                                 preview=thumb,extraction=json.dumps(data),quality=int(data['confidence'])))
                recorded+=1''',
    '''row=PaperScan(created_by=request.state.user.id,filename=fname,content_hash=digest,
                                 preview=thumb,extraction=json.dumps(data),quality=int(data['confidence']))
                db.add(row);db.flush()
                # Save reliable scans as unissued drafts. Unclear images remain for review.
                try:
                    with db.begin_nested():
                        converted=automatic_draft(db,request,row,next_number,audit)
                    if converted:automatically_saved+=1
                except (ValueError,TypeError,InvalidOperation,IntegrityError) as exc:
                    log.warning('Automatic scan drafting needs review (scan id=%s, error=%s)',row.id,type(exc).__name__)
                recorded+=1''')
replace_once('photo_import.py',
    "if recorded:flash(request,f'{recorded} invoice photo(s) read. Review and correct every result before saving any draft.','success')",
    "if recorded:flash(request,f'{recorded} invoice photo(s) read. {automatically_saved} draft(s) created automatically; {recorded-automatically_saved} need review because required details are uncertain. No accounting postings were made.','success')")
replace_once('templates/photo_import.html',
    '<a class="btn ghost" href="/paper-invoices/new">Manual entry</a>',
    '<a class="btn ghost" href="/invoices">Invoice records</a>')
replace_once('templates/photo_import.html',
    'Upload several photos at once. The system reads them and prepares editable invoice details for review.',
    'Select up to 12 printed invoice photos. Clear, complete documents are saved as invoice drafts automatically; uncertain scans are flagged for correction.')
replace_once('templates/photo_import.html',
    '<span>Review and correct every invoice</span>',
    '<span>Automatically fill invoice details</span>')
replace_once('templates/photo_import.html',
    '<span>Save verified drafts</span>',
    '<span>Save reliable drafts, flag exceptions</span>')
replace_once('templates/photo_import.html',
    '<p>Every amount, date and customer name must be checked against the original photo.</p>',
    '<p>Automatically created drafts require no typing. Review only the scans the system cannot read confidently.</p>')
# The invoice designer must preview the actual approved blank form, not a generic card.
preview=root/'templates/invoice_design.html'
body=preview.read_text(encoding='utf-8')
if 'mills-blank-invoice.jpg' not in body:
    start=body.index('      <div class="paper-preview"')
    end=body.index('      <p class="design-guide"',start)
    body=(body[:start]+'      <div class="paper-preview" style="padding:0;border:0;background:none"><img src="/static/mills-blank-invoice.jpg?v=20261015" alt="Mills Multiservices printable invoice stationery" style="width:100%;height:auto;display:block;border-radius:9px"></div>\n'+body[end:])
    preview.write_text(body,encoding='utf-8')
replace_once('templates/photo_import.html',
    '<h3>{{s.filename}}</h3><span class="subtle-pill">',
    '<h3>{{s.filename}}</h3><p style="font-size:12px;margin:4px 0;color:#67819b">{{s.data.reference or "Reference not found"}} · {{s.data.customer or "Customer not found"}}</p><span class="subtle-pill">')
print('Mills stationery, five shipment fields, guarded photo drafting, print and email actions installed.')