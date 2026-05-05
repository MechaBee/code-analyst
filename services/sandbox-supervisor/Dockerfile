FROM python:3.11.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_VERSION=1.8.4
ENV POETRY_VIRTUALENVS_CREATE=false

WORKDIR /workspace

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY packages/contracts/python /workspace/packages/contracts/python
COPY services/sandbox-supervisor /workspace/services/sandbox-supervisor

WORKDIR /workspace/services/sandbox-supervisor

RUN poetry install --only main --no-interaction --no-ansi

CMD ["poetry", "run", "uvicorn", "sandbox_supervisor_app.main:app", "--host", "0.0.0.0", "--port", "8090"]
