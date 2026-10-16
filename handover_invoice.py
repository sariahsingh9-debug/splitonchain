"""Mills stationery PDF, print preview and explicitly confirmed invoice emails.

The original supplied blank invoice is the PDF page background. Filling a document
never updates accounting amounts or automatically sends an email.
"""
import os, re, io, json, base64, logging, urllib.request, urllib.error
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path
from decimal import Decimal
from fastapi import Request, Form, HTTPException
from fastapi.responses import Response, HTMLResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from models import SessionLocal, Invoice, Contact, Setting
from invoice_tools import InvoiceDocument, fields_from

log=logging.getLogger('mills.invoice_delivery')
PAGE_W,PAGE_H=A4
TEMPLATE=Path(__file__).resolve().parent/'static'/'mills-blank-invoice.jpg'

def font_size_fit(c, content, maxwidth, start=9, minsize=6):
    text=str(content or '')
    pt=start
    while pt>minsize and c.stringWidth(text,'Helvetica',pt)>maxwidth:pt-=0.5
    return pt

def fill(c, value, x,y, maximum=120, size=10, align='left', bold=False, color='#122644'):
    s=str(value or '').replace('\n',' ').strip()
    if not s:return
    pt=font_size_fit(c,s,maximum,size)
    # We do not silently truncate customer or charge details on legal invoices.
    if c.stringWidth(s,'Helvetica',pt)>maximum:
        raise ValueError('Invoice field is too long for the stationery. Shorten the entry before printing.')
    c.setFont('Helvetica-Bold' if bold else 'Helvetica',pt)
    c.setFillColor(color)
    if align=='right':c.drawRightString(x,y,s)
    else:c.drawString(x,y,s)

def line_wrap(c,value, x,y, maxwidth=176, size=8.5, leading=12, maxlines=3):
    words=str(value or '').replace('\n',' ').split()
    lines=[];cur=''
    for word in words:
        new=(cur+' '+word).strip()
        if c.stringWidth(new,'Helvetica',size)>maxwidth and cur:
            lines.append(cur);cur=word
        else:cur=new
    if cur:lines.append(cur)
    if len(lines)>maxlines:raise ValueError('Address or customer details will not fit this stationery; shorten the field.')
    for i,ln in enumerate(lines):fill(c,ln,x,y-leading*i,maxwidth,size)

def fmt_amount(cents):return f'{Decimal(int(cents or 0))/100:,.2f}'

