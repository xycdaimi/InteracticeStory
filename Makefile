.PHONY: api web test

api:
	PYTHONPATH=. venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

web:
	cd frontend && npm run dev

test:
	PYTHONPATH=. venv/bin/pytest backend/tests -q
