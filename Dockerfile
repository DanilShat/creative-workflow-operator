FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .

EXPOSE 8000 8501

CMD ["python", "-m", "creative_workflow.server.cli", "dev", "--host", "0.0.0.0", "--port", "8000"]
