"""Simple, auditable invoice actions for the Mills invoice scan workflow.

The buttons can finalize an existing draft and print/email in one interaction,
but only after explicit confirmation by an authorized accountant/admin.
"""
import os
import re
from email.utils import parseaddr

from fastapi import Request, Form, HTTPException
from models import SessionLocal, Invoice, Setting
from invoice_tools import InvoiceDocument
from handover_invoice import render_pdf as render_mills_pdf

def register(app, helpers):
    require = helpers['require']
    check_csrf = helpers['check_csrf']
    flash = helpers['flash']
    redirect = helpers['redirect']
    invoice_issue = helpers['invoice_issue']

    def preflight_pdf(invoice_id):
        with SessionLocal() as db:
            invoice = db.get(Invoice, invoice_id)
            if invoice is None: raise HTTPException(404, 'Invoice not found')
            if invoice.status not in ('draft', 'issued', 'partial', 'paid'):
                raise HTTPException(400, 'This invoice cannot be printed or emailed')
            setting = db.query(Setting).first()
            doc = db.query(InvoiceDocument).filter_by(invoice_id=invoice_id).first()
            render_mills_pdf(invoice, setting, doc)
            return invoice.status, invoice.bill_to_email or ''

    def finalize_if_draft(request, invoice_id, csrf, status):
        if status == 'draft':
            invoice_issue(request, invoice_id, csrf)

    @app.post('/invoices/{invoice_id}/finalize-print')
    def print_ready_invoice(request: Request, invoice_id: int,
                            csrf: str = Form(...), approved: str = Form('')):
        require(request,'admin','accountant')
        check_csrf(request,csrf)
        if approved != 'yes':
            flash(request,'Confirm you checked the invoice before printing it.', 'error')
            return redirect('/invoices/'+str(invoice_id))
        try:
            status,_ = preflight_pdf(invoice_id)
        except (ValueError,RuntimeError) as error:
            flash(request,str(error),'error')
            return redirect('/invoices/'+str(invoice_id))
        finalize_if_draft(request,invoice_id,csrf,status)
        return redirect(f'/invoices/{invoice_id}/print')

    @app.post('/invoices/{invoice_id}/finalize-email')
    def email_ready_invoice(request: Request, invoice_id: int,
                            csrf: str = Form(...), approved: str = Form(''),
                            recipient: str = Form('')):
        require(request,'admin','accountant')
        check_csrf(request,csrf)
        if approved != 'yes':
            flash(request,'Confirm you checked the invoice before emailing it.', 'error')
            return redirect('/invoices/'+str(invoice_id))
        # Validate email provider before issuing so a missing provider does not
        # post revenue and surprise the user.
        sender = os.getenv('INVOICE_FROM_EMAIL','').strip()
        api_key = os.getenv('RESEND_API_KEY','').strip()
        sender_addr = parseaddr(sender)[1]
        if not api_key or not sender_addr or '@' not in sender_addr:
            flash(request,'Email is not set up yet. Ask the administrator to connect the Mills sending address. You can still save or print invoices.','error')
            return redirect('/invoices/'+str(invoice_id))
        try:
            status, customer_email = preflight_pdf(invoice_id)
        except (ValueError,RuntimeError) as error:
            flash(request,str(error),'error')
            return redirect('/invoices/'+str(invoice_id))
        recipient = recipient.strip() or customer_email
        email = parseaddr(recipient)[1]
        if not recipient or email != recipient or not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,255}',recipient):
            flash(request,'Enter a valid customer email address to send the invoice.','error')
            return redirect('/invoices/'+str(invoice_id))
        finalize_if_draft(request,invoice_id,csrf,status)
        # Existing email service handles delivery and audit logging.
        sender_handler = app.state.mills_send_invoice
        return sender_handler(request,invoice_id,csrf,recipient)