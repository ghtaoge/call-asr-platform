# SIPREC PBX Realtime Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receive multi-tenant PBX SIPREC sessions with two G.711 RTP legs, identify sales/customer roles, stream recoverable audio to the ASR gRPC service, and expose unified live calls in the existing web application.

**Architecture:** A standalone Go gateway terminates SIPREC signaling and RTP, uses cached tenant trunk/extension rules, decodes and resamples media, spools acknowledged audio safely, and forwards the same versioned gRPC frames used by browser realtime. The business backend owns metadata, permissions, WebSocket events, persistence, and post-call analysis.

**Tech Stack:** Go 1.23, sipgo, pion/rtp, pion/sdp, zaf/g711, gRPC, mTLS, Redis Streams, PostgreSQL, FastAPI, Vue 3, pytest, Go test, Docker Compose

---

## Dependencies and File Map

This plan starts after the ASR gRPC protocol/service plan and tenant/PostgreSQL foundation from the sensitive-word plan are available.

- Create `siprec-gateway/go.mod` and `cmd/gateway/main.go`.
- Create `siprec-gateway/internal/siprec/`: multipart, SDP, recording metadata, dialog lifecycle.
- Create `siprec-gateway/internal/tenant/`: trunk config cache and extension role rules.
- Create `siprec-gateway/internal/media/`: port allocation, RTP, jitter, G.711, resampling.
- Create `siprec-gateway/internal/asr/`: generated gRPC client and acknowledgement buffer.
- Create `siprec-gateway/internal/spool/`: encrypted bounded call spool and recovery index.
- Create `siprec-gateway/internal/events/`: backend call lifecycle client.
- Create fixtures and integration tests under `siprec-gateway/testdata/`.
- Create `backend/app/pbx/models.py`, `repository.py`, and internal/public routes.
- Create `backend/app/realtime/events.py`: unified browser/PBX event persistence and fan-out.
- Modify `backend/app/realtime/manager.py`: publish the unified event contract.
- Create `frontend/src/components/LiveCallList.vue` and `useLiveCalls.ts`.
- Modify `frontend/src/components/RealtimePanel.vue` to view PBX calls read-only.
- Modify `deploy/docker-compose.yml` and operations documentation.

## Task 1: Scaffold a Hardened Gateway Process

**Files:**
- Create: `siprec-gateway/go.mod`
- Create: `siprec-gateway/cmd/gateway/main.go`
- Create: `siprec-gateway/internal/config/config.go`
- Create: `siprec-gateway/internal/health/health.go`
- Test: `siprec-gateway/internal/config/config_test.go`

- [ ] **Step 1: Write failing configuration test**

```go
func TestConfigRejectsPublicRTPWithoutAllowlist(t *testing.T) {
    _, err := config.Parse(map[string]string{
        "SIP_LISTEN": "0.0.0.0:5061",
        "RTP_BIND_IP": "0.0.0.0",
        "PBX_ALLOWLIST": "",
    })
    require.ErrorContains(t, err, "PBX_ALLOWLIST")
}
```

- [ ] **Step 2: Run and verify failure**

Run: `cd siprec-gateway; go test ./internal/config`

Expected: FAIL because the module and config package do not exist.

- [ ] **Step 3: Implement strict configuration and lifecycle**

Define listen addresses, TLS files, PBX CIDR allowlist, RTP port range, ASR/backend endpoints, mTLS files, spool root/key, buffer limits, Redis, timeouts, and concurrency limit. Parse with explicit defaults only for non-security values. `main` creates a root context cancelled by SIGTERM, starts health only after config/dependencies pass, and drains active dialogs within a bounded shutdown timeout.

- [ ] **Step 4: Run tests and static checks**

Run: `go test ./...; go vet ./...`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add siprec-gateway
git commit -m "feat: scaffold SIPREC gateway"
```

## Task 2: Parse SIPREC INVITE, SDP, and Metadata Safely

**Files:**
- Create: `siprec-gateway/internal/siprec/parser.go`
- Create: `siprec-gateway/internal/siprec/metadata.go`
- Create: `siprec-gateway/internal/siprec/dialog.go`
- Test: `siprec-gateway/internal/siprec/parser_test.go`
- Create: `siprec-gateway/testdata/invite-pcma.txt`
- Create: `siprec-gateway/testdata/invite-pcmu.txt`

- [ ] **Step 1: Write failing parser tests**

```go
func TestParseInviteExtractsTwoStreamsAndParticipants(t *testing.T) {
    invite := loadFixture(t, "invite-pcma.txt")
    recording, err := siprec.ParseInvite(invite, siprec.Limits{MaxBody: 1 << 20, MaxXMLDepth: 32})
    require.NoError(t, err)
    require.Len(t, recording.Streams, 2)
    assert.Equal(t, "PCMA", recording.Streams[0].Codec)
    assert.Equal(t, "1001", recording.Participants[0].Number)
}


