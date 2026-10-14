"""Mills Multiservices: production security and accounting integrity patch.

Applied during image build. All changes are data-preserving source edits.
No production DB, employee, invoice, or customer information is read.
"""
from pathlib import Path
root = Path(__file__).resolve().parent

def edit(name, replacements):
    file = root / name
    src = file.read_text(encoding='utf-8')
    for old, new in replacements:
        if old not in src:
            if new in src: continue
            raise RuntimeError('Unexpected application version: '+name+' '+old[:60])
        src = src.replace(old,new)
    file.write_text(src,encoding='utf-8')

edit('app.py', [
    ('from sqlalchemy.exc import IntegrityError','from sqlalchemy.exc import IntegrityError\nfrom sqlalchemy.orm import joinedload'),
    ("if not n.is_finite() or n < 0 or (not allow_zero and n == 0): raise ValueError()\n        return int((n * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))",
     """if not n.is_finite() or n < 0 or n > Decimal('1000000000000') or (not allow_zero and n == 0): raise ValueError()
        pennies=n*100
        if pennies!=pennies.to_integral_value():raise ValueError('Amounts must have at most two decimal places.')
        result=int(pennies)
        if not allow_zero and result==0:raise ValueError()
        return result"""),
    ("if setting and not request.state.user and path not in ('/login',): return redirect('/login')\n    response = await call_next(request)",
     """if setting and not request.state.user and path not in ('/login',): return redirect('/login')
    # Confidential records are protected server-side, not only hidden from navigation.
    if request.state.user:
        role=request.state.user.role
        if role=='staff' and path=='/':return redirect('/invoices')
        protected_people=path=='/employees' or path.startswith('/employees/') or path=='/payroll' or path.startswith('/payroll/')
        protected_finance=(path=='/reports' or path=='/ledger' or path=='/expenses' or path.startswith('/expenses/') or
            path.startswith('/export/') or path.startswith('/invoices/batch/'))
        if ((protected_people or path.startswith('/invoices/batch/')) and role not in ('admin','accountant')) or (protected_finance and role=='staff'):
            return HTMLResponse('Forbidden: insufficient role permissions.',status_code=403)
    response = await call_next(request)"""),
    ("<p>{e.detail}</p>","<p>{xml_escape(str(e.detail))}</p>"),
    ("users=db.query(User).order_by(User.id).all();logs=db.query(Audit).order_by(desc(Audit.id)).limit(50).all()",
     "users=db.query(User).order_by(User.id).all();logs=db.query(Audit).options(joinedload(Audit.user)).order_by(desc(Audit.id)).limit(50).all()"),
    ("obj=db.get(Invoice,invoice_id)\n        if not obj or obj.status", "obj=db.query(Invoice).filter_by(id=invoice_id).with_for_update().first()\n        if not obj or obj.status"),
    ("obj=db.get(Expense,expense_id)\n        if not obj or obj.status", "obj=db.query(Expense).filter_by(id=expense_id).with_for_update().first()\n        if not obj or obj.status"),
    ("obj=db.get(Payroll,payroll_id)\n        if not obj or obj.status", "obj=db.query(Payroll).filter_by(id=payroll_id).with_for_update().first()\n        if not obj or obj.status"),
    ("        when=parse_date(paid_on)\n        p=Payment(payroll_id=obj.id", """        when=parse_date(paid_on)
        if when < obj.pay_date: raise HTTPException(400,'Payment cannot precede payroll date.')
        if obj.net_cents == 0:
            obj.status='paid';audit(db,request,'settled zero net pay','payroll',obj.id,obj.employee.full_name);db.commit()
            flash(request,'Zero net pay recorded. No bank movement posted.','success')
            return redirect('/payroll')
        p=Payment(payroll_id=obj.id"""),
    ("@app.get('/export/{kind}.csv')\ndef export", """class SafeCSVWriter:
    def __init__(self, output): self.writer=csv.writer(output)
    def writerow(self, values):
        def safe(value):
            if isinstance(value,str):
                v=value.lstrip()
                if v and (v[0] in ('=','+','@') or
                          (v[0]=='-' and (len(v)==1 or not v[1].isdigit()))):
                    return "'"+value
            return value
        return self.writer.writerow([safe(value) for value in values])

@app.get('/export/{kind}.csv')
def export"""),
    ("buf=io.StringIO();w=csv.writer(buf)\n    with SessionLocal() as db:\n        if kind=='invoices':",
     "buf=io.StringIO();w=SafeCSVWriter(buf)\n    with SessionLocal() as db:\n        if kind=='invoices':"),
])

