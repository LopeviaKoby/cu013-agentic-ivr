FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml requirements.lock README.md ./
COPY app ./app

RUN pip install --no-cache-dir -c requirements.lock .

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin cu013
USER cu013

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn --factory app.main:build_app --host 0.0.0.0 --port ${PORT:-8080}"]