func TestParseInviteRejectsExternalEntity(t *testing.T) {
    _, err := siprec.ParseInvite(inviteWithDOCTYPE(), siprec.Limits{})
    require.ErrorContains(t, err, "external entity")
}
```

- [ ] **Step 2: Run and verify failure**

Run: `go test ./internal/siprec -v`

Expected: FAIL because parsing is absent.

- [ ] **Step 3: Implement bounded SIPREC parsing**

Use sipgo for SIP messages and mime/multipart for bodies. Accept `application/sdp` plus `application/rs-metadata+xml`. Decode XML with a token loop that counts depth/elements and rejects directives/DOCTYPE before unmarshalling a minimal schema. Require recording session ID, exactly two audio streams, supported RTP payload mapping, participant associations, and non-conflicting stream labels. Return typed public SIP errors: 400 malformed, 415 unsupported media, 488 unsupported codec, 503 capacity.

- [ ] **Step 4: Run parser tests and fuzz seed corpus**

Run: `go test ./internal/siprec -run Test -v; go test ./internal/siprec -fuzz FuzzParseInvite -fuzztime 30s`

Expected: tests PASS and fuzzing finds no panic.

- [ ] **Step 5: Commit**

```powershell
git add siprec-gateway/internal/siprec siprec-gateway/testdata
git commit -m "feat: parse bounded SIPREC sessions"
```

## Task 3: Resolve Tenant and Sales/Customer Roles

**Files:**
- Create: `backend/app/pbx/models.py`
- Create: `backend/app/pbx/repository.py`
- Create: `backend/app/api/pbx_internal.py`
- Create: `backend/alembic/versions/20260717_02_pbx_config.py`
- Create: `siprec-gateway/internal/tenant/cache.go`
- Test: `backend/tests/pbx/test_config_api.py`
- Test: `siprec-gateway/internal/tenant/cache_test.go`

- [ ] **Step 1: Write failing role tests**

```go
func TestExtensionRuleMapsInternalToSalesAndExternalToCustomer(t *testing.T) {
    rules := tenant.Rules{Extensions: []string{"1XXX", "20XX"}}
    roles, err := rules.Map([]tenant.Participant{{ID: "a", Number: "1001"}, {ID: "b", Number: "13800138000"}})
    require.NoError(t, err)
    assert.Equal(t, "sales", roles["a"])
    assert.Equal(t, "customer", roles["b"])
}


func TestAmbiguousParticipantsRemainUnknown(t *testing.T) {
    _, err := (tenant.Rules{Extensions: []string{"1XXX"}}).Map(twoInternalParticipants())
    require.ErrorIs(t, err, tenant.ErrRolePending)
}
```

- [ ] **Step 2: Run and verify failure**

Run backend PBX API tests and `go test ./internal/tenant`.

Expected: FAIL because config and cache do not exist.

- [ ] **Step 3: Implement tenant configuration contract**

PostgreSQL table `pbx_trunks` stores tenant ID, source CIDRs, certificate fingerprint, trunk IDs, extension patterns, enabled, concurrency limit, and version under RLS. Internal endpoint accepts only Gateway mTLS identity and resolves source/trunk to one tenant. It returns a signed/versioned config without exposing other tenants.

Gateway caches by source/trunk with a five-minute TTL and last-known-good fallback. Extension patterns support exact digits plus `X` digit wildcard only; reject regex. One internal and one external participant map automatically. Otherwise emit `role_pending` and use `unknown`, never fixed RTP order.

- [ ] **Step 4: Run backend and Go tests**

Expected: all tenant isolation, stale-cache, disabled trunk, ambiguity, and pattern validation tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/pbx backend/app/api/pbx_internal.py backend/alembic/versions/20260717_02_pbx_config.py backend/tests/pbx siprec-gateway/internal/tenant
git commit -m "feat: resolve PBX tenants and participant roles"
```

## Task 4: Receive, Reorder, Decode, and Resample RTP

