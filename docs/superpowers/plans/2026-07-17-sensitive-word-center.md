# Multi-Tenant Sensitive Word Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide audited multi-tenant sensitive-word management for 100K-1M exact terms per tenant, publish updates to active calls within five seconds, and color realtime/offline transcript hits by four fixed risk levels.

**Architecture:** Store authoritative words, versions, imports, and audits in PostgreSQL under a token-derived tenant context. Compile immutable Rust double-array Aho-Corasick base snapshots plus small delta/tombstone layers, broadcast versions through Redis, and atomically swap active-tenant matchers without blocking calls.

**Tech Stack:** FastAPI, SQLAlchemy 2 asyncio, Alembic, PostgreSQL 16, Redis 7, PyJWT/JWKS, Rust 1.82, PyO3, daachorse, Vue 3, Vitest, pytest, Playwright

---

## File Map

- Create `backend/app/auth/context.py`: verified user, tenant, and role context.
- Create `backend/app/database/postgres.py`: async engine and tenant-scoped transaction.
- Create `backend/alembic/`: sensitive schema and RLS migrations.
- Create `backend/app/sensitive/models.py`: API/domain models.
- Create `backend/app/sensitive/normalizer.py`: exact normalization and source index mapping.
- Create `backend/native/sensitive_matcher/`: Rust/PyO3 matcher and snapshot format.
- Create `backend/app/sensitive/compiler.py`: base/delta/tombstone artifact builder.
- Create `backend/app/sensitive/cache.py`: active-tenant LRU and atomic version swap.
- Create `backend/app/sensitive/repository.py`: tenant-scoped CRUD, versions, imports, audit.
- Create `backend/app/api/sensitive_admin.py`: management APIs.
- Create `backend/app/sensitive/importer.py`: streaming CSV/XLSX validation and publishing.
- Modify `backend/app/sensitive/store.py`: delegate scans to versioned cache.
- Modify `backend/app/main.py`: PostgreSQL, Redis subscriber, compiler and routes.
- Create `frontend/src/components/SensitiveSettings.vue` and focused child components.
- Create `frontend/src/composables/useSensitiveAdmin.ts` and API/types.
- Modify transcript/risk components for versioned hit tooltips and filters.
- Create benchmark and integration tests under `backend/tests/sensitive_center/`.

## Task 1: Establish Verified Tenant Context

**Files:**
- Create: `backend/app/auth/context.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/sensitive_center/test_auth_context.py`

- [ ] **Step 1: Write failing authorization tests**

```python
def test_tenant_context_comes_from_verified_token(client, signed_admin_token):
    response = client.get("/api/admin/sensitive-words", headers={"Authorization": f"Bearer {signed_admin_token}"})
    assert response.request.headers.get("X-Tenant-Id") is None
    assert response.status_code != 401


def test_request_cannot_override_tenant(client, signed_user_token):
    response = client.get(
        "/api/admin/sensitive-words",
        headers={"Authorization": f"Bearer {signed_user_token}", "X-Tenant-Id": "other"},
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run and verify failure**

Run: `cd backend; python -m pytest tests/sensitive_center/test_auth_context.py -q`

Expected: FAIL because authentication and the route do not exist.

- [ ] **Step 3: Implement token-derived context**

```python
@dataclass(frozen=True)
class RequestContext:
    user_id: str
    tenant_id: UUID
    roles: frozenset[str]


def require_role(role: str):
    async def dependency(context: RequestContext = Depends(current_context)) -> RequestContext:
        if role not in context.roles:
            raise HTTPException(status_code=403, detail="没有敏感词管理权限")
        return context
    return dependency
```

Verify JWT signature through configured issuer/audience/JWKS, require `sub`, `tenant_id`, and `roles`, reject caller-provided tenant headers, and cache JWKS with expiry. Add `PyJWT[crypto]>=2.9,<3`.

- [ ] **Step 4: Run authorization tests**

Run: `python -m pytest tests/sensitive_center/test_auth_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/auth backend/app/core/config.py backend/pyproject.toml backend/tests/sensitive_center/test_auth_context.py
git commit -m "feat: derive tenant scope from verified identity"
```

## Task 2: Add PostgreSQL Schema and RLS

**Files:**
- Create: `backend/app/database/postgres.py`
- Modify: `backend/pyproject.toml`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/20260717_01_sensitive_center.py`
- Test: `backend/tests/sensitive_center/test_tenant_rls.py`

