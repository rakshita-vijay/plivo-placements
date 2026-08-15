.PHONY: install install-dev run test lint tunnel call status docker-build docker-run

VENV_PYTHON := .venv/bin/python

install:
	python3 -m venv .venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements.txt

install-dev:
	python3 -m venv .venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest

lint:
	ruff check app cli tests

## Convenience wrapper around `ngrok http 8000` — requires ngrok on PATH.
tunnel:
	ngrok http 8000

## Trigger a call: `make call TO=+919876543210`
call:
	python cli/trigger_call.py --to $(TO) --watch

status:
	python cli/trigger_call.py --list

docker-build:
	docker build -t inspireworks-ivr-demo .

## Run the container, forwarding local port 8000 and loading .env.
docker-run:
	docker run --rm -p 8000:8000 --env-file .env inspireworks-ivr-demo