**Files:**
- Create: `siprec-gateway/internal/media/ports.go`
- Create: `siprec-gateway/internal/media/jitter.go`
- Create: `siprec-gateway/internal/media/decoder.go`
- Create: `siprec-gateway/internal/media/stream.go`
- Test: `siprec-gateway/internal/media/*_test.go`

- [ ] **Step 1: Write failing media tests**

```go
func TestJitterBufferOrdersAndDeduplicates(t *testing.T) {
    buffer := media.NewJitterBuffer(8, 60*time.Millisecond)
    output := pushPackets(buffer, packets(1, 3, 2, 2, 4))
    assert.Equal(t, []uint16{1, 2, 3, 4}, sequences(output))
}


func TestPCMAProducesTwentyMillisecond16kPCM(t *testing.T) {
    decoder := media.NewDecoder("PCMA", 8000)
    frames := decoder.Push(makeG711Packet(160))
    require.Len(t, frames, 1)
    assert.Len(t, frames[0].PCM, 640)
}
```

- [ ] **Step 2: Run and verify failure**

Run: `go test ./internal/media -v`

Expected: FAIL because media pipeline is absent.

- [ ] **Step 3: Implement bounded media pipeline**

Default the UDP media range to 20000-21999, enforce a 200ms maximum jitter window, and allocate even/odd ports with a semaphore and release-once handle. Parse RTP using pion/rtp, bind expected payload type/SSRC after first valid packets, reject source changes outside the negotiated PBX address, order within the jitter window, ignore duplicates, and insert codec silence for missing spans up to 60ms. Decode PCMA/PCMU with zaf/g711 and resample 8k to 16k using a stateful band-limited resampler. Emit exact 20ms PCM S16LE frames with monotonic sequence and capture time.

- [ ] **Step 4: Run tests, race detector, and fixture replay**

Run: `go test -race ./internal/media -v`

Expected: PASS with no leaked ports or goroutines.

- [ ] **Step 5: Commit**

```powershell
git add siprec-gateway/internal/media
git commit -m "feat: decode resilient SIPREC RTP media"
```

## Task 5: Add Encrypted Spool and Acknowledged ASR Forwarding

**Files:**
- Create: `siprec-gateway/internal/asr/client.go`
- Create: `siprec-gateway/internal/spool/store.go`
- Create: `siprec-gateway/internal/spool/recovery.go`
- Test: `siprec-gateway/internal/asr/client_test.go`
- Test: `siprec-gateway/internal/spool/store_test.go`

- [ ] **Step 1: Write failing recovery tests**

```go
func TestAckDeletesOnlyConfirmedFrames(t *testing.T) {
    store := newTestSpool(t)
    store.Append(frames(0, 1, 2, 3, 4))
    store.Acknowledge(2)
    assert.Equal(t, []uint64{3, 4}, store.PendingSequences())
}


func TestRestartRecoversEncryptedUnfinishedCall(t *testing.T) {
    first := openSpool(t, keyA)
    first.Append(frames(0, 1))
    first.Close()
    second := openSpool(t, keyA)
    assert.Equal(t, []uint64{0, 1}, second.PendingSequences())
    assert.NotContains(t, string(readRawFile(t)), "RIFF")
}
```

- [ ] **Step 2: Run and verify failure**

Run: `go test ./internal/asr ./internal/spool -v`

Expected: FAIL because forwarding and spool are absent.

- [ ] **Step 3: Implement spool and gRPC reconnect**

Write length-delimited frame records encrypted with AES-256-GCM, a per-call random data key wrapped by the configured master key, one-second fsync interval, 512 MiB per-call maximum, and an atomic recovery index. Append before sending; delete/truncate only through the ASR `ack_sequence`. On gRPC failure, reconnect with delays of 1, 2, 5, 10, and 30 seconds and resend unacknowledged frames. If pending realtime audio exceeds five seconds, stop realtime replay for the excess but retain it for the final offline WAV.

- [ ] **Step 4: Run recovery and fault tests**

Run: `go test -race ./internal/asr ./internal/spool -v`

Expected: PASS for restart, wrong key, truncated tail, duplicate ack, ASR restart, and disk-limit cases.

- [ ] **Step 5: Commit**

```powershell
git add siprec-gateway/internal/asr siprec-gateway/internal/spool
git commit -m "feat: recover SIPREC audio across ASR outages"
```

