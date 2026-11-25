.PHONY: up down logs test

# Creates .env from the template on first run, then builds and starts the stack.
up:
	@test -f .env || (cp .env.example .env && echo ">> Created .env from .env.example - put real LLM_API_KEYS in it.")
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000   Backend: http://localhost:8000/health"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	@if [ -d "backend/.venv" ]; then \
		PYTHONPATH=backend backend/.venv/bin/pytest backend/tests -v; \
	elif command -v uv >/dev/null 2>&1; then \
		cd backend && PYTHONPATH=. uv run pytest -v; \
	elif [ -n "$$VIRTUAL_ENV" ]; then \
		cd backend && pip install -q -r requirements-dev.txt && PYTHONPATH=. python -m pytest -v; \
	else \
		cd backend && python3 -m pip install -q -r requirements-dev.txt 2>/dev/null || true; \
		cd backend && PYTHONPATH=. python3 -m pytest -v; \
	fi

