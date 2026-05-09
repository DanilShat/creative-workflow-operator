FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install third-party runtime dependencies before copying application source.
# This keeps Docker rebuilds fast when we change Python code but not dependencies.
COPY requirements.operator.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.operator.txt

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

# The package itself is installed without resolving dependencies again because
# the pinned operator dependency set above already defines the runtime surface.
RUN python -m pip install --no-deps -e .

EXPOSE 8000 8501

CMD ["python", "-m", "creative_workflow.server.cli", "dev", "--host", "0.0.0.0", "--port", "8000"]
