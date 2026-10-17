import io,json,re
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from invoice_tools import _json,fields_from
ROOT=Path(__file__).resolve().parent
W,H=1102,1427
def wrapped(text,width,size=14,bold=False):
    font='Helvetica-Bold' if bold else 'Helvetica';lines=[]
    for para in str(text or '').splitlines():
        line=''
        for word in para.split():
            if stringWidth((line+' '+word).strip(),font,size)>width and line:
                lines.append(line);line=word
            else:line=(line+' '+word).strip()
            while stringWidth(line,font,size)>width:
                n=len(line)-1
                while n>1 and stringWidth(line[:n],font,size)>width:n-=1
                lines.append(line[:n]);line=line[n:]
        lines.append(line)
    return lines or ['']

def layout(inv,doc,outstanding,cents):
    des=_json(doc.design_snapshot,{}) if doc else {}
    extras=dict(fields_from(doc)); phone=des.get('bill_to_phone','') or (inv.contact.phone if inv.contact else '')
    lines=[]
    memo=inv.memo or ''
    for label,value,width,size,limit in [
        ('Customer',inv.bill_to_name or inv.contact.name,182,13,2),
        ('Address',inv.bill_to_address,182,12,3),('Phone',phone,182,13,1),
        ('Original reference',doc.original_reference if doc else '',182,13,1)]:
        if len(wrapped(value,width,size))>limit:
            lines.extend((v,'','','') for v in wrapped(label+': '+str(value),570,13))
    for key in ('terms','footer'):
        if des.get(key):lines.extend((v,'','','') for v in wrapped(des[key],570,13))
    for label,value in extras.items():
        if label not in ['Plane','Container','E.D.A','B/L #','R.O.E']:lines.extend((v,'','','') for v in wrapped(f'{label}: {value}',570,13))
    if memo:lines.extend([(v,'','','') for v in wrapped(memo,570,13)])
    for ln in inv.lines:
        desc=wrapped(ln.description,570,14)
        lines.append((desc[0],f'{ln.quantity_thousandths/1000:g}',cents(ln.unit_price_cents),cents(ln.amount_cents)))
        lines.extend((v,'','','') for v in desc[1:])
    if inv.tax_cents:
        lines.extend([('Subtotal','','',cents(inv.subtotal_cents)),(f'VAT ({inv.tax_bps/100:g}%)','','',cents(inv.tax_cents))])
    chunks=[lines[i:i+13] for i in range(0,len(lines),13)] or [[]]
    pages=[]
    for page_no,chunk in enumerate(chunks):
        cells=[]
        def put(x,y,width,text,size=14,bold=False,align='left',maxlines=1):
            for n,line in enumerate(wrapped(text,width,size,bold)[:maxlines]):cells.append(dict(x=x,y=y+n*(size+3),width=width,text=line,size=size,bold=bold,align=align))
        put(880,138,182,inv.issued_on.strftime('%d/%m/%Y'),14)
        put(880,171,182,doc.original_reference if doc and doc.original_reference else inv.number,13)
        put(880,204,182,inv.bill_to_name or inv.contact.name,13,maxlines=2)
        put(880,263,182,inv.bill_to_address,12,maxlines=3)
        put(880,329,182,phone,13)
        for x,width,key in [(42,172,'Plane'),(233,188,'Container'),(441,156,'E.D.A'),(618,174,'B/L #'),(814,242,'R.O.E')]:
            put(x,421,width,extras.get(key,inv.currency if key=='R.O.E' else ''),13,maxlines=2)
        for n,(desc,qty,rate,amount) in enumerate(chunk):
            y=515+n*33.5
            put(43,y,568,desc,13)
            put(631,y,102,qty,13,align='right')
            put(754,y,123,rate,13,align='right')
            put(900,y,155,amount,13,align='right')
        put(838,963,210,cents(inv.total_cents) if page_no==len(chunks)-1 else 'Continued',22,True,'right')
        # Keep the source's printed currency honest for non-TTD invoices.
        if inv.currency!='TTD':put(751,958,68,inv.currency,16,True)
        put(610,1175,430,f'Paid: {inv.currency} {cents(inv.total_cents-outstanding)} | Balance: {inv.currency} {cents(outstanding)}',11)
        put(40,1381,980,'Mills Multiservices | '+str(des.get('heading','INVOICE')),10)
        put(40,1398,980,f'{inv.number} | {inv.status.upper()} | Page {page_no+1} of {len(chunks)}',11)
        pages.append(cells)
    return pages

