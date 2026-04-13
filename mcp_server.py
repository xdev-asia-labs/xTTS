#!/usr/bin/env python3
"""
xTTS MCP Server — Model Context Protocol server for managing xTTS deployment config.

Provides tools for AI agents to:
- View/update environment variables (.env)
- Get current running config
- Restart the service
- Check health & stats
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
ENV_EXAMPLE = PROJECT_DIR / ".env.example"
DOCKER_COMPOSE = PROJECT_DIR / "docker-compose.yml"

# ── Valid config keys and their descriptions ────────────────────────────────
CONFIG_SCHEMA: dict[str, dict] = {
    "PORT": {"type": "int", "default": "3099", "desc": "Server port"},
    "LOG_LEVEL": {"type": "str", "default": "info", "desc": "Log level (debug/info/warning/error)"},
    "TTS_MAX_CHUNK": {"type": "int", "default": "500", "desc": "Max characters per TTS chunk"},
    "TTS_MAX_RETRIES": {"type": "int", "default": "3", "desc": "Max retries per chunk on failure"},
    "TTS_MAX_TEXT_LENGTH": {"type": "int", "default": "20000", "desc": "Max input text length"},
    "TTS_DEFAULT_VOICE": {"type": "str", "default": "vi-VN-HoaiMyNeural", "desc": "Default TTS voice"},
    "TTS_DEFAULT_RATE": {"type": "str", "default": "+0%", "desc": "Default speech rate"},
    "TTS_CONCURRENCY": {"type": "int", "default": "2", "desc": "Max concurrent TTS chunk processing"},
    "TTS_TIMEOUT": {"type": "int", "default": "30", "desc": "Timeout per TTS chunk in seconds"},
    "TTS_CACHE_SIZE": {"type": "int", "default": "100", "desc": "LRU cache max entries"},
    "TTS_CORS_ORIGINS": {"type": "str", "default": "*", "desc": "Comma-separated CORS origins"},
    "API_KEY": {"type": "str", "default": "", "desc": "API key for auth (empty = disabled)"},
    "RATE_LIMIT_MAX": {"type": "int", "default": "30", "desc": "Max POST requests per window"},
    "RATE_LIMIT_WINDOW": {"type": "int", "default": "60", "desc": "Rate limit window in seconds"},
    "FPS": {"type": "int", "default": "30", "desc": "Frames per second for caption timing"},
    "CAPTION_MAX_WORDS": {"type": "int", "default": "6", "desc": "Max words per caption group"},
    "CAPTION_MAX_GAP_FRAMES": {"type": "int", "default": "10", "desc": "Max gap frames before caption split"},
}

app = FastAPI(
    title="xTTS MCP Server",
    version="1.0.0",
    description="MCP server for managing xTTS deployment configuration",
)


# ── Helpers ─────────────────────────────────────────────────────────────────
def _read_env() -> dict[str, str]:
    """Read .env file into a dict."""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Write dict back to .env file, preserving comments from .env.example."""
    lines: list[str] = []
    if ENV_EXAMPLE.exists():
        for line in ENV_EXAMPLE.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(line)
            elif "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                value = env.get(key, stripped.split("=", 1)[1].strip())
                lines.append(f"{key}={value}")
    else:
        for key, value in env.items():
            lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def _validate_key(key: str) -> None:
    if key not in CONFIG_SCHEMA:
        raise HTTPException(400, f"Unknown config key '{key}'. Valid keys: {list(CONFIG_SCHEMA.keys())}")


def _validate_value(key: str, value: str) -> None:
    schema = CONFIG_SCHEMA[key]
    if schema["type"] == "int":
        try:
            int(value)
        except ValueError:
            raise HTTPException(400, f"'{key}' must be an integer, got '{value}'")


# ── MCP Tool Endpoints ──────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    key: str = Field(description="Environment variable name (e.g. TTS_MAX_CHUNK)")
    value: str = Field(description="New value for the variable")


class ConfigBatchUpdate(BaseModel):
    updates: dict[str, str] = Field(description="Dict of key-value pairs to update")


@app.get("/mcp/config/schema")
async def get_config_schema():
    """Get the full config schema with descriptions and defaults."""
    return {"schema": CONFIG_SCHEMA}


