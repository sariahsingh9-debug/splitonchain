"""Deploy private photo-invoice OCR as an additive upgrade. Preserve ledger data."""
from pathlib import Path
root=Path(__file__).resolve().parent
app=root/"app.py"
txt=app.read_text("utf-8")
marker="# Automatic private OCR of multiple paper invoices"
if marker not in txt:
    txt+="""


# Automatic private OCR of multiple paper invoices with mandatory human review.
from photo_import import register as register_photo_import
register_photo_import(app, {
    'render': render, 'require': require, 'check_csrf': check_csrf, 'redirect': redirect,
    'flash': flash, 'audit': audit, 'parse_date': parse_date, 'money_cents': money_cents,
    'fx_value': fx_value, 'next_number': next_number,
})
"""
    app.write_text(txt,"utf-8")
base=root/"templates/base.html"
s=base.read_text("utf-8")
nav="""   {% if user.role in ['admin','accountant'] %}<a class="nav-item {% if nav=='photos' %}active{% endif %}" href="/paper-invoices/photos"><svg><use href="#i-file"/></svg>Scan paper invoice photos</a>{% endif %}
"""
needle="""   {% if user.role in ['admin','accountant'] %}<a class="nav-item {% if nav=='paper' %}active{% endif %}" href="/paper-invoices/new"><svg><use href="#i-file"/></svg>Enter paper invoice</a>{% endif %}
"""
if nav not in s:
    if needle not in s:raise RuntimeError("Invoice navigation anchor missing")
    s=s.replace(needle,needle+nav)
s=s.replace("/static/app.css?v=1.4","/static/app.css?v=1.5").replace("/static/app.js?v=1.0","/static/app.js?v=1.1")
base.write_text(s,"utf-8")
template=root/"templates/photo_import.html"
template.write_bytes((root/"photo_import_template.html").read_bytes())
requirements=root/"requirements.txt"
req=requirements.read_text("utf-8")
if "Pillow" not in req:
    requirements.write_text(req+"\nPillow>=10.4,<13\n","utf-8")
js=root/"static/app.js"
script=js.read_text("utf-8")
if "invoice-photos" not in script:
    script+="""
// Private photo invoice upload: filenames and processing state.
const paperInput = document.getElementById('invoice-photos');
if (paperInput) {
  const details=document.getElementById('photo-selected');
  const button=document.getElementById('photo-process');
  paperInput.addEventListener('change',()=>{
    const files=Array.from(paperInput.files||[]);
    details.textContent=files.length ? files.length+' photo(s): '+files.map(f=>f.name).join(' · ') : 'No photos selected';
    if(button)button.disabled=!files.length||files.length>12;
  });
  const form=document.getElementById('photo-import-form');
  form?.addEventListener('submit',()=>{if(button){button.disabled=true;button.textContent='Reading photographs… please wait';}});
}
"""
    js.write_text(script,"utf-8")
css=root/"static/app.css"
style=css.read_text("utf-8")
if "/* Invoice OCR v4 */" not in style:
    style+="""
/* Invoice OCR v4 */
.photo-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 20px}
.photo-summary>div{border:1px solid #e4edf5;background:#fff;border-radius:12px;display:flex;align-items:center;gap:12px;padding:14px;font-size:11px;color:#4b6075;font-weight:700}
.photo-summary strong{color:#13749a;font-size:17px}
.photo-upload-card{margin-bottom:30px}.photo-upload-body{padding:5px 24px 24px}
.photo-file-zone{border:2px dashed #abc5d9;background:#f7fbfd;border-radius:15px;padding:26px;display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;color:#32536b;cursor:pointer}
.photo-file-zone:hover{background:#eef9fb;border-color:#389eaf}
.photo-file-zone svg{width:27px;height:27px}.photo-file-zone small{font-size:11px;color:#7591a5}
.photo-file-zone input{font-size:12px;padding:8px;max-width:100%}
.photo-selected{font-size:11px;color:#426278;padding:12px 0}
.photo-privacy-note{display:flex;gap:12px;margin-top:20px;border-top:1px solid #e4edf4;padding-top:17px;font-size:11px;color:#607888;line-height:1.6}
.photo-privacy-note svg{min-width:18px;width:18px}.photo-privacy-note p{margin:0}
.photo-review-header,.photo-review-title{display:flex;justify-content:space-between;align-items:center;gap:16px}
.photo-review-header{margin:25px 0 18px}.photo-review-header h2{margin:5px 0}.photo-review-header p{font-size:12px;color:#8495a4}
.photo-review-card{overflow:hidden;margin-bottom:20px}.photo-review-title{padding:18px 23px;border-bottom:1px solid #e7eef5}
.photo-review-title h3{overflow-wrap:anywhere;margin:5px 0}.photo-score{font-size:11px;color:#668096}
.photo-review-cols{display:grid;grid-template-columns:minmax(220px,38%) 1fr;gap:24px;padding:24px}
.photo-preview-col{border-right:1px solid #e8edf4;padding-right:22px;min-width:0}.photo-preview-col img{display:block;width:100%;max-height:720px;object-fit:contain;object-position:top;border:1px solid #dde7ef;border-radius:10px}
.photo-preview-col p,.photo-safe-note{font-size:11px;color:#8595a4;line-height:1.6}
.photo-fields-form{min-width:0}.photo-fields-form h4,.photo-preview-col h4{font-size:13px;color:#25384f;margin:0 0 14px}
.photo-fields-form h4 small{font-size:11px;color:#5b9ab3}
.photo-warnings{border:1px solid #f0dba9;background:#fffbf2;padding:13px;border-radius:9px;margin-bottom:16px;font-size:11px;color:#8a6332}.photo-warnings ul{padding-left:18px}
.photo-fields-form .form-grid{margin:0 0 18px}.photo-fields-form input,.photo-fields-form select,.photo-fields-form textarea{max-width:100%}
.photo-line-label,.photo-line-fields{display:grid;grid-template-columns:minmax(96px,1fr) 70px 100px;gap:7px;margin-bottom:7px}
.photo-line-fields input{min-width:0}.photo-line-label{font-size:10px;color:#728697;font-weight:800}
.photo-detected-total{background:#f0f7fb;border:1px solid #e3edf6;padding:12px;border-radius:9px;margin:14px 0;font-size:12px;color:#497084}
.photo-detected-total strong{font-size:17px;color:#163f60}.photo-detected-total small{display:block;margin-top:7px;font-size:10px}
.photo-check{display:flex;gap:9px;align-items:flex-start;margin:13px 0;font-size:11px;color:#586f82}.photo-check input{width:17px;height:17px;flex-shrink:0}
.photo-finished,.photo-empty{padding:36px;text-align:center;color:#668096}.photo-empty h3{color:#304c62}
@media(max-width:1100px){.photo-review-cols{grid-template-columns:1fr}.photo-preview-col{border-right:0;border-bottom:1px solid #e7eef4;padding:0 0 20px}.photo-preview-col img{max-width:410px;max-height:400px}.photo-summary{grid-template-columns:1fr 1fr}}
@media(max-width:650px){.photo-summary{gap:8px}.photo-summary>div{padding:10px;font-size:10px}.photo-review-cols{padding:15px}.photo-review-title{padding:15px;flex-wrap:wrap}.photo-line-label,.photo-line-fields{grid-template-columns:minmax(80px,1fr) 50px 85px;gap:5px}.photo-file-zone{padding:18px 8px}.photo-upload-body{padding:0 14px 18px}}
"""
    css.write_text(style,"utf-8")
print("Photo-import extension installed.")
