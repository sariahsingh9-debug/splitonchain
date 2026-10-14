FROM python:3.12-slim
WORKDIR /srv/atlas
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 atlas
COPY bundle.tar.gz /tmp/bundle.tar.gz
COPY mills_release_2026.b64 /tmp/mills-release.b64
COPY mills_invoice_v3.b64 /tmp/mills-invoice-v3.b64
COPY deployment_entry.py /srv/atlas/deployment_entry.py
RUN tar xzf /tmp/bundle.tar.gz -C /srv/atlas \
    && base64 -d /tmp/mills-release.b64 | tar xzf - -C /srv/atlas \
    && base64 -d /tmp/mills-invoice-v3.b64 | tar xzf - -C /srv/atlas \
    && rm /tmp/bundle.tar.gz /tmp/mills-release.b64 /tmp/mills-invoice-v3.b64 \
    && python -m compileall -q /srv/atlas/app.py /srv/atlas/invoice_tools.py /srv/atlas/operations_plus.py /srv/atlas/models.py \
    && pip install --no-cache-dir -r requirements.txt \
    && chown -R atlas:atlas /srv/atlas
USER atlas
EXPOSE 10000
CMD ["python", "deployment_entry.py"]