- [ ] **Step 1: Write failing cross-tenant database test**

```python
async def test_rls_hides_other_tenant_words(postgres):
    await insert_word(postgres, TENANT_A, "退款")
    await insert_word(postgres, TENANT_B, "投诉")
    async with tenant_transaction(postgres, TENANT_A) as session:
        rows = (await session.execute(select(SensitiveWordRow))).scalars().all()
    assert [row.word for row in rows] == ["退款"]
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/sensitive_center/test_tenant_rls.py -q`

Expected: FAIL because PostgreSQL schema and RLS do not exist.

- [ ] **Step 3: Create schema**

Add `sqlalchemy[asyncio]>=2.0,<2.1`, `alembic>=1.13,<2`, and `asyncpg>=0.29,<1` to runtime dependencies. Create `sensitive_words`, `sensitive_versions`, `sensitive_imports`, and `sensitive_audit_logs` with UUID primary keys and required `tenant_id`. Add unique `(tenant_id, normalized_word)`, filter indexes, foreign keys, version status constraint, and timestamps. Enable/force RLS on every table with policy:

```sql
CREATE POLICY tenant_isolation ON sensitive_words
USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

`tenant_transaction()` starts a transaction then executes `SET LOCAL app.tenant_id = :tenant_id`; it never returns an unscoped session to route handlers.

- [ ] **Step 4: Apply migration and run RLS tests**

Run: `alembic upgrade head; python -m pytest tests/sensitive_center/test_tenant_rls.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/database backend/alembic.ini backend/alembic backend/pyproject.toml backend/tests/sensitive_center/test_tenant_rls.py
git commit -m "feat: persist tenant-isolated sensitive words"
```

## Task 3: Normalize Exact Matches With Source Mapping

**Files:**
- Create: `backend/app/sensitive/normalizer.py`
- Test: `backend/tests/sensitive_center/test_normalizer.py`

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalizer_maps_nfkc_case_and_whitespace_to_original_span():
    value = normalize_with_mapping("请联系 Ａ B C 客服")
    assert value.text == "请联系abc客服"
    start = value.text.index("abc")
    assert value.original_span(start, start + 3) == (4, 9)


def test_normalizer_does_not_convert_traditional_or_homophones():
    assert normalize_word("退貨") == "退貨"
    assert normalize_word("微心") == "微心"
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/sensitive_center/test_normalizer.py -q`

Expected: FAIL because normalization does not exist.

- [ ] **Step 3: Implement deterministic normalization**

Use per-codepoint Unicode NFKC, `casefold()`, and removal of Unicode whitespace. Store the original index for every emitted normalized codepoint and return an exclusive original end index. `normalize_word()` calls the same logic and rejects an empty result or more than 128 normalized codepoints.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/sensitive_center/test_normalizer.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/sensitive/normalizer.py backend/tests/sensitive_center/test_normalizer.py
git commit -m "feat: normalize sensitive matches with source positions"
```

## Task 4: Build Rust Double-Array Matcher

**Files:**
- Create: `backend/native/sensitive_matcher/Cargo.toml`
- Create: `backend/native/sensitive_matcher/pyproject.toml`
- Create: `backend/native/sensitive_matcher/src/lib.rs`
- Create: `backend/tests/sensitive_center/test_native_matcher.py`

- [ ] **Step 1: Write failing Python contract tests**

```python
def test_native_matcher_returns_pattern_ids_and_longest_overlap(tmp_path):
    matcher = SensitiveMatcher.compile([(10, "有效"), (11, "绝对有效")])
    assert matcher.scan("产品绝对有效") == [(2, 6, 11)]
    path = tmp_path / "base.ac"
    matcher.save(path)
    assert SensitiveMatcher.load(path).scan("绝对有效") == [(0, 4, 11)]
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/sensitive_center/test_native_matcher.py -q`

Expected: FAIL because the extension is absent.

- [ ] **Step 3: Implement PyO3 extension**

Use Rust `daachorse` for the double-array automaton, `serde`/`bincode` for a versioned snapshot envelope, and SHA-256 checksum. Expose:

```rust
#[pyclass]
struct SensitiveMatcher { automaton: DoubleArrayAhoCorasick<u32> }

