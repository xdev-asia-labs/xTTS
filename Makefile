.PHONY: dev install test lint docker-up docker-down clean

# ── Development ─────────────────────────────────────────────────────────────
dev:
	uvicorn server:app --host 0.0.0.0 --port 3099 --reload

install:
	pip install -e ".[dev]"

# ── Testing ─────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=app --cov-report=term-missing

# ── Linting ─────────────────────────────────────────────────────────────────
lint:
	ruff check app/ tests/ server.py

format:
	ruff format app/ tests/ server.py

# ── Docker ──────────────────────────────────────────────────────────────────
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f xtts

# ── Cleanup ─────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache *.egg-info dist build
