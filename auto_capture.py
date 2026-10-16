"""Conservative automatic drafting from paper scans; never automatically issue/post.

High-confidence, arithmetically reconciled scans become drafts without data entry.
Anything ambiguous remains in a secure review queue, not in the ledger.
"""
import re,json,logging
from decimal import Decimal,ROUND_HALF_UP,InvalidOperation
from datetime import date
from sqlalchemy import func
from models import Invoice,InvoiceLine,Contact,Division,Setting
from invoice_tools import InvoiceDocument,active_design
log=logging.getLogger('mills.automatic_capture')
FIELDS=('Plane','Container','E.D.A','B/L #','R.O.E')

def extract_shipments(text):
    lines=[' '.join(line.split()) for line in text.splitlines() if line.strip()]
    patterns={
      'Plane':r'\b(?:plane|aircraft|flight)\s*[:#-]?\s*([^|]{2,36})',
      'Container':r'\bcontainer\s*(?:no|#|number)?\s*[:#-]?\s*([A-Z]{3,5}\d{6,9})',
      'E.D.A':r'\bE\.?D\.?A\.?\s*[:#-]?\s*(\d{1,2}[-/.][A-Za-z]{3,9}[-/.]\d{2,4}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})',
      'B/L #':r'\b(?:B\s*/\s*L|bill\s+of\s+lading)\s*(?:no\.?|#)?\s*[:#-]?\s*([A-Z0-9-]{5,30})',
      'R.O.E':r'\bR\.?O\.?E\.?\s*[:#-]?\s*(TTD|USD|[\d.]{1,16})',
    }
    data={key:'' for key in FIELDS}
    for field,rx in patterns.items():
        for line in lines:
            m=re.search(rx,line,re.I)
            if m:
                value=m.group(1).strip()
                # Header-only lines (e.g. PLANE CONTAINER EDA BL) aren't valid values.
                if value and not re.search(r'\b(?:PLANE|CONTAINER|E\.D\.A|B/L|R\.O\.E)\b',value,re.I):
                    data[field]=value[:70];break
    return data

def enrich_extraction(text,result):
    result['shipment']=extract_shipments(text)
    lines=[' '.join(v.split()) for v in text.splitlines() if v.strip()]
    # Additional paper fields are useful even when we cannot automatically post.
    def nearby(pattern):
        for idx,line in enumerate(lines):
            m=re.search(pattern,line,re.I)
            if m:
                v=line[m.end():].strip(' :#-')
                if v:return v[:180]
                if idx+1<len(lines):return lines[idx+1][:180]
        return ''
    result['customer_address']=nearby(r'\b(?:address|ship\s*to)\s*[:#]?')
    phone=nearby(r'\b(?:contact|telephone|tel|phone)\s*(?:no\.?|#)?\s*[:#]?')
    m=re.search(r'\b(?:\+?1[-\s]?)?(?:\(?\d{3}\)?[-\s]?)?\d{3}[-\s]\d{4}\b',phone)
    result['customer_phone']=m.group(0) if m else ''
    return result

def division_choice(db,result):
    active=db.query(Division).filter(Division.active.is_(True)).all()
    if len(active)==1:return active[0]
    haystack=' '.join(v.get('description','') for v in result.get('lines',[])).lower()
    terms={'skybox':('skybox','sky box','courier locker','package forwarding'),
      'courier':('courier','delivery','last mile'),
      'transport':('transportation','transport','haulage','trucking','freight','container transfer')}
    matches=[]
    for row in active:
        name=(row.name+' '+row.code).lower()
        for group,keywords in terms.items():
            if group in name and any(term in haystack for term in keywords):
                matches.append(row);break
    return matches[0] if len(matches)==1 else None

