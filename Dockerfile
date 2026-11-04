FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build SQLite database with indexes (takes ~14s)
RUN python build_db.py

EXPOSE 8000

ENV PORT=8000

CMD ["python", "server.py"]
