FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md evaluation-results.json ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home relay && mkdir -p /app/data && chown -R relay:relay /app
USER relay

EXPOSE 8000
CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8000"]
