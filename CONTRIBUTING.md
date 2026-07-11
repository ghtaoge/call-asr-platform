# Contributing

## Local Checks

Run backend checks:

```bash
cd backend
python -m pytest -v --basetemp .pytest-tmp
```

Run frontend checks:

```bash
cd frontend
npm test
npm run build
```

Run sensitive-word benchmark:

```bash
cd backend
python scripts/bench_sensitive.py
```

## Pull Request Expectations

- Keep provider integrations behind existing provider boundaries.
- Add tests for scanner, scoring, compliance, and API behavior.
- Do not commit generated files such as `node_modules`, `dist`, SQLite databases, caches, or logs.
- Update docs when changing API contracts or environment variables.
