FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