## Task 6: Persist Call Lifecycle and Unified Events

**Files:**
- Create: `backend/app/pbx/calls.py`
- Create: `backend/app/api/pbx_calls.py`
- Create: `backend/app/realtime/events.py`
- Modify: `backend/app/realtime/manager.py`
- Modify: `backend/app/main.py`
- Create: `backend/alembic/versions/20260717_03_realtime_calls.py`
- Test: `backend/tests/pbx/test_call_lifecycle.py`

- [ ] **Step 1: Write failing idempotency/event tests**

```python
async def test_duplicate_siprec_start_returns_same_call(repository):
    first = await repository.start_call(TENANT, "siprec-session-1", payload())
    second = await repository.start_call(TENANT, "siprec-session-1", payload())
    assert first.id == second.id


async def test_event_sequence_supports_websocket_resume(event_store):
    await event_store.append(CALL, "call_status", {"status": "active"})
    await event_store.append(CALL, "final_transcript", {"text": "您好"})
    assert [event.sequence for event in await event_store.after(CALL, 0)] == [1, 2]
```

- [ ] **Step 2: Run and verify failure**

Run: `cd backend; python -m pytest tests/pbx/test_call_lifecycle.py -q`

Expected: FAIL because call and event stores do not exist.

- [ ] **Step 3: Implement lifecycle**

Create tenant-scoped `realtime_calls` and `realtime_events` tables. Unique `(tenant_id, source, source_session_id)` provides idempotency. States are connecting, active, finalizing, completed with orthogonal flags role_pending, media_interrupted, asr_degraded, pbx_aborted. Internal mTLS routes accept start/status/end/audio-ready events from Gateway. Redis Streams fan out events; PostgreSQL stores final/status events and a bounded resume history.

Browser realtime must publish the same event names and sequence semantics. `WS /ws/calls/{call_id}?after_sequence=N` validates tenant access and replays stored events before live subscription.

- [ ] **Step 4: Run lifecycle and existing realtime tests**

Run: `python -m pytest tests/pbx/test_call_lifecycle.py tests/test_realtime_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/pbx backend/app/api/pbx_calls.py backend/app/realtime backend/app/main.py backend/alembic/versions/20260717_03_realtime_calls.py backend/tests/pbx/test_call_lifecycle.py backend/tests/test_realtime_api.py
git commit -m "feat: unify PBX and browser realtime calls"
```

## Task 7: Connect Gateway Dialog Lifecycle to Backend

**Files:**
- Create: `siprec-gateway/internal/events/client.go`
- Modify: `siprec-gateway/internal/siprec/dialog.go`
- Test: `siprec-gateway/internal/events/client_test.go`
- Test: `siprec-gateway/internal/siprec/dialog_test.go`

- [ ] **Step 1: Write failing end-to-end dialog state test**

Create an in-process fake backend and ASR, send INVITE, RTP on both streams, one ASR final event, then BYE. Assert backend receives exactly one start, active, finalizing, and completed transition; the final event includes role/time/text; and duplicate INVITE/BYE do not duplicate transitions.

- [ ] **Step 2: Run and verify failure**

Run: `go test ./internal/events ./internal/siprec -v`

Expected: FAIL because dialog orchestration is incomplete.

- [ ] **Step 3: Implement dialog state machine**

Use one owner goroutine per dialog and typed messages for SIP, media, ASR, timers, and shutdown. Transition only through valid state edges. On BYE, stop accepting RTP, flush both streams with end-of-stream, finalize spool/WAV, notify backend audio-ready, and wait for bounded acknowledgements. RTP timeout marks media_interrupted; gateway termination marks pbx_aborted. Retry backend notifications with idempotency key and persist unsent terminal events in spool metadata.

- [ ] **Step 4: Run dialog and race tests**

Run: `go test -race ./internal/events ./internal/siprec -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add siprec-gateway/internal/events siprec-gateway/internal/siprec
git commit -m "feat: orchestrate SIPREC call lifecycle"
```

## Task 8: Add Live PBX Call UI

**Files:**
- Create: `frontend/src/components/LiveCallList.vue`
- Create: `frontend/src/components/LiveCallDetail.vue`
- Create: `frontend/src/composables/useLiveCalls.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/RealtimePanel.vue`
- Test: `frontend/src/components/LiveCallList.spec.ts`

- [ ] **Step 1: Write failing UI tests**