def render_pdf(invoice,company,doc):
    if not TEMPLATE.exists():raise RuntimeError('The Mills invoice stationery is missing.')
    buf=io.BytesIO()
    c=canvas.Canvas(buf,pagesize=A4, pageCompression=1)
    c.setTitle(f'Mills Multiservices invoice {invoice.number}')
    c.setAuthor('Mills Multiservices')
    # The supplied blank invoice artwork contains logo, plane, bank details, statutory
    # headings, notes, footer, and signature lines. Data stays separate in the overlay.
    c.drawImage(ImageReader(str(TEMPLATE)),0,0,width=PAGE_W,height=PAGE_H,mask='auto')
    # Mapping from the original 1102x1427 stationery to A4.
    sx=PAGE_W/1102;sy=PAGE_H/1427
    def p(x,y):return x*sx,PAGE_H-y*sy
    def at(v,x,y,width=160,size=9,align='left',bold=False,color='#14253e'):
        xx,yy=p(x,y);fill(c,v,xx,yy,maximum=width*sx,size=size,align=align,bold=bold,color=color)
    inv_num=doc.original_reference if doc and doc.original_reference else invoice.number
    at(invoice.issued_on.strftime('%d/%m/%Y'),874,163,width=169,size=9.5,bold=True)
    at(inv_num,874,201,width=169,size=9.8,bold=True)
    at(invoice.bill_to_name or invoice.contact.name,873,240,width=171,size=9.8,bold=True)
    address=invoice.bill_to_address or invoice.contact.address or ''
    addrx,addry=p(872,279)
    line_wrap(c,address,addrx,addry,maxwidth=176*sx,size=7.7,leading=10,maxlines=3)
    at(invoice.contact.phone or '',876,368,width=170,size=9)
    field_map={re.sub(r'[^A-Za-z0-9]','',str(label).lower()):value for label,value in fields_from(doc)}
    def find(*keys):
        for key in keys:
            key=re.sub(r'[^A-Za-z0-9]','',key.lower())
            if key in field_map:return field_map[key]
        return ''
    shipment=[find('Plane','Aircraft'),find('Container','Package / container'),
              find('EDA','E.D.A','Arrival date'),find('BL','B/L #','Bill of lading'),
              find('ROE','R.O.E','Exchange rate')]
    if not shipment[-1] and invoice.currency!='TTD':shipment[-1]=invoice.fx_rate
    for val,x,w in zip(shipment,[105,268,451,652,865],[114,145,146,158,170]):
        at(val,x,449,w,size=8.9,bold=True)
    # Keep printed items inside the 15-row charge table in the provided stationery.
    rows=[]
    for ln in invoice.lines:
        rows.append((ln.description,str(Decimal(ln.quantity_thousandths)/1000).rstrip('0').rstrip('.') if ln.quantity_thousandths%1000 else str(ln.quantity_thousandths//1000),
                     fmt_amount(ln.unit_price_cents),fmt_amount(ln.amount_cents)))
    # Preserve older customizable shipping references that do not match the new
    # five printed columns. Put them into unused description rows so no values disappear.
    standard={'plane','container','eda','bl','roe','aircraft','packagecontainer',
              'trackingwaybillnumber','shipmentreference','otherreference'}
    for label,value in fields_from(doc):
        key=re.sub('[^a-z0-9]','',label.lower())
        if key not in standard:
            rows.append((f'{label}: {value}', '', '', ''))
    if invoice.tax_cents:
        rows.append(('VAT', '', '', fmt_amount(invoice.tax_cents)))
    if len(rows)>14:
        raise ValueError('This document has too many charge lines for the supplied stationery. Please split the invoice or use a continuation sheet.')
    if invoice.currency!='TTD':
        # The approved artwork says TT$ in its headings. Mask only those labels
        # when the invoice is issued in another currency, preserving the navy theme.
        c.setFillColor('#073e74')
        x,y=p(737,453);c.rect(x,y-7*sx,132*sx,33*sy,fill=1,stroke=0)
        x,y=p(894,453);c.rect(x,y-7*sx,154*sx,33*sy,fill=1,stroke=0)
        xx,yy=p(756,464);fill(c,f'RATE ({invoice.currency})',xx,yy,maximum=114*sx,size=8,bold=True,color='#ffffff')
        xx,yy=p(899,464);fill(c,f'AMOUNT ({invoice.currency})',xx,yy,maximum=160*sx,size=8,bold=True,color='#ffffff')
        x,y=p(745,975);c.rect(x,y-7*sx,63*sx,33*sy,fill=1,stroke=0)
        xx,yy=p(764,985);fill(c,invoice.currency,xx,yy,maximum=66*sx,size=9.5,bold=True,color='#ffffff')
    for idx,(desc,qty,rate,total) in enumerate(rows):
        y=525+33.4*idx
        at(desc,47,y,width=535,size=8.7)
        at(qty,716,y,width=53,size=8.3,align='right')
        at(rate,869,y,width=89,size=8.3,align='right')
        at(total,1048,y,width=160,size=8.8,align='right',bold=True)
    at(fmt_amount(invoice.total_cents),1038,984,width=180,size=12,align='right',bold=True)
    # Display a small status watermark only for drafts, so staff cannot mistake a
    # proposed invoice for an issued customer demand.
    if invoice.status=='draft':
        c.saveState()
        c.translate(PAGE_W*.48,PAGE_H*.49);c.rotate(35)
        c.setFillColorRGB(.83,.20,.20)
        c.setFillAlpha(.17)
        c.setFont('Helvetica-Bold',74);c.drawCentredString(0,0,'DRAFT')
        c.restoreState()
    # Searchable text for the raster-background branding. The visible stationery
    # already prints these headings; a zero-alpha text layer preserves PDF search.
    c.saveState();c.setFillAlpha(0)
    c.setFont('Helvetica',1)
    c.drawString(2,2,'Mills Multiservices')
    c.drawString(2,4,str((json.loads(doc.design_snapshot) if doc else {}).get('heading','INVOICE')))
    c.restoreState()
    c.showPage();c.save()
    return buf.getvalue()

def register(app,helpers):
    require,check_csrf,flash,redirect,audit=(helpers[k] for k in ('require','check_csrf','flash','redirect','audit'))
    @app.get('/invoices/{invoice_id}/print')
    def print_invoice(request:Request,invoice_id:int):
        require(request)
        with SessionLocal() as db:
            row=db.get(Invoice,invoice_id)
            if not row:raise HTTPException(404)
        safe=str(invoice_id)
        html=(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Print Mills Invoice</title><style>body{{margin:0;background:#e8eef4;font:14px system-ui}}header{{background:#102840;color:white;padding:13px;display:flex;gap:12px;align-items:center;justify-content:space-between}}button,a{{padding:10px 15px;border:0;border-radius:8px;background:#fff;color:#123251;cursor:pointer;text-decoration:none;font-weight:700}}iframe{{display:block;width:100%;height:calc(100vh - 64px);border:none}}@media print{{header{{display:none}}iframe{{height:100vh}}}}</style></head><body>
<header><b>Mills Multiservices · Invoice {safe}</b><div><button onclick="document.querySelector('iframe').contentWindow.print()">Print invoice</button> <a href="/invoices/{safe}/pdf">Download PDF</a> <a href="/invoices/{safe}">Return</a></div></header>
<iframe title="Printable invoice" src="/invoices/{safe}/pdf?inline=1"></iframe></body></html>''')
        return HTMLResponse(html,headers={'Cache-Control':'no-store'})

    @app.post('/invoices/{invoice_id}/email')
    def send_invoice(request:Request,invoice_id:int,csrf:str=Form(...),recipient:str=Form('')):
        require(request,'admin','accountant');check_csrf(request,csrf)
        key=os.getenv('RESEND_API_KEY','').strip()
        sender=os.getenv('INVOICE_FROM_EMAIL','').strip()
        if not key or not sender:
            flash(request,'Invoice email is not configured yet. Add a verified Mills sending domain and API key under Render Environment.','error')
            return redirect(f'/invoices/{invoice_id}')
        _,sender_addr=parseaddr(sender)
        if not sender_addr or '@' not in sender_addr:
            flash(request,'The configured sender address is invalid.','error');return redirect(f'/invoices/{invoice_id}')
        recipient=recipient.strip()
        _,addr=parseaddr(recipient)
        if addr!=recipient or not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,255}',addr):
            flash(request,'Enter a valid customer email address.','error');return redirect(f'/invoices/{invoice_id}')
        with SessionLocal() as db:
            invoice=db.get(Invoice,invoice_id)
            if not invoice:raise HTTPException(404)
            if invoice.status not in ('issued','partial','paid'):
                flash(request,'Issue the invoice before emailing it to a customer.','error');return redirect(f'/invoices/{invoice_id}')
            doc=db.query(InvoiceDocument).filter_by(invoice_id=invoice.id).first()
            company=db.query(Setting).first()
            try:pdf=render_pdf(invoice,company,doc)
            except (ValueError,RuntimeError) as exc:
                flash(request,str(exc),'error');return redirect(f'/invoices/{invoice_id}')
            number=str(invoice.number)
        from html import escape
        # The pdf is attached so recipients do not need a portal login.
        payload={'from':sender,'to':[addr],'subject':f'Mills Multiservices | Invoice {number}',
                 'html':f'<p>Dear customer,</p><p>Please find attached invoice <strong>{escape(number)}</strong> from Mills Multiservices.</p><p>Thank you for your business.</p>',
                 'attachments':[{'filename':f'Mills-Invoice-{re.sub("[^A-Za-z0-9_-]","-",number)}.pdf','content':base64.b64encode(pdf).decode()}]}
        req=urllib.request.Request('https://api.resend.com/emails',data=json.dumps(payload).encode(),
                 headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'MillsInvoiceSystem/1'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=15) as response:
                receipt=json.loads(response.read(5000).decode())
                if response.status<200 or response.status>=300 or not receipt.get('id'):
                    raise RuntimeError('Email service did not acknowledge the message.')
        except (urllib.error.HTTPError,urllib.error.URLError,ValueError,RuntimeError,TimeoutError) as exc:
            log.warning('Invoice email delivery was not accepted (invoice_id=%s, issue=%s)',invoice_id,type(exc).__name__)
            flash(request,'The email could not be sent. Confirm the sender domain, API key, and recipient address; try again.','error')
            return redirect(f'/invoices/{invoice_id}')
        with SessionLocal() as db:
            audit(db,request,'invoice emailed','invoice',invoice_id,'Recipient '+addr[:180]+' / provider delivery ID '+str(receipt['id'])[:100]);db.commit()
        flash(request,'Invoice email accepted by the delivery provider.','success')
        return redirect(f'/invoices/{invoice_id}')