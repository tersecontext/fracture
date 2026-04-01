FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "fracture.consumer", "--config", "/app/fracture.yaml"]
