FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/autonoesis

WORKDIR /workspace
RUN pip install --no-cache-dir uv
COPY . .
RUN uv sync --frozen --all-packages --no-dev
ENV PATH="/opt/autonoesis/bin:$PATH"

CMD ["uvicorn", "autonoesis_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