def ready(result):
    # Require a labelled reference, date, customer, and fully reconciled positive line items.
    if not all(result.get(k) for k in ('reference','issued_on','customer','total')):return False
    if result.get('confidence',0)<75:return False
    if len(result['reference'])>100 or not (2<=len(result['customer'])<=200):return False
    lines=result.get('lines') or []
    if not lines or len(lines)>8:return False
    try:
        amount=Decimal(result['total']);rows=[]
        for item in lines:
            desc=str(item['description'])
            if 'verify' in desc.lower() or len(desc)<3:return False
            q=Decimal(str(item.get('qty') or '1'));u=Decimal(str(item['unit']))
            if not(q.is_finite() and u.is_finite()) or q<=0 or u<=0:return False
            rows.append(q*u)
        return amount>0 and abs(sum(rows)-amount)<=Decimal('.01')
    except (InvalidOperation,TypeError,KeyError):return False

def automatic_draft(db,request,scan,next_number,audit):
    data=json.loads(scan.extraction or '{}')
    if not ready(data):return False
    division=division_choice(db,data)
    if not division:return False
    from photo_import import PaperScan
    ref=str(data['reference']).strip()
    if db.query(InvoiceDocument).filter_by(original_reference=ref).first() or db.query(Invoice).filter_by(number=ref).first():
        scan.error='An invoice with this original number already exists.';return False
    company=db.query(Setting).first()
    if not company:return False
    customer_name=str(data['customer']).strip()
    matches=db.query(Contact).filter(Contact.kind=='customer',func.lower(Contact.name)==customer_name.lower()).all()
    if len(matches)>1:return False
    customer=matches[0] if matches else Contact(kind='customer',name=customer_name)
    if not matches:
        customer.address=str(data.get('customer_address',''))[:1000]
        customer.phone=str(data.get('customer_phone',''))[:80]
        db.add(customer);db.flush()
    issue=date.fromisoformat(data['issued_on']);due=date.fromisoformat(data.get('due_on') or data['issued_on'])
    if due<issue:return False
    currency=data.get('currency','TTD')
    # Never invent historical FX conversion rates; rate 1 only if TTD denominated.
    if currency!='TTD':return False
    entries=[]
    for line in data['lines']:
        qty=int((Decimal(str(line.get('qty','1')))*1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        price=int((Decimal(str(line['unit']))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        amount=int((Decimal(qty)*price/1000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        entries.append((line['description'][:500],qty,price,amount))
    subtotal=sum(x[3] for x in entries)
    if abs(subtotal-int((Decimal(str(data['total']))*100).quantize(Decimal('1'))))>1:return False
    obj=Invoice(number=next_number(db,'invoice',company.invoice_prefix),contact_id=customer.id,
        division_id=division.id,issued_on=issue,due_on=due,currency='TTD',fx_rate='1',
        subtotal_cents=subtotal,tax_bps=0,tax_cents=0,total_cents=subtotal,status='draft',
        memo='Automatically transcribed from original invoice photo. Verify before issuing.',
        created_by=request.state.user.id,
        bill_to_name=customer.name,bill_to_email=customer.email,bill_to_address=customer.address,
        issuer_name=company.company_name,issuer_email=company.business_email,issuer_address=company.address,
        issuer_registration=company.registration_number,issuer_vat_number=company.vat_number)
    db.add(obj);db.flush()
    for desc,qty,price,amount in entries:
        db.add(InvoiceLine(invoice_id=obj.id,description=desc,quantity_thousandths=qty,
                           unit_price_cents=price,amount_cents=amount))
    design=active_design(db);design['issuer_phone']=company.business_phone or ''
    design['labels']=list(FIELDS)
    shipment=data.get('shipment') or {}
    db.add(InvoiceDocument(invoice_id=obj.id,original_reference=ref,source='paper',
        design_snapshot=json.dumps(design),extra_values=json.dumps([shipment.get(k,'') for k in FIELDS])))
    scan.invoice_id=obj.id;scan.status='imported';scan.preview=None
    audit(db,request,'auto drafted paper invoice','invoice',obj.id,'Original '+ref+' / scan '+str(scan.id))
    return True