#[pymethods]
impl SensitiveMatcher {
    #[staticmethod]
    fn compile(patterns: Vec<(u32, String)>) -> PyResult<Self>;
    fn scan(&self, text: &str) -> Vec<(usize, usize, u32)>;
    fn save(&self, path: PathBuf) -> PyResult<()>;
    #[staticmethod]
    fn load(path: PathBuf) -> PyResult<Self>;
}
```

Reject duplicate pattern IDs, empty patterns, invalid snapshot version/checksum, and snapshots larger than 8 GiB. Resolve overlaps by leftmost start, longest span, then lowest stable pattern ID.

- [ ] **Step 4: Build extension and run tests**

Run:

```powershell
cd backend/native/sensitive_matcher
maturin develop --release
cd ../..
python -m pytest tests/sensitive_center/test_native_matcher.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/native/sensitive_matcher backend/tests/sensitive_center/test_native_matcher.py
git commit -m "perf: add native sensitive word matcher"
```

## Task 5: Compile Base, Delta, and Tombstone Versions

**Files:**
- Create: `backend/app/sensitive/compiler.py`
- Create: `backend/app/sensitive/models.py`
- Test: `backend/tests/sensitive_center/test_compiler.py`

- [ ] **Step 1: Write failing layer tests**

```python
async def test_delta_add_and_tombstone_override_base(compiler, repository):
    base = await compiler.build_base(TENANT, version=1)
    await repository.disable_word(TENANT, "退款")
    await repository.add_word(TENANT, "投诉", level="high")
    delta = await compiler.build_delta(TENANT, base_version=1, version=2)
    matcher = LayeredMatcher(base, delta)
    assert [hit.word for hit in matcher.scan("退款和投诉")] == ["投诉"]
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/sensitive_center/test_compiler.py -q`

Expected: FAIL because compiler and layers are absent.

- [ ] **Step 3: Implement atomic artifacts**

Write artifacts under `{artifact_root}/{tenant_id}/{version}/` into a temporary directory, fsync files, write a manifest containing base version, counts, SHA-256, normalization version, and format version, then atomically rename. A delta contains an automaton for enabled additions/changes, a sorted tombstone ID set, and current metadata. Never mark a database version ready before all files pass reload/checksum verification.

Compact when delta changes exceed 50,000 or 10% of base count. Failed compaction marks only the candidate version failed and keeps the active version unchanged.

- [ ] **Step 4: Run compiler tests**

Run: `python -m pytest tests/sensitive_center/test_compiler.py -q`

Expected: PASS including crash-before-rename and checksum corruption.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/sensitive/compiler.py backend/app/sensitive/models.py backend/tests/sensitive_center/test_compiler.py
git commit -m "feat: compile versioned sensitive word layers"
```

## Task 6: Hot-Swap Active Tenant Cache Within Five Seconds

**Files:**
- Create: `backend/app/sensitive/cache.py`
- Modify: `backend/app/sensitive/store.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/sensitive_center/test_cache.py`

- [ ] **Step 1: Write failing hot-update test**

```python
async def test_active_call_uses_new_version_after_broadcast(cache, redis, artifacts):
    lease = await cache.acquire(TENANT)
    assert lease.matcher.version == 1
    await redis.publish("sensitive-versions", json.dumps({"tenant_id": str(TENANT), "version": 2}))
    await wait_until(lambda: cache.current_version(TENANT) == 2, timeout=5)
    assert (await cache.acquire(TENANT)).matcher.version == 2
    assert lease.matcher.version == 1
    lease.release()
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/sensitive_center/test_cache.py -q`

