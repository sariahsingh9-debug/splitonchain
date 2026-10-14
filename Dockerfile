FROM python:3.12-slim
WORKDIR /srv/atlas
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 atlas
COPY bundle.tar.gz /tmp/bundle.tar.gz
COPY deployment_entry.py /srv/atlas/deployment_entry.py
COPY mills_brand_patch.py /srv/atlas/mills_brand_patch.py
COPY production_audit_fix.py /srv/atlas/production_audit_fix.py
RUN tar xzf /tmp/bundle.tar.gz -C /srv/atlas && rm /tmp/bundle.tar.gz \
    && python mills_brand_patch.py \
    && python production_audit_fix.py \
    && pip install --no-cache-dir -r requirements.txt \
    && chown -R atlas:atlas /srv/atlas
USER atlas
EXPOSE 10000
CMD ["python", "deployment_entry.py"]
