"""Local OCR with table rectification and spatial line-item matching."""
import io, re, csv, subprocess
from decimal import Decimal
import cv2
import numpy as np
from PIL import Image, ImageOps

CHARGES=['Brokerage','Documentation','Transport','Reimbursement','Duty & VAT','Upliftment','Delivery','Rent','Overtime','Bureau of Standards','Handling charge']
SHIP_LABELS=['Plane','Container','E.D.A','B/L #','R.O.E']

def ocr(image, psm=6):
    out=io.BytesIO();image.save(out,format='PNG')
    p=subprocess.run(['tesseract','stdin','stdout','-l','eng','--psm',str(psm),'tsv'],input=out.getvalue(),capture_output=True,timeout=20)
    if p.returncode:raise ValueError('Could not read the invoice photograph.')
    words=[]
    for r in csv.DictReader(io.StringIO(p.stdout.decode('utf-8','replace')),delimiter='\t'):
        if r.get('text','').strip() and float(r.get('conf',-1))>=35:
            words.append(dict(text=r['text'],x=int(r['left']),y=int(r['top']),w=int(r['width']),h=int(r['height']),conf=float(r['conf']),group=(r['block_num'],r['par_num'],r['line_num'])))
    return words

def rows(words):
    groups=[]
    for w in sorted(words,key=lambda w:w['y']+w['h']/2):
        y=w['y']+w['h']/2
        found=next((g for g in groups if abs(g[0]-y)<max(10,w['h']*.6)),None)
        if found:found[1].append(w)
        else:groups.append([y,[w]])
    return [(y,' '.join(w['text'] for w in sorted(ws,key=lambda w:w['x']))) for y,ws in groups]

def rectified_table(image):
    a=np.array(image);gray=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    bw=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,12)
    contours,_=cv2.findContours(bw,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    h,w=gray.shape
    for c in sorted(contours,key=cv2.contourArea,reverse=True):
        area=cv2.contourArea(c)
        if not .15*w*h<area<.85*w*h:continue
        pts=cv2.approxPolyDP(c,.02*cv2.arcLength(c,True),True).reshape(-1,2)
        if len(pts)!=4:continue
        s=pts.sum(axis=1);d=np.diff(pts,axis=1).ravel()
        box=np.float32([pts[s.argmin()],pts[d.argmin()],pts[s.argmax()],pts[d.argmax()]])
        if box[0,1]<h*.15:continue
        width=max(np.linalg.norm(box[1]-box[0]),np.linalg.norm(box[2]-box[3]))
        height=max(np.linalg.norm(box[3]-box[0]),np.linalg.norm(box[2]-box[1]))
        tw=1800;th=int(tw*height/width)
        if th<400 or th>2400:continue
        matrix=cv2.getPerspectiveTransform(box,np.float32([[0,0],[tw-1,0],[tw-1,th-1],[0,th-1]]))
        warped=cv2.warpPerspective(a,matrix,(tw,th),borderValue=(255,255,255))
        g=cv2.cvtColor(warped,cv2.COLOR_RGB2GRAY)
        clean=cv2.adaptiveThreshold(g,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,15)
        return Image.fromarray(clean),box
    return None,None

def extract(blob, fallback):
    image=ImageOps.exif_transpose(Image.open(io.BytesIO(blob))).convert('RGB')
    image.thumbnail((2600,3400))
    table,box=rectified_table(image)
    if table is None:return fallback
    # Spatial extraction is used only for a recognised Mills-style service-charge table.
    words=ocr(table,11); textrows=rows(words)
    joined='\n'.join(t for y,t in textrows)
    recognized=sum(bool(re.search(re.escape(label),joined,re.I)) for label in CHARGES)
    if recognized<4:return fallback
    from photo_import import extract_fields, normalize_amount
    top=int(min(box[0,1],box[1,1])); w,h=image.size
    head=image.crop((int(w*.54),int(top*.35),int(w*.90),int(top*.99)))
    head=head.resize((head.width*2,head.height*2))
    groups={}
    for word in ocr(head,6):groups.setdefault(word['group'],[]).append(word['text'])
    header='\n'.join(' '.join(v) for v in groups.values())
    fields=extract_fields(header,85)
    lines=[]; total=''; description=''; reference=''
    for y,line in textrows:
        if re.search(r'\bDESCRIPTION\b',line,re.I):description=re.sub(r'^.*?DESCRIPTION\s*:?\s*','',line,flags=re.I).strip(' |')
        if re.match(r'REF\s*#?',line,re.I):reference=line.strip(' |')
        nums=[v for v in words if v['x']>table.width*.76 and abs(v['y']+v['h']/2-y)<18 and re.fullmatch(r'[\d,]+\.\d{2}',v['text'])]
        amount=normalize_amount(nums[-1]['text']) if nums else ''
        if re.search(r'\bTOTAL\b',line,re.I) and amount:total=amount
        for label in CHARGES:
            if re.search(r'\b'+re.escape(label)+r'\b',line,re.I) and amount:
                lines.append({'description':label,'qty':'1','unit':amount})
                break
    # Read shipment values independently of grid lines and charge labels.
    shipment=[]
    for left,right in [(0,.198),(.198,.398),(.398,.584),(.584,.855),(.855,1)]:
        crop=table.crop((int(table.width*left)+7,int(table.height*.052),int(table.width*right)-7,int(table.height*.092)))
        value=' '.join(v['text'] for v in ocr(crop,7)).strip(' |')
        shipment.append(value if re.search(r'[A-Za-z0-9]',value) else '')
    fields['currency']='TTD' if re.search(r'TTD|TTO|TTD',shipment[-1],re.I) else fields['currency']
    address=re.search(r'Address\s*:\s*(.*?)(?=\nContact\s*:|\nPhone\s*:|$)',header,re.I|re.S)
    phone=re.search(r'(?:Contact|Phone)\s*:\s*([+\d ()-]{7,30})',header,re.I)
    email=re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',header)
    fields.update(lines=lines,total=total,address=address.group(1).strip() if address else '',phone=phone.group(1).strip() if phone else '',email=email.group() if email else '',shipment=shipment,description=description,reference_note=reference)
    summed=sum(Decimal(v['unit']) for v in lines)
    complete=all(fields.get(k) for k in ['reference','issued_on','customer','total']) and lines and summed==Decimal(total or '0')
    fields['auto_ready']=bool(complete and recognized>=4 and fields['currency']=='TTD')
    fields['confidence']=90 if complete else 55
    fields['warnings']=[] if complete else ['Some fields or charge amounts could not be read consistently. Check the highlighted draft before saving.']
    return fields
