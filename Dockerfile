# Backend image: FastAPI app + the original agent code (agents/, teams/, models/, utils/, config/, main.py CLI).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt requirements-server.txt ./
RUN pip install -r requirements-server.txt

COPY . .
RUN sed -i 's/\r$//' docker/backend-entrypoint.sh && chmod +x docker/backend-entrypoint.sh \
    && useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"
ENTRYPOINT ["./docker/backend-entrypoint.sh"]
