FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# exact versions REVIVE is tested with
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY . .
# builds models / sample IFC only if they are missing. The app user has uid 1000 because
# Hugging Face Spaces runs every container as uid 1000, and the app writes to data/, models/ and bim/.
RUN python -m revive setup \
 && useradd --create-home --uid 1000 revive \
 && mkdir -p /app/data /app/models/bim_cache \
 && chown -R revive:revive /app/data /app/models /app/bim
# never run the web server as root inside the container
USER revive
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",8000)}/api/health')" || exit 1
CMD ["sh", "-c", "python -m revive serve --host 0.0.0.0 --port ${PORT}"]
