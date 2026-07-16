FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --gid 10001 mediaos \
    && useradd --uid 10001 --gid mediaos --create-home mediaos

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY scripts ./scripts

RUN pip install --no-cache-dir ".[dev]"

USER mediaos

CMD ["uvicorn", "mediaos.main:app", "--host", "0.0.0.0", "--port", "8000"]

