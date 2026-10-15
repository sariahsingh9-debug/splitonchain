"""Multi-photo historical paper invoice capture, OCR, human review, and draft import.

Images are never sent to an external service. A small private review thumbnail is stored
until approved or deleted; original upload bytes and OCR text are not stored. No books are
changed until an authorized accountant manually reviews and imports each extracted record.
"""
import csv
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any
from PIL import Image, ImageOps, ImageEnhance, UnidentifiedImageError
from fastapi import Request, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from sqlalchemy import Column, Integer, String, Text, LargeBinary, DateTime, ForeignKey
from sqlalchemy.exc import IntegrityError
from models import (Base, SessionLocal, engine, Setting, Invoice, InvoiceLine, Contact, Division,
                    utcnow)
from invoice_tools import InvoiceDocument, active_design

log = logging.getLogger('mills.photo_import')
MAX_COUNT=12
MAX_EACH=8*1024*1024
MAX_TOTAL=60*1024*1024
Image.MAX_IMAGE_PIXELS=16_000_000
SUPPORTED={'JPEG','PNG','WEBP'}

class PaperScan(Base):
    __tablename__='paper_photo_scans'
    id=Column(Integer,primary_key=True)
    created_by=Column(Integer,ForeignKey('users.id'),nullable=False)
    filename=Column(String(180),nullable=False)
    content_hash=Column(String(64),nullable=False,index=True)
    preview=Column(LargeBinary)
    extraction=Column(Text,nullable=False,default='{}')
    quality=Column(Integer,default=0)
    status=Column(String(16),nullable=False,default='review')
    invoice_id=Column(Integer,ForeignKey('invoices.id'),nullable=True)
    error=Column(String(400),default='')
    created_at=Column(DateTime,default=utcnow)

DATE_RX=r'(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[\-/.]\d{1,2}[\-/.]\d{2,4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[A-Za-z]*\s+\d{4})'
CURRENCIES={'TT$':'TTD','TTD':'TTD','T.T.':'TTD','USD':'USD','US$':'USD',
            'EUR':'EUR','GBP':'GBP','CAD':'CAD','EC$':'XCD'}
MONEY_TOKEN=re.compile(r'(?<![A-Za-z0-9])(?:TT\$|US\$|USD|TTD|\$)?\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|(?<![A-Za-z0-9])(?:TT\$|US\$|USD|TTD|\$)?\s*\d{4,10}(?:\.\d{1,2})?')
AMOUNT_LABEL=re.compile(r'\b(grand\s*total|total\s*due|amount\s*due|balance\s*due|invoice\s*total|total)\b',re.I)
SKIP_LABEL=re.compile(r'\b(sub\s*total|vat|tax|discount|change|shipping\s*date|account\s*number|paid\s*to\s*date)\b',re.I)


