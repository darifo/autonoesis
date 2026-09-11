# Per-application runtime image (P2-03): builds exactly one workspace package
# with dev dependencies excluded; the repo's build context is filtered by
# .dockerignore (no tests, docs, git history, or dev signing material).
FROM python:3.14-slim

ARG AUTONOESIS_PACKAGE=autonoesis-api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/autonoesis

WORKDIR /workspace
RUN pip install --no-cache-dir uv
COPY . .
RUN uv sync --frozen --no-dev --package "${AUTONOESIS_PACKAGE}"
ENV PATH="/opt/autonoesis/bin:$PATH"

CMD ["uvicorn", "autonoesis_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
