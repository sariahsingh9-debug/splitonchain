"""Integration checks against the isolated baseline test database. No email sent."""
import io,json,os
from pathlib import Path
from types import SimpleNamespace
import pytest
import test_flow as core
from models import SessionLocal,Invoice,Journal,User,Audit
from photo_import import PaperScan,scan_one
from invoice_tools import InvoiceDocument

def test_26_scan_and_print(monkeypatch):
    fixture=os.getenv('MILLS_SAMPLE_INVOICE')
    if not fixture:pytest.skip('Set MILLS_SAMPLE_INVOICE for private reference-image verification')
    blob=Path(fixture).read_bytes()
    preview,data=scan_one('sample.jpeg',blob)
    assert data['reference'] and data['customer'] and data['customer_address']
    assert data['customer_phone'] and data['shipment']['Container']
    assert len(data['lines'])==7 and data['total']=='12806.57'
    private_checks=os.getenv('MILLS_SCAN_ASSERTIONS')
    if private_checks:
        import textwrap
        exec(compile(textwrap.dedent(Path(private_checks).read_text()),private_checks,'exec'),{'data':data})
    reference=data['reference']
    monkeypatch.setattr('photo_import.scan_one',lambda *args:(preview,data))
    with SessionLocal() as db:before=db.query(Journal).count()
    r=core.client.post('/paper-invoices/photos',data={'csrf':core.csrf('/paper-invoices/photos')},files={'photos':('sample.jpeg',blob,'image/jpeg')},follow_redirects=True)
    assert r.status_code==200
    with SessionLocal() as db:
        doc=db.query(InvoiceDocument).filter_by(original_reference=reference).one()
        inv=db.get(Invoice,doc.invoice_id);iid=inv.id
        assert inv.status=='draft' and inv.total_cents==1280657
        assert inv.bill_to_address==data['customer_address']
        assert json.loads(doc.design_snapshot)['bill_to_phone']==data['customer_phone']
        assert len(inv.lines)==7 and db.query(Journal).count()==before
        assert db.query(PaperScan).filter_by(invoice_id=iid).one().preview
    for path in [f'/invoices/{iid}',f'/invoices/{iid}/print',f'/invoices/{iid}/pdf']:
        r=core.client.get(path);assert r.status_code==200
        if path.endswith('/print'):
            assert '<iframe' not in r.text and 'onclick=' not in r.text
            assert '12,806.57' in r.text and data['shipment']['Container'] in r.text
        if path.endswith('/pdf'):Path('/tmp/mills-verified-invoice.pdf').write_bytes(r.content)
    r=core.post(f'/invoices/{iid}/finalize-email',{'approved':'yes','recipient':'customer@example.net'},f'/invoices/{iid}')
    assert 'Email is not set up' in r.text
    with SessionLocal() as db:assert db.get(Invoice,iid).status=='draft'
    r=core.post(f'/invoices/{iid}/finalize-print',{'approved':'yes'},f'/invoices/{iid}')
    assert r.status_code==200 and 'Print invoice' in r.text
    with SessionLocal() as db:assert db.get(Invoice,iid).status=='issued'
    # Duplicate upload must never create another invoice with the same reference.
    core.client.post('/paper-invoices/photos',data={'csrf':core.csrf('/paper-invoices/photos')},files={'photos':('sample.jpeg',blob,'image/jpeg')})
    with SessionLocal() as db:assert db.query(InvoiceDocument).filter_by(original_reference=reference).count()==1
    # Provider transport mocked: inspect attached PDF and retry protection, no external send.
    monkeypatch.setenv('RESEND_API_KEY','fake-test-key');monkeypatch.setenv('INVOICE_FROM_EMAIL','billing@example.net')
    sent=[]
    class Reply:
        status=200
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):return b'{"id":"mock-delivery"}'
    def send(req,**kwargs):sent.append(req);return Reply()
    monkeypatch.setattr('handover_invoice.urllib.request.urlopen',send)
    for _ in range(2):
        r=core.post(f'/invoices/{iid}/email',{'recipient':'customer@example.net'},f'/invoices/{iid}')
        assert 'accepted by the delivery provider' in r.text
    assert sent[0].get_header('Idempotency-key')==sent[1].get_header('Idempotency-key')
    assert sent[0].data==sent[1].data
    assert json.loads(sent[0].data)['attachments'][0]['content'].startswith('JVBER')

def test_27_account_email_change(monkeypatch):
    from account_email_migration import apply
    with SessionLocal() as db:
        user=db.query(User).filter_by(email='owner@example.net').one()
        uid=user.id;before=user.password_hash;name=user.full_name
    monkeypatch.setenv('MILLS_LOGIN_EMAIL_OLD','owner@example.net')
    monkeypatch.setenv('MILLS_LOGIN_EMAIL_NEW','new-owner@example.net')
    monkeypatch.setenv('MILLS_LOGIN_ACCOUNT_NAME',name)
    apply();apply()
    with SessionLocal() as db:
        user=db.get(User,uid)
        assert user.email=='new-owner@example.net' and user.password_hash==before
        assert db.query(Audit).filter_by(action='requested login email migration').count()==1
    core.post('/logout',{},'/profile')
    r=core.client.post('/login',data={'csrf':core.csrf('/login'),'email':'new-owner@example.net','password':'very-secure-demo-test-passphrase!'},follow_redirects=True)
    assert 'Business overview' in r.text

def test_28_multipage_and_uncertain_scan():
    from invoice_stationery import layout,pdf_bytes,print_html
    from auto_capture import ready
    from datetime import date
    invoice=SimpleNamespace(id=999,number='TEST-LONG',contact=SimpleNamespace(name='Test customer',phone='555-0100'),bill_to_name='Test customer',bill_to_address='Test address',memo='Test notes',issued_on=date(2026,1,1),currency='USD',status='draft',payments=[],total_cents=30000,subtotal_cents=30000,tax_cents=0,tax_bps=0,
        lines=[SimpleNamespace(description='Service '+str(i),quantity_thousandths=1000,unit_price_cents=1000,amount_cents=1000) for i in range(30)])
    cents=lambda n:f'{n/100:,.2f}'
    pages=layout(invoice,None,30000,cents)
    assert len(pages)==3
    assert any(c['text']=='Service 29' for c in pages[-1])
    assert any(c['text']=='300.00' for c in pages[-1])
    html=print_html(invoice,None)
    assert html.count('<section class="sheet">')==3 and 'RATE (USD)' in html
    assert pdf_bytes(invoice,None,30000,cents).startswith(b'%PDF')
    assert not ready({'reference':'unclear','issued_on':'2026-01-01','customer':'Test','total':'100','confidence':20,'lines':[{'description':'Transport','qty':'1','unit':'100'}]})
    assert not ready({'reference':'mismatch','issued_on':'2026-01-01','customer':'Test','total':'120','confidence':90,'lines':[{'description':'Transport','qty':'1','unit':'100'}]})