edit('templates/base.html', [
    ('<a class="nav-item {% if nav==\'dashboard\' %}active{% endif %}" href="/"><svg><use href="#i-grid"/></svg>Overview</a>',
     '{% if user.role!=\'staff\' %}<a class="nav-item {% if nav==\'dashboard\' %}active{% endif %}" href="/"><svg><use href="#i-grid"/></svg>Overview</a>{% endif %}'),
    ('<a class="nav-item {% if nav==\'batch\' %}active{% endif %}" href="/invoices/batch/upload"><svg><use href="#i-box"/></svg>Skybox batch billing</a>',
     '{% if user.role in [\'admin\',\'accountant\'] %}<a class="nav-item {% if nav==\'batch\' %}active{% endif %}" href="/invoices/batch/upload"><svg><use href="#i-box"/></svg>Skybox batch billing</a>{% endif %}'),
    ('<a class="nav-item {% if nav==\'expenses\' %}active{% endif %}" href="/expenses"><svg><use href="#i-wallet"/></svg>Bills & expenses</a>',
     '{% if user.role!=\'staff\' %}<a class="nav-item {% if nav==\'expenses\' %}active{% endif %}" href="/expenses"><svg><use href="#i-wallet"/></svg>Bills & expenses</a>{% endif %}'),
    ('<div class="nav-label">FINANCIAL MANAGEMENT</div>',
     '{% if user.role!=\'staff\' %}<div class="nav-label">FINANCIAL MANAGEMENT</div>{% endif %}'),
    ('<a class="nav-item {% if nav==\'reports\' %}active{% endif %}" href="/reports"><svg><use href="#i-chart"/></svg>Financial reports</a>',
     '{% if user.role!=\'staff\' %}<a class="nav-item {% if nav==\'reports\' %}active{% endif %}" href="/reports"><svg><use href="#i-chart"/></svg>Financial reports</a>{% endif %}'),
    ('<a class="nav-item {% if nav==\'ledger\' %}active{% endif %}" href="/ledger"><svg><use href="#i-lines"/></svg>General ledger</a>',
     '{% if user.role!=\'staff\' %}<a class="nav-item {% if nav==\'ledger\' %}active{% endif %}" href="/ledger"><svg><use href="#i-lines"/></svg>General ledger</a>{% endif %}'),
    ('<div class="nav-label">PEOPLE</div>',
     '{% if user.role in [\'admin\',\'accountant\'] %}<div class="nav-label">PEOPLE</div>{% endif %}'),
    ('<a class="nav-item {% if nav==\'employees\' %}active{% endif %}" href="/employees"><svg><use href="#i-users"/></svg>Employees</a>',
     '{% if user.role in [\'admin\',\'accountant\'] %}<a class="nav-item {% if nav==\'employees\' %}active{% endif %}" href="/employees"><svg><use href="#i-users"/></svg>Employees</a>{% endif %}'),
    ('<a class="nav-item {% if nav==\'payroll\' %}active{% endif %}" href="/payroll"><svg><use href="#i-wallet"/></svg>Payroll records</a>',
     '{% if user.role in [\'admin\',\'accountant\'] %}<a class="nav-item {% if nav==\'payroll\' %}active{% endif %}" href="/payroll"><svg><use href="#i-wallet"/></svg>Payroll records</a>{% endif %}'),
])
print('Mills Multiservices production audit fixes applied.')
