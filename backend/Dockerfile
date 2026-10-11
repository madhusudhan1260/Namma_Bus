FROM python:3.11-slim

WORKDIR /app

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PORT=8001     TRANSIT_PROVIDER=mock     ENVIRONMENT=production

# Install system dependencies & create non-root user
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*     && useradd -m -u 1000 appuser

# Install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY . .
RUN chown -R appuser:appuser /app

USER appuser

# Expose service port
EXPOSE 8001

# Healthcheck probe using production /api/ready endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/api/ready || exit 1

STOPSIGNAL SIGTERM

# Launch production server with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
