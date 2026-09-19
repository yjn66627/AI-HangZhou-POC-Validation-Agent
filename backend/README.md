# Backend

This directory contains the FastAPI backend for the POC validation and decision workflow. It accepts structured run requests, validates the experiment contract, executes the configured adapter, and exposes the resulting status and decision data.

## Local requirements

- Python 3.12.14 is the validation baseline.
- Install the dependencies from the repository-level `requirements.txt`.
- No secret is committed. Runtime credentials and live endpoint settings must be supplied through environment variables.

## Local start

From the candidate root:

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

The loopback address is a replaceable local-development default. A deployment-specific endpoint must be configured outside this source snapshot.

## Main endpoints

- `GET /health` — service health check.
- `POST /api/v1/runs` — submit a structured validation run.
- `POST /api/v1/yuanqi/runs` — submit a Yuanqi-adapter run.
- `GET /api/v1/runs/{run_id}` — read run status and result data.

The source snapshot is intended for review and reproducible local inspection. It does not claim a production deployment or require any credential to be stored in the repository.
