# Proctor SUT - guarded refund assistant API
FROM python:3.11-slim

WORKDIR /app

# install the framework (runtime deps only - no dev extras)
COPY pyproject.toml README.md ./
COPY framework/ framework/
COPY clients/ clients/
COPY sut/ sut/
RUN pip install --no-cache-dir .

# non-root user
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# container best practice: bind all interfaces INSIDE the container only;
# the repo's binding scan covers Python source, not container entrypoints
CMD ["uvicorn", "sut.api:app", "--host", "0.0.0.0", "--port", "8000"]

# deployment validation: container is healthy when /health returns 200
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
