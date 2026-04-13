# xTTS

Lightweight TTS microservice — gọi trực tiếp edge-tts Python library (không spawn subprocess), chunk-based cho text dài.

## Quick Start

```bash
# Docker (recommended)
docker compose up -d

# Native
pip install -r requirements.txt
python server.py
```

## API

### `POST /tts`
```json
{
  "text": "Xin chào anh em, đây là X Dev",
  "voice": "vi-VN-HoaiMyNeural",
  "rate": "+0%"
}
```

Response:
```json
{
  "audio": "<base64 MP3>",
  "audioFormat": "mp3",
  "audioSize": 19728,
  "captions": [
    { "startFrame": 3, "endFrame": 100, "text": "Xin chào anh em," },
    { "startFrame": 100, "endFrame": 200, "text": "đây là X Dev" }
  ],
  "durationSeconds": 3.2,
  "chunks": 1,
  "elapsed": 2.1
}
```

### `GET /health`
### `GET /voices?lang=vi`
### `GET /docs` — Swagger UI

## Deploy (Ubuntu)

```bash
git clone https://github.com/xdev-asia-labs/xTTS.git
cd xTTS
docker compose up -d
```

## Env

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 3099 | Server port |
| `TTS_MAX_CHUNK` | 500 | Max chars per chunk |
| `TTS_MAX_RETRIES` | 3 | Retries per chunk |
| `TTS_MAX_TEXT_LENGTH` | 20000 | Max input text |

## Architecture

```
Client ──POST /tts──> FastAPI (async)
                        │
                        ├─ Split text → chunks (≤500 chars)
                        ├─ edge-tts.Communicate.stream() per chunk (2 concurrent)
                        ├─ Collect audio bytes + WordBoundary captions
                        ├─ Merge word captions → phrases
                        ├─ Concatenate MP3 chunks
                        └─ Return base64 audio + frame-level captions
```