```typescript
it("lists PBX source, roles, latency, status, and risk count", async () => {
  api.listLiveCalls.mockResolvedValue({ items: [pbxCall], next_cursor: null });
  const wrapper = mount(LiveCallList);
  await flushPromises();
  expect(wrapper.text()).toContain("PBX");
  expect(wrapper.text()).toContain("识别降级");
  expect(wrapper.text()).toContain("620 ms");
});


it("resumes detail websocket after the last sequence", async () => {
  const calls = useLiveCalls(fakeSocketFactory);
  calls.open("call_1");
  fakeSocketFactory.emit({ sequence: 9, type: "final_transcript", segment });
  fakeSocketFactory.disconnect();
  expect(fakeSocketFactory.lastUrl).toContain("after_sequence=9");
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend; npm test -- --run src/components/LiveCallList.spec.ts`

Expected: FAIL because live calls do not exist.

- [ ] **Step 3: Implement operational UI**

Add a realtime call list with source, sales/customer masked numbers, started time, status, P95-like current subtitle latency, risk count, and flags. Use cursor pagination and periodic refresh. Detail reuses transcript/risk components, is read-only for PBX media, reconnects by sequence, and shows role_pending/media/asr flags in Chinese. Do not expose another tenant or unmasked number without permission.

- [ ] **Step 4: Run frontend tests and build**

Run: `npm test -- --run; npm run build`

Expected: PASS and build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/LiveCallList.vue frontend/src/components/LiveCallDetail.vue frontend/src/composables/useLiveCalls.ts frontend/src/api/client.ts frontend/src/types.ts frontend/src/App.vue frontend/src/components/RealtimePanel.vue frontend/src/components/LiveCallList.spec.ts
git commit -m "feat: show live PBX calls"
```

## Task 9: Deploy, Replay, Load Test, and Roll Out

**Files:**
- Create: `siprec-gateway/Dockerfile`
- Create: `siprec-gateway/scripts/replay.go`
- Modify: `deploy/docker-compose.yml`
- Create: `backend/tests/pbx/test_deploy_contract.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/API.md`

- [ ] **Step 1: Write deployment contract tests**

Assert the Gateway runs non-root with read-only root filesystem, exposes configured SIP/RTP ranges only, mounts spool separately, has health/restart/log limits, uses mTLS secrets, and depends on ASR/backend readiness without putting credentials in Compose.

- [ ] **Step 2: Build deterministic replay tool**

Implement a Go replay command that reads sanitized fixture descriptions, sends SIPREC INVITE/BYE and wall-clock RTP for two legs, supports PCMA/PCMU, loss/reorder/duplicate rates, and concurrent calls. It must generate no real phone numbers or customer audio.

- [ ] **Step 3: Run integration and 100-call load tests**

Run full Go/Python/frontend tests, Docker builds, then shadow replay at 20/50/100 calls. Assert no duplicate calls, no spool loss, no cross-tenant events, P95 subtitles below 800ms, bounded memory/file descriptors/ports, and all calls reach a terminal state.

- [ ] **Step 4: Run failure and security tests**

Restart ASR, Redis, Gateway, and backend during calls; fill spool to its limit; send malformed/XXE/oversized SIPREC bodies and invalid RTP sources. Confirm explicit SIP responses, degraded states, offline recovery, no panic, and no unbounded disk growth.

- [ ] **Step 5: Document rollout and commit**

Document PBX trunk/TLS/port configuration, firewall/VPN, extension rules, mTLS rotation, spool encryption/retention, dashboards, alerts, packet diagnostics, replay usage, shadow mode, 5% canary, full rollout gates, and rollback by stopping SIPREC routing to Gateway.

```powershell
git add siprec-gateway deploy/docker-compose.yml backend/tests/pbx docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/API.md
git commit -m "feat: deploy and validate SIPREC ingestion"
```

## Completion Criteria

- SIPREC INVITE/SDP/XML and two PCMA/PCMU streams interoperate with the target PBX.
- Tenant is derived from trusted trunk identity; roles derive from extension rules, never RTP order.
- RTP reorder, duplicate, short loss, restart, and ASR outage preserve bounded audio and terminal state.
- PBX and browser calls use one sequenced event/UI contract.
- 100-call shadow load meets subtitle latency and resource gates.
- XML, SIP, RTP, tenant, mTLS, spool encryption, rate, port, and disk protections pass.
- Backend, frontend, Go, integration, Docker, replay, chaos, and browser checks pass before canary.
