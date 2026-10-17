"""One-time, explicitly requested login-address correction. Password is untouched."""
import os,logging
from models import SessionLocal,User,Audit
from sqlalchemy import func
log=logging.getLogger('mills.account_migration')
def apply():
    old=os.getenv('MILLS_LOGIN_EMAIL_OLD','').strip().lower()
    new=os.getenv('MILLS_LOGIN_EMAIL_NEW','').strip().lower()
    name=os.getenv('MILLS_LOGIN_ACCOUNT_NAME','').strip()
    if not old or not new or not name:return
    if '@' not in new or len(new)>200:raise RuntimeError('Invalid requested account email')
    with SessionLocal() as db:
        if db.query(Audit).filter_by(action='requested login email migration',subject='user',summary=old+' -> '+new).first():return
        rows=db.query(User).filter(func.lower(User.email)==old,User.full_name==name,User.role=='admin',User.active.is_(True)).with_for_update().all()
        if len(rows)!=1:
            log.warning('MILLS_LOGIN_EMAIL_MIGRATION: expected account not uniquely identified; no change made');return
        if db.query(User).filter(func.lower(User.email)==new).first():
            log.warning('MILLS_LOGIN_EMAIL_MIGRATION: destination already used; no change made');return
        user=rows[0];user.email=new
        db.add(Audit(user_id=user.id,action='requested login email migration',subject='user',subject_id=user.id,summary=old+' -> '+new))
        db.commit()
        log.warning('MILLS_LOGIN_EMAIL_MIGRATION: completed for requested account; password unchanged')
