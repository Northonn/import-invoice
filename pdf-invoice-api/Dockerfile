FROM python:3.12-slim

ARG PDFBOX_VERSION=3.0.5

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDFBOX_JAR=/opt/pdfbox/pdfbox-app.jar

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/pdfbox \
    && curl -fsSL "https://archive.apache.org/dist/pdfbox/${PDFBOX_VERSION}/pdfbox-app-${PDFBOX_VERSION}.jar" \
      -o /opt/pdfbox/pdfbox-app.jar

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