def pdf_bytes(inv,doc,outstanding,cents):
    buf=io.BytesIO();c=canvas.Canvas(buf,pagesize=(595.28,841.89),invariant=1)
    c.setTitle(f'{inv.number} - Mills Multi Services')
    for cells in layout(inv,doc,outstanding,cents):
        c.saveState();c.scale(595.28/W,841.89/H)
        c.drawImage(str(ROOT/'static/mills-blank-invoice.jpg'),0,0,width=W,height=H)
        if inv.currency!='TTD':
            c.setFillColorRGB(1,1,1);c.rect(747,H-994,77,47,fill=1,stroke=0)
            c.setFillColorRGB(.02,.24,.40)
            c.rect(747,H-502,143,40,fill=1,stroke=0);c.rect(893,H-502,176,40,fill=1,stroke=0)
            c.setFillColorRGB(1,1,1);c.setFont('Helvetica-Bold',15)
            c.drawCentredString(818,H-487,'RATE ('+inv.currency+')')
            c.drawCentredString(981,H-487,'AMOUNT ('+inv.currency+')')
        for cell in cells:
            c.setFillColorRGB(.04,.10,.18);c.setFont('Helvetica-Bold' if cell['bold'] else 'Helvetica',cell['size'])
            x=cell['x']+cell['width'] if cell['align']=='right' else cell['x']
            if cell['align']=='right':c.drawRightString(x,H-cell['y']-cell['size'],cell['text'])
            else:c.drawString(x,H-cell['y']-cell['size'],cell['text'])
        c.restoreState();c.showPage()
    c.save();return buf.getvalue()

def render_pdf(invoice,company,doc):
    from decimal import Decimal
    cents=lambda n:f'{Decimal(n or 0)/100:,.2f}'
    outstanding=invoice.total_cents-sum(p.amount_cents for p in invoice.payments)
    return pdf_bytes(invoice,doc,outstanding,cents)

def print_html(invoice,doc):
    from html import escape
    from decimal import Decimal
    cents=lambda n:f'{Decimal(n or 0)/100:,.2f}'
    pages=layout(invoice,doc,invoice.total_cents-sum(p.amount_cents for p in invoice.payments),cents)
    sheets=[]
    for cells in pages:
        texts=''.join(f'<div class="cell" style="left:{c["x"]}px;top:{c["y"]}px;width:{c["width"]}px;font-size:{c["size"]}px;font-weight:{700 if c["bold"] else 400};text-align:{c["align"]}">{escape(c["text"])}</div>' for c in cells)
        masks='' if invoice.currency=='TTD' else '<div class="currency-mask"></div><div class="rate-mask">RATE ('+escape(invoice.currency)+')</div><div class="amount-mask">AMOUNT ('+escape(invoice.currency)+')</div>'
        sheets.append('<section class="sheet"><div class="inner"><img class="stationery" src="/static/mills-blank-invoice.jpg" alt="Mills invoice stationery">'+masks+texts+'</div></section>')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(invoice.number)+' | Print invoice</title><link rel="stylesheet" href="/static/invoice-print.css"><script defer src="/static/invoice-print.js"></script></head><body><nav class="tools"><button id="print-invoice">Print invoice</button><a href="/invoices/'+str(invoice.id)+'/pdf">Download PDF</a><a href="/invoices/'+str(invoice.id)+'">Return to invoice</a></nav>'+''.join(sheets)+'</body></html>'
