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

from invoice_stationery import render_pdf,print_html

def register(app,helpers):
    require,check_csrf,flash,redirect,audit=(helpers[k] for k in ('require','check_csrf','flash','redirect','audit'))
    @app.get('/invoices/{invoice_id}/print')
    def print_invoice(request:Request,invoice_id:int):
        require(request)
        with SessionLocal() as db:
            row=db.get(Invoice,invoice_id)
            if not row:raise HTTPException(404)
            doc=db.query(InvoiceDocument).filter_by(invoice_id=row.id).first()
            html=print_html(row,doc)
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
                 headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','User-Agent':'MillsInvoiceSystem/1','Idempotency-Key':__import__('hashlib').sha256((str(invoice_id)+':'+addr+':'+__import__('hashlib').sha256(pdf).hexdigest()+':'+datetime.utcnow().strftime('%Y-%m-%d')).encode()).hexdigest()},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=15) as response:
                receipt=json.loads(response.read(5000).decode())
                if response.status<200 or response.status>=300 or not receipt.get('id'):
                    raise RuntimeError('Email service did not acknowledge the message.')
        except (urllib.error.HTTPError,urllib.error.URLError,ValueError,RuntimeError,TimeoutError) as exc:
            log.warning('Invoice email delivery was not accepted (invoice_id=%s, issue=%s)',invoice_id,type(exc).__name__)
            flash(request,'Email acceptance could not be confirmed. Check the recipient and sending setup. Retrying the same invoice today uses duplicate protection.','error')
            return redirect(f'/invoices/{invoice_id}')
        with SessionLocal() as db:
            audit(db,request,'invoice emailed','invoice',invoice_id,'Recipient '+addr[:180]+' / provider delivery ID '+str(receipt['id'])[:100]);db.commit()
        flash(request,'Invoice email accepted by the delivery provider.','success')
        return redirect(f'/invoices/{invoice_id}')