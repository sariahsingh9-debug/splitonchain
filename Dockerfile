FROM python:3.12-slim
WORKDIR /srv/atlas
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 atlas
COPY bundle.tar.gz /tmp/bundle.tar.gz
RUN tar xzf /tmp/bundle.tar.gz -C /srv/atlas && rm /tmp/bundle.tar.gz \
    && pip install --no-cache-dir -r requirements.txt \
    && chown -R atlas:atlas /srv/atlas
USER atlas
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers"]
