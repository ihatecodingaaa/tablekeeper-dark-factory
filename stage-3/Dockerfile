FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Dependencies are fetched at build time; the running container needs no network.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tablekeeper ./tablekeeper

RUN useradd --system --uid 10001 --no-create-home tablekeeper
USER tablekeeper

EXPOSE 8080
CMD ["python", "-m", "tablekeeper"]
