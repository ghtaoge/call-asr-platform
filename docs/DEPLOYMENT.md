# Deployment Guide

This project is currently a local-first prototype. Use the commands below for development and demo environments.

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .[test]
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Optional local model dependencies:

```bash
python -m pip install -e .[models]
```

## Frontend

```bash
cd frontend
npm install
npm run build
```

For development:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

If the backend uses a non-default port:

```powershell
$env:VITE_API_BASE="http://127.0.0.1:8022"
npm run dev -- --host 127.0.0.1 --port 5178
```

## Environment Variables

| Name | Default | Description |
|---|---|---|
| `CALL_ASR_DATABASE_PATH` | `data/call_asr.sqlite3` | SQLite database path |
| `CALL_ASR_SENSITIVE_WORDS_PATH` | `data/sensitive_words.sample.json` | Sensitive lexicon path |
| `CALL_ASR_ASR_PROVIDER` | `mock` | ASR provider name |
| `CALL_ASR_ASR_MODEL_SIZE` | `base` | Local ASR model size |
| `CALL_ASR_PREFERRED_DEVICE` | `auto` | `auto`, `cpu`, or `cuda` |
| `CALL_ASR_TARGET_LANGUAGE` | `en` | Default translation target |
| `VITE_API_BASE` | `http://127.0.0.1:8000` | Frontend backend base URL |

## Production Hardening Checklist

- Replace mock ASR with a real local model provider.
- Add object storage for uploaded audio.
- Add a task queue for long offline recordings.
- Add authentication and audit logs.
- Add lexicon management UI and validation.
- Add observability for ASR latency and risk-alert volume.