def normalize_amount(s:str):
    s=re.sub(r'(?i)(?:TTD|USD|US\$|TT\$|GBP|EUR|CAD|\$|\s)','',s or '')
    if ',' in s and '.' not in s:
        if re.fullmatch(r'\d+,\d{2}',s):s=s.replace(',','.')
        else:s=s.replace(',','')
    else:s=s.replace(',','')
    try:
        v=Decimal(s)
        if not v.is_finite() or v<0 or v>Decimal('1000000000000'):return ''
        return str(v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    except (InvalidOperation,ValueError):return ''


def parse_ocr_date(value:str):
    v=(value or '').strip().replace('.','/').replace('\\','/').replace('–','-')
    from datetime import datetime, date
    for fmt in ('%Y-%m-%d','%Y/%m/%d','%d/%m/%Y','%d-%m-%Y','%d/%m/%y','%d-%m-%y',
                '%d %B %Y','%d %b %Y'):
        try:
            d=datetime.strptime(v,fmt).date()
            return d.isoformat() if 1900<=d.year<=date.today().year+10 else ''
        except ValueError:pass
    return ''


def field_near(lines,pattern, max_lookahead=1):
    rule=re.compile(pattern,re.I)
    for i,line in enumerate(lines):
        m=rule.search(line)
        if m:
            remainder=re.sub(r'^[\s:#.\-]+','',line[m.end():]).strip()
            if remainder:return remainder
            for next_line in lines[i+1:i+1+max_lookahead]:
                if next_line.strip():return next_line.strip()
    return ''


def find_labelled_date(lines, pattern):
    for i,line in enumerate(lines):
        if re.search(pattern,line,re.I):
            m=re.search(DATE_RX,line,re.I)
            if m:
                date=parse_ocr_date(m.group())
                if date:return date
            if i+1<len(lines):
                m=re.search(DATE_RX,lines[i+1],re.I)
                if m:
                    date=parse_ocr_date(m.group())
                    if date:return date
    return ''


def extract_fields(text:str, avg_conf:int=0):
    lines=[' '.join(x.split()) for x in text.splitlines() if x.strip()]
    invoice_ref=field_near(lines,r'\b(?:invoice|inv|bill)\s*(?:no\.?|number|#|ref(?:erence)?\.?|:)\s*',0)
    if not invoice_ref:
        invoice_ref=field_near(lines,r'^\s*(?:invoice|inv)\s*#\s*',0)
    if invoice_ref:
        invoice_ref=re.split(r'\s{2,}|\s+(?:date|customer|total|due)\b',invoice_ref,1,flags=re.I)[0]
        invoice_ref=re.sub(r'^[#: ]+','',invoice_ref)[:100]
        if len(invoice_ref.split())>4 or not re.search(r'[A-Za-z0-9]',invoice_ref):invoice_ref=''
    issue=find_labelled_date(lines,r'\b(invoice\s*date|issue\s*date|date\s*issued|dated)\b')
    due=find_labelled_date(lines,r'\b(due\s*date|payment\s*due|pay\s*by)\b')
    if not issue:issue=find_labelled_date(lines,r'\bdate\b')
    currency=''
    blob=' '.join(lines)
    if re.search(r'\b(?:TTD|TT\$|T\.T\.)\b|TT\$',blob,re.I):currency='TTD'
    elif re.search(r'\bUSD\b|US\$',blob,re.I):currency='USD'
    else:
        for curr in ('EUR','GBP','CAD'):
            if re.search(r'\b'+curr+r'\b',blob,re.I):currency=curr;break
    customer=field_near(lines,r'\b(?:bill(?:ed)?\s*to|invoice\s*to|customer\s*(?:name)?|sold\s*to|client\s*(?:name)?)\s*[:#-]?\s*',2)
    customer=re.sub(r'^[:#\s-]+','',customer).strip()
    if customer and (len(customer)>180 or re.search(r'\b(?:invoice|date|telephone|address|total|vat|phone)\b',customer,re.I)):
        customer=''
    total=''; amount_line=''; amount_candidates=[]
    for line in lines:
        if AMOUNT_LABEL.search(line) and not SKIP_LABEL.search(line):
            suffix=line[AMOUNT_LABEL.search(line).end():]
            matches=list(MONEY_TOKEN.finditer(suffix))
            if matches:
                amount=normalize_amount(matches[-1].group())
                if amount:
                    amount_candidates.append((amount,line))
    if amount_candidates:total,amount_line=amount_candidates[-1]
    # Use labelled totals only. Picking the largest random number can mistake a waybill for money.
    descriptions=[]
    for line in lines:
        if len(descriptions)>=6:break
        if re.search(r'\b(invoice|customer|date|payment|subtotal|total|amount due|invoice no|reference|bill to|tax|vat|address|phone|tel|email)\b',line,re.I):continue
        m=list(MONEY_TOKEN.finditer(line))
        if not m:continue
        words=line[:m[-1].start()].strip(' .:-')
        if len(words)<4 or len(words)>120 or not re.search(r'[a-zA-Z]{3}',words):continue
        amount=normalize_amount(m[-1].group())
        if not amount or Decimal(amount)<=0:continue
        # Avoid interpreting address/telephone fields as invoice services.
        if re.search(r'\b(street|avenue|road|drive|city|post code|fax|phone)\b',words,re.I):continue
        descriptions.append({'description':words[:130],'qty':'1','unit':amount})
    if not descriptions and total:
        descriptions=[{'description':'Charges from original paper invoice — verify service description',
                      'qty':'1','unit':total}]
    # Most OCR line items do not reliably distinguish pre-tax amounts; reviewer must reconcile.
    if descriptions and total:
        item_sum=sum(Decimal(r['unit']) for r in descriptions)
        if abs(item_sum-Decimal(total))>Decimal('.01'):
            descriptions=[{'description':'Charges from original paper invoice — verify line items',
                          'qty':'1','unit':total}]
    issues=[]
    if not invoice_ref:issues.append('Original invoice number was not confidently found.')
    if not issue:issues.append('Invoice date needs manual verification.')
    if not customer:issues.append('Customer name needs manual verification.')
    if not total:issues.append('Total amount was not confidently found; enter it manually.')
    if not currency:issues.append('Currency was not clearly labelled; TTD is a default only.')
    if avg_conf<55:issues.append('Photo text is difficult to read; check every field against the paper.')
    if not due:issues.append('Due date not visible; check whether it was the same as invoice date.')
    quality=max(0,min(100,round(avg_conf*.60+7*(5-sum(not bool(x) for x in (invoice_ref,issue,customer,total,currency))) )))
    return {'reference':invoice_ref,'issued_on':issue,'due_on':due or issue,'customer':customer,
            'currency':currency or 'TTD','total':total,'lines':descriptions[:8],
            'confidence':quality,'warnings':issues,'amount_line':amount_line[:180]}


def read_image_bytes(blob:bytes):
    if not blob or len(blob)>MAX_EACH:raise ValueError('Image is empty or larger than 8 MB.')
    try:
        src=Image.open(io.BytesIO(blob))
        if src.format not in SUPPORTED:raise ValueError('Only JPG, PNG and WebP photographs are accepted.')
        src.verify()
        src=Image.open(io.BytesIO(blob))
        src=ImageOps.exif_transpose(src).convert('RGB')
        if src.width<250 or src.height<250:raise ValueError('Photo resolution is too low to read an invoice.')
        if src.width*src.height>16_000_000:raise ValueError('Photo resolution exceeds the 16-megapixel limit.')
        preview=src.copy(); preview.thumbnail((950,1250))
        pb=io.BytesIO();preview.save(pb,format='JPEG',quality=69,optimize=True)
        if len(pb.getvalue())>350_000:
            preview.thumbnail((700,1000));pb=io.BytesIO();preview.save(pb,format='JPEG',quality=55,optimize=True)
        working=src.copy(); working.thumbnail((2600,3200))
        if working.width<1300:
            factor=min(2,1300/working.width)
            working=working.resize((int(working.width*factor),int(working.height*factor)))
        working=ImageOps.autocontrast(ImageOps.grayscale(working))
        working=ImageEnhance.Contrast(working).enhance(1.2)
        out=io.BytesIO();working.save(out,format='PNG')
        return out.getvalue(),pb.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValueError('Photo is damaged or not a supported image.') from e


def run_tesseract(image_png:bytes):
    if not shutil.which('tesseract'):
        raise RuntimeError('Invoice photo reading service is unavailable. Contact the administrator.')
    # Capturing in a subprocess prevents a malformed file from keeping the worker busy forever.
    cmd=['tesseract','stdin','stdout','-l','eng','--psm','6','tsv']
    process=subprocess.run(cmd,input=image_png,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=14,check=False)
    if process.returncode!=0:raise ValueError('Could not read the photo. Please retake it in good lighting.')
    reader=csv.DictReader(io.StringIO(process.stdout.decode('utf-8','replace')),delimiter='\t')
    groups={}; confidence=[]
    for row in reader:
        text=(row.get('text') or '').strip()
        if not text:continue
        key=(row.get('block_num'),row.get('par_num'),row.get('line_num'))
        groups.setdefault(key,[]).append(text)
        try:
            conf=float(row.get('conf',-1))
            if conf>=0:confidence.append(conf)
        except (ValueError,TypeError):pass
    lines=[' '.join(items) for items in groups.values()]
    return '\n'.join(lines),round(sum(confidence)/len(confidence)) if confidence else 0


def scan_one(filename:str, blob:bytes):
    work,preview=read_image_bytes(blob)
    try:text,quality=run_tesseract(work)
    except subprocess.TimeoutExpired as e:raise ValueError('Photo analysis timed out; try a clearer picture.') from e
    result=extract_fields(text,quality)
    return preview,result


def register(app, helpers):
    render,require,check_csrf,redirect,flash,audit=tuple(helpers[k] for k in ('render','require','check_csrf','redirect','flash','audit'))
    parse_date=helpers['parse_date'];money_cents=helpers['money_cents'];fx_value=helpers['fx_value'];next_number=helpers['next_number']
    # Additive schema only. There is no data migration or modification of existing invoice tables.
    Base.metadata.create_all(engine,tables=[PaperScan.__table__])

    @app.get('/paper-invoices/photos')
    def home(request:Request):
        require(request,'admin','accountant')
        with SessionLocal() as db:
            scans=db.query(PaperScan).order_by(PaperScan.id.desc()).limit(80).all()
            contacts=db.query(Contact).filter_by(kind='customer').order_by(Contact.name).all()
            divisions=db.query(Division).filter_by(active=True).order_by(Division.name).all()
            count=db.query(PaperScan).filter_by(status='review').count()
            # Convert from SQLAlchemy objects to simple dicts before session closes.
            rows=[{'id':s.id,'filename':s.filename,'data':json.loads(s.extraction or '{}'),
                   'status':s.status,'invoice_id':s.invoice_id,'error':s.error,
                   'created_at':s.created_at} for s in scans]
        return render(request,'photo_import.html',nav='photos',scans=rows,contacts=contacts,
                      divisions=divisions,pending=count,ocr_ready=bool(shutil.which('tesseract')))

    @app.post('/paper-invoices/photos')
    async def upload(request:Request, csrf:str=Form(...), photos:list[UploadFile]=File(...)):
        require(request,'admin','accountant');check_csrf(request,csrf)
        if not 1<=len(photos)<=MAX_COUNT:
            flash(request,'Choose between 1 and 12 photographs per upload.','error');return redirect('/paper-invoices/photos')
        submitted=[];total=0
        for photo in photos:
            safe_name=Path((photo.filename or 'Photo').replace('\\','/')).name[:180]
            data=await photo.read(MAX_EACH+1)
            total+=len(data)
            if len(data)>MAX_EACH or total>MAX_TOTAL:
                flash(request,'Images must be under 8 MB each, and the batch under 60 MB.','error');return redirect('/paper-invoices/photos')
            submitted.append((safe_name,data))
        # OCR on bounded workers, with no calls to third-party AI services.
        def process(item):
            fname,raw=item
            try:
                thumbnail,extraction=scan_one(fname,raw)
                return (fname,hashlib.sha256(raw).hexdigest(),thumbnail,extraction,'')
            except (ValueError,RuntimeError) as exc:
                return (fname,hashlib.sha256(raw).hexdigest(),None,{},str(exc)[:300])
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(process,submitted))
        recorded=0;failures=[]
        with SessionLocal() as db:
            for fname,digest,thumb,data,error in results:
                if db.query(PaperScan).filter_by(content_hash=digest,status='review').first():
                    failures.append(f'{fname}: already in review queue');continue
                if error:
                    failures.append(f'{fname}: {error}');continue
                db.add(PaperScan(created_by=request.state.user.id,filename=fname,content_hash=digest,
                                 preview=thumb,extraction=json.dumps(data),quality=int(data['confidence'])))
                recorded+=1
            if recorded:audit(db,request,'scanned invoices','photo import',None,f'{recorded} private invoice previews queued')
            db.commit()
        if recorded:flash(request,f'{recorded} invoice photo(s) read. Review and correct every result before saving any draft.','success')
        if failures:log.info('Some paper-photo uploads were rejected (%s).',len(failures))
        return redirect('/paper-invoices/photos'+('?notices='+str(len(failures)) if failures else ''))

    @app.get('/paper-invoices/photos/{scan_id}/preview')
    def preview(request:Request, scan_id:int):
        require(request,'admin','accountant')
        with SessionLocal() as db:
            scan=db.get(PaperScan,scan_id)
            if not scan or not scan.preview:raise HTTPException(404,'The source photo is no longer available.')
            return Response(scan.preview,media_type='image/jpeg',headers={'Cache-Control':'no-store','Content-Disposition':'inline'})

    @app.post('/paper-invoices/photos/{scan_id}/delete')
    def delete(request:Request,scan_id:int,csrf:str=Form(...)):
        require(request,'admin','accountant');check_csrf(request,csrf)
        with SessionLocal() as db:
            row=db.query(PaperScan).filter_by(id=scan_id).with_for_update().first()
            if not row:raise HTTPException(404)
            if row.status!='review':raise HTTPException(400,'Completed scans cannot be removed from audit history.')
            db.delete(row);audit(db,request,'removed pending scan','photo import',scan_id,'Discarded unapproved invoice preview');db.commit()
        flash(request,'Pending photo removed without creating an invoice.','success')
        return redirect('/paper-invoices/photos')

    @app.post('/paper-invoices/photos/{scan_id}/draft')
    async def save_draft(request:Request,scan_id:int):
        require(request,'admin','accountant')
        form=await request.form();check_csrf(request,form.get('csrf'))
        if form.get('verified')!='yes':
            flash(request,'Confirm that every field was checked against the original photo.','error');return redirect('/paper-invoices/photos#scan-'+str(scan_id))
        try:
            ref=str(form.get('reference','')).strip()
            if not ref or len(ref)>100:raise ValueError('Enter the original paper invoice number (maximum 100 characters).')
            issued=parse_date(str(form.get('issued_on','')))
            due=parse_date(str(form.get('due_on','')))
            if due<issued:raise ValueError('Due date cannot be before invoice date.')
            currency=str(form.get('currency','TTD')).upper()
            if currency not in ('TTD','USD','EUR','GBP','CAD'):raise ValueError('Select a supported currency.')
            rate=fx_value(form.get('fx_rate','1'),currency)
            division_id=int(form.get('division_id') or 0)
            contact_id=int(form.get('contact_id') or 0)
            new_name=str(form.get('new_contact_name') or '').strip()
            if not contact_id and not (2<=len(new_name)<=200):raise ValueError('Select a customer or enter the customer name from the paper invoice.')
            tax_pct=Decimal(str(form.get('tax_percent','0')))
            if not tax_pct.is_finite() or tax_pct<0 or tax_pct>100:raise ValueError('Enter a valid tax percentage.')
            tax_bps=int((tax_pct*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            lines=[]
            for n in range(1,9):
                desc=str(form.get(f'desc_{n}','')).strip()
                if not desc:continue
                qty=Decimal(str(form.get(f'qty_{n}','1')))
                if not qty.is_finite() or qty<=0 or qty>100000:raise ValueError('Check each line-item quantity.')
                qty_1000=int((qty*1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                if qty_1000<=0:raise ValueError('Quantity is too small.')
                unit=money_cents(form.get(f'unit_{n}','0'))
                amount=int((Decimal(qty_1000)*unit/1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                if amount<=0:raise ValueError('Each line needs a positive amount.')
                lines.append((desc[:500],qty_1000,unit,amount))
            if not lines:raise ValueError('Enter at least one verified service and price.')
            subtotal=sum(r[3] for r in lines)
            vat=int((Decimal(subtotal)*tax_bps/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            expected=str(form.get('scanned_total','')).strip()
            if expected:
                total_expected=money_cents(expected)
                if abs(total_expected-(subtotal+vat))>2 and form.get('override_amount')!='yes':
                    raise ValueError('Calculated total does not match the photographed total. Correct the lines or explicitly confirm the difference.')
            memo=str(form.get('memo',''))[:2000]
            with SessionLocal() as db:
                row=db.query(PaperScan).filter_by(id=scan_id).with_for_update().first()
                if not row or row.status!='review':raise ValueError('This photo was already imported or removed.')
                if db.query(InvoiceDocument).filter_by(original_reference=ref).first() or db.query(Invoice).filter_by(number=ref).first():
                    raise ValueError('An invoice with this original number has already been recorded.')
                division=db.get(Division,division_id)
                if not division or not division.active:raise ValueError('Choose an active business division.')
                if contact_id:
                    customer=db.get(Contact,contact_id)
                    if not customer or customer.kind!='customer':raise ValueError('Choose a customer.')
                else:
                    customer=db.query(Contact).filter(Contact.kind=='customer',Contact.name.ilike(new_name)).first()
                    if not customer:
                        customer=Contact(name=new_name,kind='customer');db.add(customer);db.flush()
                settings=db.query(Setting).first()
                if not settings:raise ValueError('Company has not been configured.')
                invoice=Invoice(number=next_number(db,'invoice',settings.invoice_prefix),contact_id=customer.id,
                    division_id=division.id,issued_on=issued,due_on=due,currency=currency,fx_rate=str(rate),
                    subtotal_cents=subtotal,tax_bps=tax_bps,tax_cents=vat,total_cents=subtotal+vat,
                    status='draft',memo=memo,created_by=request.state.user.id,
                    bill_to_name=customer.name,bill_to_email=customer.email,bill_to_address=customer.address,
                    issuer_name=settings.company_name,issuer_email=settings.business_email,issuer_address=settings.address,
                    issuer_registration=settings.registration_number,issuer_vat_number=settings.vat_number)
                db.add(invoice);db.flush()
                for desc,qty,unit,amount in lines:
                    db.add(InvoiceLine(invoice_id=invoice.id,description=desc,quantity_thousandths=qty,
                                       unit_price_cents=unit,amount_cents=amount))
                design=active_design(db)
                design['issuer_phone']=settings.business_phone or ''
                db.add(InvoiceDocument(invoice_id=invoice.id,original_reference=ref,source='paper',
                                       design_snapshot=json.dumps(design),extra_values=json.dumps(['','','',''])))
                row.invoice_id=invoice.id;row.status='imported';row.preview=None
                audit(db,request,'approved scanned paper invoice','invoice',invoice.id,
                      f'{invoice.number} original {ref}; saved as draft from scan {scan_id}')
                db.commit()
                created_id=invoice.id
        except (ValueError,TypeError,InvalidOperation,IntegrityError) as exc:
            log.info('Photo-import draft validation rejected scan id %s',scan_id)
            flash(request,'Duplicate original invoice.' if isinstance(exc,IntegrityError) else str(exc),'error')
            return redirect('/paper-invoices/photos#scan-'+str(scan_id))
        flash(request,'Reviewed paper invoice saved as a draft. No financial posting was made.','success')
        return redirect('/invoices/'+str(created_id))