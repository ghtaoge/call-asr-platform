# Sensitive Word Lexicon

Sensitive words are stored as JSON records and compiled into an Aho-Corasick style automaton.

Default file:

```text
backend/data/sensitive_words.sample.json
```

## Format

```json
[
  {
    "word": "绝对有效",
    "level": "critical",
    "category": "medical_promise",
    "enabled": true,
    "match_type": "contains",
    "description": "绝对化疗效承诺"
  }
]
```

## Levels

- `low`: light notice.
- `medium`: warning.
- `high`: high-risk warning.
- `critical`: severe risk.

The frontend maps these levels to different highlight colors.

## Performance

Run the benchmark:

```bash
cd backend
python scripts/bench_sensitive.py
```

The benchmark builds a 100,000-word scanner and scans repeated text. On the current development machine, the scanner completed a 100,000-entry build in about 1.24 seconds and scanned 16,000 characters in about 0.14 seconds.

## Updating The Lexicon

The `SensitiveStore.reload()` method loads the lexicon, builds a new scanner, and atomically switches the active scanner. If a future admin API is added, it should reuse this method and reject invalid lexicon entries before switching.
