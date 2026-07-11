# Development Guide

## Backend Tests

```bash
cd backend
python -m pytest -v --basetemp .pytest-tmp
```

Use `--basetemp .pytest-tmp` on Windows machines where the default user temp directory is restricted.

## Frontend Tests

```bash
cd frontend
npm install
npm test
npm run build
```

## Benchmark

```bash
cd backend
python scripts/bench_sensitive.py
```

## Code Organization

- Keep model-specific logic behind provider classes.
- Keep API route handlers thin.
- Put orchestration in `app/sessions/service.py`.
- Keep sensitive-word scanning deterministic and unit tested.
- Avoid making the frontend depend on provider-specific backend details.

## Adding A Real ASR Provider

1. Implement the provider behind `app/asr/base.py`.
2. Add configuration in `app/core/config.py`.
3. Update `SessionService` provider selection.
4. Add integration tests that can be skipped when model files are unavailable.
5. Document required model files and hardware expectations.
