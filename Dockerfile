FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --system --uid 10001 app

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN python -m pip install --no-cache-dir uv==0.12.2 \
    && uv sync --frozen --no-editable --no-install-project --no-dev --no-cache \
    && chmod 0555 /usr/local/bin/entrypoint.sh \
    && chown -R app:app /app

USER app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
