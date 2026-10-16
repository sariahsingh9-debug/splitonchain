FROM python:3.12-slim
WORKDIR /srv/atlas
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 atlas
COPY bundle.tar.gz /tmp/bundle.tar.gz
COPY mills_release_2026.b64 /tmp/mills-release.b64
COPY mills_invoice_v3.b64 /tmp/mills-invoice-v3.b64
COPY deployment_entry.py /srv/atlas/deployment_entry.py
COPY photo_import.py /srv/atlas/photo_import.py
COPY photo_import.html /srv/atlas/templates/photo_import.html
COPY photo_import.css /srv/atlas/static/photo_import.css
COPY photo_import.js /srv/atlas/static/photo_import.js
COPY install_photo_import.py /srv/atlas/install_photo_import.py
COPY mills_logo_patch.py /srv/atlas/mills_logo_patch.py
COPY sidebar_ambient.css /srv/atlas/static/sidebar_ambient.css
COPY install_sidebar_ambient.py /srv/atlas/install_sidebar_ambient.py
COPY login_cash_ambient.css /srv/atlas/static/login_cash_ambient.css
COPY install_login_cash_ambient.py /srv/atlas/install_login_cash_ambient.py
COPY handover_invoice.py /srv/atlas/handover_invoice.py
COPY auto_capture.py /srv/atlas/auto_capture.py
COPY install_handover.py /srv/atlas/install_handover.py
COPY simple_invoice_workflow.py /srv/atlas/simple_invoice_workflow.py
COPY simple_invoice_workflow.css /srv/atlas/static/simple_invoice_workflow.css
COPY install_simple_invoice_workflow.py /srv/atlas/install_simple_invoice_workflow.py
COPY invoice_background_part_01.txt /tmp/invoice_background_part_01.txt
COPY invoice_background_part_02.txt /tmp/invoice_background_part_02.txt
COPY invoice_background_part_03.txt /tmp/invoice_background_part_03.txt
COPY invoice_background_part_04.txt /tmp/invoice_background_part_04.txt
COPY invoice_background_part_05.txt /tmp/invoice_background_part_05.txt
COPY invoice_background_part_06.txt /tmp/invoice_background_part_06.txt
COPY mills_logo.b64 /tmp/mills_logo.b64
COPY mills_emblem.b64 /tmp/mills_emblem.b64
RUN tar xzf /tmp/bundle.tar.gz -C /srv/atlas \
    && base64 -d /tmp/mills-release.b64 | tar xzf - -C /srv/atlas \
    && base64 -d /tmp/mills-invoice-v3.b64 | tar xzf - -C /srv/atlas \
    && rm /tmp/bundle.tar.gz /tmp/mills-release.b64 /tmp/mills-invoice-v3.b64 \
    && python install_photo_import.py \
    && base64 -d /tmp/mills_logo.b64 > /srv/atlas/static/mills-logo.png \
    && base64 -d /tmp/mills_emblem.b64 > /srv/atlas/static/mills-emblem.png \
    && rm /tmp/mills_logo.b64 /tmp/mills_emblem.b64 \
    && python mills_logo_patch.py \
    && python install_sidebar_ambient.py \
    && python install_login_cash_ambient.py \
    && cat /tmp/invoice_background_part_01.txt /tmp/invoice_background_part_02.txt /tmp/invoice_background_part_03.txt /tmp/invoice_background_part_04.txt /tmp/invoice_background_part_05.txt /tmp/invoice_background_part_06.txt | base64 -d > /srv/atlas/static/mills-blank-invoice.jpg \
    && python install_handover.py \
    && python install_simple_invoice_workflow.py \
    && python -m compileall -q /srv/atlas/simple_invoice_workflow.py /srv/atlas/app.py /srv/atlas/photo_import.py /srv/atlas/invoice_tools.py /srv/atlas/operations_plus.py /srv/atlas/models.py \
    && pip install --no-cache-dir -r requirements.txt 'Pillow>=10.4,<13' \
    && chown -R atlas:atlas /srv/atlas
USER atlas
EXPOSE 10000
CMD ["python", "deployment_entry.py"]
