FROM python:3.11-slim

WORKDIR /app

# ffmpeg for audio processing (concat, duration probe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 3099

CMD ["python", "server.py"]