@app.get("/mcp/config")
async def get_config():
    """Get current .env configuration merged with defaults."""
    env = _read_env()
    result = {}
    for key, schema in CONFIG_SCHEMA.items():
        result[key] = {
            "value": env.get(key, schema["default"]),
            "default": schema["default"],
            "is_custom": key in env,
            "type": schema["type"],
            "description": schema["desc"],
        }
    return {"config": result, "env_file": str(ENV_FILE), "exists": ENV_FILE.exists()}


@app.get("/mcp/config/{key}")
async def get_config_key(key: str):
    """Get a specific config key's current value."""
    _validate_key(key)
    env = _read_env()
    schema = CONFIG_SCHEMA[key]
    return {
        "key": key,
        "value": env.get(key, schema["default"]),
        "default": schema["default"],
        "is_custom": key in env,
        "description": schema["desc"],
    }


@app.put("/mcp/config")
async def update_config(update: ConfigUpdate):
    """Update a single config key in .env file."""
    _validate_key(update.key)
    _validate_value(update.key, update.value)
    env = _read_env()
    old_value = env.get(update.key, CONFIG_SCHEMA[update.key]["default"])
    env[update.key] = update.value
    _write_env(env)
    return {
        "key": update.key,
        "old_value": old_value,
        "new_value": update.value,
        "note": "Restart the service for changes to take effect",
    }


@app.put("/mcp/config/batch")
async def update_config_batch(batch: ConfigBatchUpdate):
    """Update multiple config keys at once."""
    for key in batch.updates:
        _validate_key(key)
        _validate_value(key, batch.updates[key])

    env = _read_env()
    changes = []
    for key, value in batch.updates.items():
        old = env.get(key, CONFIG_SCHEMA[key]["default"])
        env[key] = value
        changes.append({"key": key, "old": old, "new": value})
    _write_env(env)
    return {"changes": changes, "note": "Restart the service for changes to take effect"}


@app.post("/mcp/config/reset/{key}")
async def reset_config_key(key: str):
    """Reset a config key to its default value."""
    _validate_key(key)
    env = _read_env()
    old = env.pop(key, CONFIG_SCHEMA[key]["default"])
    _write_env(env)
    return {"key": key, "old_value": old, "new_value": CONFIG_SCHEMA[key]["default"]}


@app.post("/mcp/config/reset")
async def reset_all_config():
    """Reset all config to defaults (recreate .env from .env.example)."""
    if ENV_EXAMPLE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text())
    else:
        _write_env({k: v["default"] for k, v in CONFIG_SCHEMA.items()})
    return {"status": "reset", "note": "All config reset to defaults"}


@app.get("/mcp/service/status")
async def service_status():
    """Check if the xTTS service is running."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            env = _read_env()
            port = env.get("PORT", "3099")
            resp = await client.get(f"http://localhost:{port}/health")
            return {"running": True, "health": resp.json()}
    except Exception as e:
        return {"running": False, "error": str(e)}


@app.post("/mcp/service/restart")
async def restart_service():
    """Restart the xTTS service via docker-compose."""
    if not DOCKER_COMPOSE.exists():
        raise HTTPException(400, "docker-compose.yml not found")
    try:
        result = subprocess.run(
            ["docker", "compose", "restart", "xtts"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_DIR),
        )
        return {
            "status": "restarted" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Restart timed out")
    except FileNotFoundError:
        raise HTTPException(500, "docker command not found")


@app.get("/mcp/docker/status")
async def docker_status():
    """Check docker-compose service status."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_DIR),
        )
        if result.returncode == 0 and result.stdout.strip():
            containers = []
            for line in result.stdout.strip().splitlines():
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            return {"status": "ok", "containers": containers}
        return {"status": "not_running", "stderr": result.stderr}
    except FileNotFoundError:
        return {"status": "docker_not_found"}


@app.get("/mcp/env/diff")
async def env_diff():
    """Show differences between current .env and .env.example defaults."""
    env = _read_env()
    diffs = []
    for key, schema in CONFIG_SCHEMA.items():
        current = env.get(key, schema["default"])
        if current != schema["default"]:
            diffs.append({
                "key": key,
                "current": current,
                "default": schema["default"],
                "description": schema["desc"],
            })
    return {"differences": diffs, "total_custom": len(diffs)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mcp_server:app",
        host="0.0.0.0",
        port=3100,
        log_level="info",
    )