Expected: FAIL because cache and subscriber are absent.

- [ ] **Step 3: Implement ref-counted atomic swap**

Use an `OrderedDict` LRU keyed by tenant. Each entry contains current matcher, byte estimate, last access, and reference count. Load new artifacts outside the lock, verify, then swap under the lock. Existing leases retain the old matcher until released. Default to a 12 GiB cache ceiling and 64 loaded tenants per process; evict only zero-reference entries. Subscribe to Redis and poll PostgreSQL every 30 seconds for missed versions.

Replace JSON-file scanning in `SensitiveStore` with `scan(tenant_id, ...)` against the cache. Keep the JSON loader only as a one-time import tool.

- [ ] **Step 4: Run cache and existing scan tests**

Run: `python -m pytest tests/sensitive_center/test_cache.py tests/test_sensitive.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/sensitive/cache.py backend/app/sensitive/store.py backend/app/main.py backend/tests/sensitive_center/test_cache.py backend/tests/test_sensitive.py
git commit -m "feat: hot-swap tenant sensitive word versions"
```

## Task 7: Add Admin CRUD, Import, Export, Versions, and Audit APIs

**Files:**
- Create: `backend/app/sensitive/repository.py`
- Create: `backend/app/sensitive/importer.py`
- Create: `backend/app/api/sensitive_admin.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/sensitive_center/test_admin_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_admin_creates_word_and_publishes_version(admin_client):
    response = admin_client.post("/api/admin/sensitive-words", json={
        "word": "绝对有效", "level": "critical", "category": "promise", "enabled": True,
    })
    assert response.status_code == 201
    assert response.json()["version"] == 1


def test_user_cannot_modify_words(user_client):
    assert user_client.post("/api/admin/sensitive-words", json=valid_word()).status_code == 403


def test_list_uses_cursor_not_offset(admin_client):
    response = admin_client.get("/api/admin/sensitive-words?limit=50")
    assert set(response.json()) == {"items", "next_cursor"}
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/sensitive_center/test_admin_api.py -q`

Expected: FAIL because routes and repository do not exist.

- [ ] **Step 3: Implement scoped APIs**

Provide create/update/delete/enable/batch endpoints, cursor pagination ordered by `(updated_at DESC, id DESC)`, filters for query/level/category/enabled, versions and audit queries. Every mutation uses one transaction to change the word, append immutable audit, create a building version, and enqueue compilation after commit.

Add `openpyxl>=3.1,<4` to runtime dependencies. Imports accept CSV/XLSX up to 200 MiB and 2,000,000 rows, store a SHA-256, parse in a worker, reject formulas and invalid levels, produce a downloadable error CSV, and require explicit publish. Exports stream rows and prevent spreadsheet formula injection by prefixing cells beginning with `=`, `+`, `-`, or `@`.

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/sensitive_center/test_admin_api.py -q`

Expected: PASS including duplicate, invalid cursor, tenant isolation, import limits, and audit assertions.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/sensitive/repository.py backend/app/sensitive/importer.py backend/app/api/sensitive_admin.py backend/app/main.py backend/pyproject.toml backend/tests/sensitive_center/test_admin_api.py
git commit -m "feat: manage tenant sensitive word versions"
```

## Task 8: Build Sensitive Settings UI and Versioned Highlights

**Files:**
- Create: `frontend/src/components/SensitiveSettings.vue`
- Create: `frontend/src/components/SensitiveWordTable.vue`
- Create: `frontend/src/components/SensitiveImportPanel.vue`
- Create: `frontend/src/components/SensitiveVersionPanel.vue`
- Create: `frontend/src/components/SensitiveAuditPanel.vue`
- Create: `frontend/src/composables/useSensitiveAdmin.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/TranscriptPanel.vue`
- Modify: `frontend/src/components/SensitivePanel.vue`
- Test: `frontend/src/components/SensitiveSettings.spec.ts`

- [ ] **Step 1: Write failing UI tests**

