"""Wire tested scan extraction, printable stationery, and requested account correction."""
from pathlib import Path
root=Path(__file__).resolve().parent

def edit(name,old,new):
 p=root/name;s=p.read_text()
 if new in s:return
 if old not in s:raise RuntimeError(f'Missing installation marker: {name}: {old[:80]}')
 p.write_text(s.replace(old,new))

edit('app.py','initialize()','initialize()\nfrom account_email_migration import apply as apply_requested_email_change\napply_requested_email_change()')
edit('photo_import.py','result=enrich_extraction(text,extract_fields(text,quality))', '''result=enrich_extraction(text,extract_fields(text,quality))
    from mills_scan import extract, SHIP_LABELS
    try:
        result=extract(blob,result)
    except (ValueError,subprocess.TimeoutExpired):
        result['confidence']=0
        result.setdefault('warnings',[]).append('Table reading needs review.')
    if isinstance(result.get('shipment'),list):
        result['shipment']=dict(zip(SHIP_LABELS,result['shipment']))
        result['customer_address']=result.get('address','')
        result['customer_phone']=result.get('phone','')''')
for name in ['app.py','photo_import.py','templates/invoice_new.html','templates/photo_import.html']:
 edit(name,'range(1,9)','range(1,21)')
# Preserve customized labels on historic and new invoices.
edit('invoice_tools.py',"config['labels']=list(config.get('labels') or []) if len(config.get('labels') or [])==5 and all(config.get('labels') or []) else DEFAULT_LABELS.copy()", "config['labels']=list(config.get('labels') or DEFAULT_LABELS)")
edit('invoice_tools.py',"labels=design.get('labels',DEFAULT_LABELS)[:4]", "labels=design.get('labels',DEFAULT_LABELS)[:5]")
# Reviewed scans must retain the same source metadata as automatic drafts.
edit('photo_import.py',"settings=db.query(Setting).first()\n                if not settings", "scanned=json.loads(row.extraction or '{}')\n                settings=db.query(Setting).first()\n                if not settings")
edit('photo_import.py','bill_to_address=customer.address,','bill_to_address=scanned.get(\'customer_address\') or customer.address,')
edit('photo_import.py',"design['issuer_phone']=settings.business_phone or ''", "design['issuer_phone']=settings.business_phone or ''\n                design['bill_to_phone']=scanned.get('customer_phone') or customer.phone\n                design['labels']=['Plane','Container','E.D.A','B/L #','R.O.E']")
edit('photo_import.py',"extra_values=json.dumps(['','','',''])", "extra_values=json.dumps([(scanned.get('shipment') or {}).get(k,'') for k in design['labels']])")
edit('photo_import.py',"status='draft',memo=memo,created_by=request.state.user.id,", "status='draft',memo=memo or '\\n'.join(v for v in [scanned.get('description'),scanned.get('reference_note')] if v),created_by=request.state.user.id,")
edit('photo_import.py',"row.invoice_id=invoice.id;row.status='imported';row.preview=None", "row.invoice_id=invoice.id;row.status='imported'")
print('Final invoice verification changes installed.')
