FROM python:3.11.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_VERSION=1.8.4
ENV POETRY_VIRTUALENVS_CREATE=false

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY packages/contracts/python /workspace/packages/contracts/python
COPY services/control-plane /workspace/services/control-plane

WORKDIR /workspace/services/control-plane

RUN poetry install --only main --no-interaction --no-ansi

CMD ["poetry", "run", "uvicorn", "control_plane_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