```typescript
it("uses server cursor pagination and fixed four levels", async () => {
  api.listSensitiveWords.mockResolvedValue({ items: [word], next_cursor: "next" });
  const wrapper = mount(SensitiveSettings);
  await flushPromises();
  expect(wrapper.text()).toContain("严重");
  await wrapper.get("button[aria-label='下一页']").trigger("click");
  expect(api.listSensitiveWords).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "next" }));
});


it("shows version and category in transcript hit tooltip", () => {
  const wrapper = mount(TranscriptPanel, { props: transcriptWithCriticalHit({ version: 42 }) });
  expect(wrapper.get("mark").attributes("title")).toContain("版本 42");
  expect(wrapper.get("mark").classes()).toContain("hit-critical");
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend; npm test -- --run src/components/SensitiveSettings.spec.ts src/components/TranscriptPanel.spec.ts`

Expected: FAIL because settings and versioned hit fields do not exist.

- [ ] **Step 3: Implement work-focused management UI**

Use four tabs: sensitive words, batch tasks, versions, audit. Keep the table unframed inside one page section, server-side filters, stable row heights, a modal only for add/edit, and explicit import confirmation. Use yellow/orange/red/deep-red swatches in level selectors. Do not render all rows or nest cards. Add hit `dictionary_version` to backend/frontend types and tooltip; retain current seek behavior.

- [ ] **Step 4: Run frontend tests and build**

Run: `npm test -- --run; npm run build`

Expected: all tests PASS and build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components frontend/src/composables/useSensitiveAdmin.ts frontend/src/api/client.ts frontend/src/types.ts frontend/src/App.vue
git commit -m "feat: add sensitive word administration"
```

## Task 9: Million-Word Benchmark, Security, and Rollout

**Files:**
- Create: `backend/scripts/bench_sensitive_center.py`
- Create: `backend/tests/sensitive_center/test_benchmark_report.py`
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`

- [ ] **Step 1: Define benchmark report contract**

Require tenant count, term count, build seconds, base/delta artifact bytes, load seconds, scan MB/s, P50/P95 scan microseconds, update visibility seconds, peak RSS, false positives, and matcher versions.

- [ ] **Step 2: Implement and run benchmark**

Generate deterministic 1M-term data without customer content, build a base, publish 10K mixed changes, continuously scan while swapping, and verify no partial version or false match. Exit nonzero when update visibility exceeds five seconds, scan complexity grows with term count for fixed text, or process peak RSS exceeds the 12 GiB cache ceiling plus 2 GiB build allowance.

- [ ] **Step 3: Run complete checks**

Run backend/frontend full tests, Rust tests, production build, PostgreSQL integration tests, Redis outage reconciliation test, import security tests, and the million-word benchmark.

- [ ] **Step 4: Browser verification**

Use Playwright at desktop and 390px widths to create/edit/disable a word, import a validation fixture, inspect version/audit, and verify live/final transcript colors and tooltips. Confirm zero console errors and no horizontal overflow.

- [ ] **Step 5: Document and commit**

Document schema, RLS, artifact retention, compaction thresholds, cache memory sizing, Redis recovery, import format, API pagination, metrics, alerts, initial JSON import, rollback to the previous version, and audit retention.

```powershell
git add backend/scripts/bench_sensitive_center.py backend/tests/sensitive_center/test_benchmark_report.py docs/API.md docs/ARCHITECTURE.md docs/DEPLOYMENT.md
git commit -m "perf: validate million-word sensitive matching"
```

## Completion Criteria

- Tenant scope comes only from verified identity and PostgreSQL RLS blocks cross-tenant reads/writes.
- 1M exact terms compile and scan within measured release limits.
- Published changes become visible to active calls within five seconds without interrupting scans.
- Failed builds leave the previous active version untouched.
- CRUD, four levels, enable/disable, import/export, versions, audit, and read-only user permissions work.
- Transcript locations and colors remain correct after normalization.
- Existing offline/realtime risk analysis remains compatible.
- Full tests, Rust tests, integration tests, benchmark, security checks, build, and browser QA pass.
