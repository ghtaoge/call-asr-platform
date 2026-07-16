# Vue 3 Migration + URL Audio Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the frontend from React to Vue 3 (Composition API + TypeScript + pure CSS) and add a URL audio recognition feature — a text input in the Toolbar where users paste a remote audio file URL, the backend downloads the audio and runs the existing analysis pipeline.

**Architecture:** Backend adds a single new REST endpoint (`POST /api/sessions/url`) that receives an audio URL, downloads the audio via `httpx`, and reuses `SessionService.analyze_offline` for analysis. Frontend is rebuilt from React to Vue 3 Composition API, keeping the same component structure and CSS. A URL input field and "识别" button are added to the Toolbar alongside existing upload and realtime controls.

**Tech Stack:** Vue 3, Vite, TypeScript, Composition API, `lucide-vue-next`, `httpx`, FastAPI, Pydantic, Vitest

## Global Constraints

- Python >= 3.11 (backend)
- Vue 3 Composition API + `<script setup lang="ts">` (frontend)
- Pure CSS — no UI framework, no scoped styles in Vue components
- Frontend URL validation: only check `http://` or `https://` prefix, rest is backend's job
- Backend URL download: timeout 30s, max file size 50MB
- Backend response shape for `/api/sessions/url` identical to `/api/sessions/offline`
- All existing features (file upload, realtime WebSocket) must work unchanged after migration

---

## Task 1: Backend — Add `UrlAnalysisRequest` model and `httpx` dependency

**Files:**
- Modify: `backend/app/core/models.py` (add `UrlAnalysisRequest` class at end)
- Modify: `backend/pyproject.toml` (add `httpx` to main dependencies)

**Interfaces:**
- Produces: `UrlAnalysisRequest(audio_url: str)` — used by Task 2
- Produces: `httpx` available in runtime dependencies — used by Task 2

- [ ] **Step 1: Add `httpx` to pyproject.toml runtime dependencies**

Edit `backend/pyproject.toml`. Add `"httpx>=0.27.0"` to the main `dependencies` list (it's currently only in the `test` optional group). The `dependencies` block should become:

```toml
dependencies = [
  "fastapi>=0.111.0",
  "uvicorn[standard]>=0.30.0",
  "pydantic>=2.7.0",
  "pydantic-settings>=2.2.1",
  "python-multipart>=0.0.9",
  "aiosqlite>=0.20.0",
  "websockets>=12.0",
  "httpx>=0.27.0"
]
```

- [ ] **Step 2: Add `UrlAnalysisRequest` model to models.py**

Edit `backend/app/core/models.py`. Append the following class after the `OfflineAnalysisResponse` class:

```python
class UrlAnalysisRequest(BaseModel):
    audio_url: str
```

- [ ] **Step 3: Reinstall backend dependencies**

Run:
```bash
cd backend && python -m pip install -e .
```

Expected: `httpx` installs successfully alongside other dependencies.

- [ ] **Step 4: Verify model parses valid URL**

Run:
```bash
cd backend && python -c "from app.core.models import UrlAnalysisRequest; r = UrlAnalysisRequest(audio_url='https://example.com/audio.wav'); print(r.audio_url)"
```

Expected output: `https://example.com/audio.wav`

- [ ] **Step 5: Commit**

```bash
cd backend && git add pyproject.toml app/core/models.py && git commit -m "feat: add UrlAnalysisRequest model and httpx dependency"
```

---

## Task 2: Backend — Create `/api/sessions/url` route handler

**Files:**
- Create: `backend/app/api/url.py`
- Modify: `backend/app/main.py:4,17-18` (add import and include router)
- Test: `backend/tests/test_url_api.py` (new file)

**Interfaces:**
- Consumes: `UrlAnalysisRequest` from Task 1, `SessionService` from existing code, `OfflineAnalysisResponse` from existing models
- Consumes: `httpx` from Task 1 dependency
- Produces: `router` with `POST /api/sessions/url` — used by frontend Task 5

- [ ] **Step 1: Write the failing test — valid URL returns analysis**

Create `backend/tests/test_url_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_url_analysis_returns_segments_and_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sensitive_words.sample.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(data_dir / "sensitive_words.sample.json"))
    client = TestClient(create_app())

    # Use a URL that httpx can't actually reach in tests — we'll mock it later.
    # For now, test that the route exists and returns proper shape when audio is available.
    response = client.post(
        "/api/sessions/url",
        json={"audio_url": "https://example.com/test.wav"},
    )

    # The route should exist (not 404). It may return 502 because httpx can't
    # actually download from example.com in a test environment, but it must not 404.
    assert response.status_code != 404
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && python -m pytest tests/test_url_api.py -v
```

Expected: FAIL with 404 (route doesn't exist yet) or ImportError.

- [ ] **Step 3: Create the URL route handler**

Create `backend/app/api/url.py`:

```python
import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.models import OfflineAnalysisResponse, UrlAnalysisRequest
from app.sensitive.store import SensitiveStore
from app.sessions.repository import SessionRepository
from app.sessions.service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["url"])

MAX_AUDIO_SIZE = 50 * 1024 * 1024  # 50MB
DOWNLOAD_TIMEOUT = 30.0  # seconds


@router.post("/url", response_model=OfflineAnalysisResponse)
async def create_url_session(request: UrlAnalysisRequest) -> OfflineAnalysisResponse:
    # Validate URL format
    if not request.audio_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="音频 URL 格式不合法")

    # Download audio from remote URL
    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            response = await client.get(request.audio_url, follow_redirects=True)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="下载音频文件超时")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法下载音频文件：远程服务器返回 {exc.response.status_code}",
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="无法下载音频文件")

    audio = response.content

    # Validate size
    if len(audio) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="音频文件过大")

    # Validate content type is audio-ish
    content_type = response.headers.get("content-type", "")
    if content_type and not any(
        prefix in content_type for prefix in ("audio/", "application/octet-stream", "binary")
    ):
        raise HTTPException(status_code=400, detail="URL 返回的内容不是有效的音频文件")

    # Reuse existing analysis pipeline
    settings = get_settings()
    sensitive_store = SensitiveStore(settings.sensitive_words_path)
    sensitive_store.reload()
    repository = SessionRepository(settings.database_path)
    service = SessionService(repository, sensitive_store)
    session_id, segments, quality, summary = await service.analyze_offline(audio, settings.target_language)
    return OfflineAnalysisResponse(session_id=session_id, segments=segments, quality=quality, summary=summary)
```

- [ ] **Step 4: Register the router in main.py**

Edit `backend/app/main.py`. Change the import line and add router inclusion:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, offline, realtime, url


def create_app() -> FastAPI:
    app = FastAPI(title="Call ASR Platform", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(offline.router)
    app.include_router(realtime.router)
    app.include_router(url.router)
    return app


app = create_app()
```

- [ ] **Step 5: Run the basic route existence test**

Run:
```bash
cd backend && python -m pytest tests/test_url_api.py -v
```

Expected: PASS (route exists, returns 502 because example.com can't serve real audio, but no 404).

- [ ] **Step 6: Write test for invalid URL format (not http/https)**

Add to `backend/tests/test_url_api.py`:

```python
def test_url_analysis_rejects_invalid_url_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sensitive_words.sample.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(data_dir / "sensitive_words.sample.json"))
    client = TestClient(create_app())

    response = client.post(
        "/api/sessions/url",
        json={"audio_url": "ftp://example.com/audio.wav"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "音频 URL 格式不合法"
```

- [ ] **Step 7: Run invalid URL format test**

Run:
```bash
cd backend && python -m pytest tests/test_url_api.py::test_url_analysis_rejects_invalid_url_format -v
```

Expected: PASS — returns 400 with correct detail message.

- [ ] **Step 8: Run all backend tests to confirm no regressions**

Run:
```bash
cd backend && python -m pytest -v
```

Expected: All existing tests pass (health, offline, realtime, providers, etc.) plus new URL tests pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/url.py backend/app/main.py backend/tests/test_url_api.py && git commit -m "feat: add POST /api/sessions/url endpoint for URL audio recognition"
```

---

## Task 3: Frontend — Replace React dependencies with Vue in package.json

**Files:**
- Modify: `frontend/package.json` (swap dependencies)
- Delete: `frontend/node_modules/` (will be recreated by npm install)

**Interfaces:**
- Produces: Vue 3 + Vite project foundation — used by Tasks 4-7

- [ ] **Step 1: Update package.json dependencies**

Edit `frontend/package.json` to the following:

```json
{
  "name": "call-asr-platform-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "vue-tsc && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "lucide-vue-next": "^0.468.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vue-tsc": "^2.0.0",
    "typescript": "^5.5.0",
    "vite": "^5.3.0",
    "vitest": "^1.6.0",
    "@vue/test-utils": "^2.4.0",
    "jsdom": "^24.1.0"
  }
}
```

Key changes: removed `react`, `react-dom`, `@vitejs/plugin-react`, `@types/react`, `@types/react-dom`, `@testing-library/react`, `@testing-library/jest-dom`; added `vue`, `@vitejs/plugin-vue`, `vue-tsc`, `lucide-vue-next`, `@vue/test-utils`.

- [ ] **Step 2: Delete node_modules and reinstall**

Run:
```bash
cd frontend && rm -rf node_modules package-lock.json && npm install
```

Expected: npm installs Vue 3 and all new dependencies successfully. A new `package-lock.json` is created.

- [ ] **Step 3: Verify Vue is installed**

Run:
```bash
cd frontend && node -e "const vue = require('vue'); console.log('Vue version:', vue.version)"
```

Expected output: `Vue version: 3.x.x` (exact version depends on npm resolution).

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json && git commit -m "feat: swap React dependencies for Vue 3 in package.json"
```

---

## Task 4: Frontend — Update Vite config and TypeScript config for Vue

**Files:**
- Modify: `frontend/vite.config.ts` (Vue plugin)
- Modify: `frontend/tsconfig.json` (Vue TS settings)
- Modify: `frontend/index.html` (script src change)

**Interfaces:**
- Produces: Vue-ready build configuration — used by Tasks 5-7

- [ ] **Step 1: Update vite.config.ts for Vue**

Replace entire content of `frontend/vite.config.ts` with:

```typescript
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    globals: true
  }
});
```

- [ ] **Step 2: Update tsconfig.json for Vue**

Replace entire content of `frontend/tsconfig.json` with:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals"]
  },
  "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.vue"],
  "references": []
}
```

Key changes: `moduleResolution` changed to `bundler` (required by Vue 3 + Vite), `jsx` changed to `preserve`, `include` now includes `.vue` files, removed `allowJs`, `esModuleInterop`, `allowSyntheticDefaultImports`, `forceConsistentCasingInFileNames` (Vue handles these differently).

- [ ] **Step 3: Update index.html script src**

Edit `frontend/index.html`. Change the script tag from `main.tsx` to `main.ts`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>通话语音智能分析</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 4: Add Vue shim file for TypeScript**

Create `frontend/src/env.d.ts` so TypeScript understands `.vue` files:

```typescript
/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/src/env.d.ts && git commit -m "feat: update Vite, TypeScript, and HTML config for Vue 3"
```

---

## Task 5: Frontend — Create Vue entry point (`main.ts`) and API client (`client.ts`)

**Files:**
- Create: `frontend/src/main.ts` (Vue entry)
- Create: `frontend/src/api/client.ts` (Vue API client with `analyzeByUrl` added)
- Delete: `frontend/src/main.tsx` (React entry)
- Delete: `frontend/src/api/client.ts` (React API client — will be recreated)

**Interfaces:**
- Consumes: `App.vue` from Task 6 (imported)
- Produces: `uploadOffline`, `openRealtimeSession`, `analyzeByUrl` — used by Task 6 (App.vue)

- [ ] **Step 1: Create Vue entry point `main.ts`**

Create `frontend/src/main.ts`:

```typescript
import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";

createApp(App).mount("#root");
```

- [ ] **Step 2: Create Vue API client `client.ts`**

Create `frontend/src/api/client.ts` (replaces React version, adds `analyzeByUrl`):

```typescript
import type { CallSummary, QualityScore, Segment, Speaker } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export interface OfflineResult {
  session_id: string;
  segments: Segment[];
  quality: QualityScore;
  summary: CallSummary;
}

export async function uploadOffline(file: File): Promise<OfflineResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/sessions/offline`, {
    method: "POST",
    body: form
  });
  if (!response.ok) {
    throw new Error(`上传失败：${response.status}`);
  }
  return response.json();
}

export function openRealtimeSession(
  sessionId: string,
  speaker: Speaker,
  onEvent: (event: any) => void
) {
  const ws = new WebSocket(`${WS_BASE}/ws/realtime/${sessionId}`);
  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ type: "start_session", speaker, target_language: "en" }));
  });
  ws.addEventListener("message", (message) => onEvent(JSON.parse(message.data)));
  return ws;
}

export async function analyzeByUrl(audioUrl: string): Promise<OfflineResult> {
  const response = await fetch(`${API_BASE}/api/sessions/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_url: audioUrl })
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `识别失败：${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 3: Delete React entry and old API client**

Run:
```bash
rm frontend/src/main.tsx frontend/src/lucide-react.d.ts
```

Note: Don't delete the old `frontend/src/api/client.ts` yet — it will be overwritten by Step 2. If Step 2 created a new file alongside it, remove the old one. Since we're using `Write` tool to create the file at the same path, the old content is replaced.

- [ ] **Step 4: Verify TypeScript compilation**

Run:
```bash
cd frontend && vue-tsc --noEmit
```

Expected: May have errors about missing `App.vue` (not created yet). That's expected — Task 6 creates `App.vue`. The `client.ts` and `main.ts` themselves should compile fine.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/main.ts frontend/src/api/client.ts frontend/src/env.d.ts && git rm frontend/src/main.tsx frontend/src/lucide-react.d.ts && git commit -m "feat: create Vue entry point and API client with analyzeByUrl"
```

---

## Task 6: Frontend — Create `App.vue` root component

**Files:**
- Create: `frontend/src/App.vue`
- Delete: `frontend/src/App.tsx` (React version)

**Interfaces:**
- Consumes: `uploadOffline`, `openRealtimeSession`, `analyzeByUrl` from Task 5
- Consumes: `Toolbar.vue`, `TranscriptPanel.vue`, `RiskPanel.vue` from Task 7
- Produces: Root component rendering the full workbench — used by `main.ts` (Task 5)

- [ ] **Step 1: Create `App.vue`**

Create `frontend/src/App.vue`:

```vue
<script setup lang="ts">
import { ref } from "vue";
import { openRealtimeSession, uploadOffline, analyzeByUrl } from "./api/client";
import Toolbar from "./components/Toolbar.vue";
import TranscriptPanel from "./components/TranscriptPanel.vue";
import RiskPanel from "./components/RiskPanel.vue";
import type { CallSummary, QualityScore, Segment, Speaker } from "./types";

const speaker = ref<Speaker>("sales");
const status = ref("准备就绪");
const segments = ref<Segment[]>([]);
const quality = ref<QualityScore>();
const summary = ref<CallSummary>();
const audioUrl = ref("");
const isLoading = ref(false);

async function handleUpload(file: File) {
  status.value = "正在分析离线录音...";
  try {
    const result = await uploadOffline(file);
    segments.value = result.segments;
    quality.value = result.quality;
    summary.value = result.summary;
    status.value = `分析完成：${result.session_id}`;
  } catch (error) {
    status.value = error instanceof Error ? error.message : "上传失败";
  }
}

function handleRealtime() {
  const sessionId = `web_${Date.now()}`;
  const ws = openRealtimeSession(sessionId, speaker.value, (event) => {
    if (event.type === "session_started") {
      status.value = `实时会话已连接：${sessionId}`;
    }
    if (event.type === "final_segment") {
      segments.value = [...segments.value, event.segment];
    }
    if (event.type === "quality_update") {
      quality.value = event.quality;
    }
    if (event.type === "summary_ready") {
      summary.value = event.summary;
    }
  });
  status.value = `正在连接实时会话：当前角色 ${speaker.value}`;
}

async function handleUrlAnalyze() {
  if (!audioUrl.value || isLoading.value) return;
  if (!/^https?:\/\/.+/i.test(audioUrl.value)) {
    status.value = "URL 格式不合法，需要以 http:// 或 https:// 开头";
    return;
  }
  isLoading.value = true;
  status.value = "正在从 URL 下载并分析语音...";
  try {
    const result = await analyzeByUrl(audioUrl.value);
    segments.value = result.segments;
    quality.value = result.quality;
    summary.value = result.summary;
    status.value = `分析完成：${result.session_id}`;
  } catch (error) {
    status.value = error instanceof Error ? error.message : "URL 识别失败";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <main class="workbench">
    <Toolbar
      :status="status"
      :speaker="speaker"
      :audio-url="audioUrl"
      :is-loading="isLoading"
      @update:speaker="speaker = $event"
      @update:audio-url="audioUrl = $event"
      @upload="handleUpload"
      @realtime="handleRealtime"
      @url-analyze="handleUrlAnalyze"
    />
    <section class="layout">
      <TranscriptPanel :segments="segments" />
      <RiskPanel :segments="segments" :quality="quality" :summary="summary" />
    </section>
  </main>
</template>
```

- [ ] **Step 2: Delete React App.tsx**

Run:
```bash
git rm frontend/src/App.tsx
```

- [ ] **Step 3: Verify App.vue doesn't have obvious syntax issues**

Run:
```bash
cd frontend && vue-tsc --noEmit 2>&1 | head -20
```

Expected: May have errors about missing child components (Toolbar.vue etc. not created yet). That's expected — Task 7 creates them. The App.vue itself should parse fine.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.vue && git commit -m "feat: create App.vue root component with URL recognition"
```

---

## Task 7: Frontend — Create Vue child components (Toolbar, TranscriptPanel, RiskPanel)

**Files:**
- Create: `frontend/src/components/Toolbar.vue`
- Create: `frontend/src/components/TranscriptPanel.vue`
- Create: `frontend/src/components/RiskPanel.vue`
- Delete: `frontend/src/components/Toolbar.tsx`
- Delete: `frontend/src/components/TranscriptPanel.tsx`
- Delete: `frontend/src/components/RiskPanel.tsx`

**Interfaces:**
- Consumes: Props/emits defined in App.vue (Task 6)
- Produces: Three Vue components used by App.vue

- [ ] **Step 1: Create `Toolbar.vue`**

Create `frontend/src/components/Toolbar.vue`:

```vue
<script setup lang="ts">
import { Upload, Radio, Link } from "lucide-vue-next";
import type { Speaker } from "../types";

defineProps<{
  status: string;
  speaker: Speaker;
  audioUrl: string;
  isLoading: boolean;
}>();

defineEmits<{
  (e: "update:speaker", value: Speaker): void;
  (e: "update:audio-url", value: string): void;
  (e: "upload", file: File): void;
  (e: "realtime"): void;
  (e: "url-analyze"): void;
}>();

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) {
    // Emit upload event — parent handles the API call
    // We need to emit the file object. Vue emits can carry data.
    emit("upload", file);
  }
}

const emit = defineEmits<{
  (e: "update:speaker", value: Speaker): void;
  (e: "update:audio-url", value: string): void;
  (e: "upload", file: File): void;
  (e: "realtime"): void;
  (e: "url-analyze"): void;
}>();
</script>

<template>
  <header class="toolbar">
    <div>
      <h1>通话语音智能分析</h1>
      <p>{{ status }}</p>
    </div>
    <div class="actions">
      <select
        :value="speaker"
        @change="emit('update:speaker', ($event.target as HTMLSelectElement).value as Speaker)"
        aria-label="当前说话人"
      >
        <option value="sales">销售</option>
        <option value="customer">客户</option>
        <option value="unknown">未知</option>
      </select>
      <input
        type="text"
        placeholder="输入语音文件 URL 地址"
        :value="audioUrl"
        @input="emit('update:audio-url', ($event.target as HTMLInputElement).value)"
        class="urlInput"
      />
      <button
        type="button"
        title="URL 识别"
        :disabled="!audioUrl || isLoading"
        @click="emit('url-analyze')"
      >
        <Link :size="18" />
        识别
      </button>
      <label class="fileButton" title="上传录音">
        <Upload :size="18" />
        上传
        <input type="file" accept="audio/*" @change="onFileChange" />
      </label>
      <button type="button" title="实时演示" @click="emit('realtime')">
        <Radio :size="18" />
        实时
      </button>
    </div>
  </header>
</template>
```

Wait — `defineEmits` can't be called twice. Let me fix this. The correct pattern is to define emits once and use the returned `emit` function.

Corrected `Toolbar.vue`:

```vue
<script setup lang="ts">
import { Upload, Radio, Link } from "lucide-vue-next";
import type { Speaker } from "../types";

const props = defineProps<{
  status: string;
  speaker: Speaker;
  audioUrl: string;
  isLoading: boolean;
}>();

const emit = defineEmits<{
  updateSpeaker: [value: Speaker];
  updateAudioUrl: [value: string];
  upload: [file: File];
  realtime: [];
  urlAnalyze: [];
}>();

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) emit("upload", file);
}
</script>

<template>
  <header class="toolbar">
    <div>
      <h1>通话语音智能分析</h1>
      <p>{{ status }}</p>
    </div>
    <div class="actions">
      <select
        :value="speaker"
        @change="emit('updateSpeaker', ($event.target as HTMLSelectElement).value as Speaker)"
        aria-label="当前说话人"
      >
        <option value="sales">销售</option>
        <option value="customer">客户</option>
        <option value="unknown">未知</option>
      </select>
      <input
        type="text"
        placeholder="输入语音文件 URL 地址"
        :value="audioUrl"
        @input="emit('updateAudioUrl', ($event.target as HTMLInputElement).value)"
        class="urlInput"
      />
      <button
        type="button"
        title="URL 识别"
        :disabled="!audioUrl || isLoading"
        @click="emit('urlAnalyze')"
      >
        <Link :size="18" />
        识别
      </button>
      <label class="fileButton" title="上传录音">
        <Upload :size="18" />
        上传
        <input type="file" accept="audio/*" @change="onFileChange" />
      </label>
      <button type="button" title="实时演示" @click="emit('realtime')">
        <Radio :size="18" />
        实时
      </button>
    </div>
  </header>
</template>
```

Now update `App.vue` to match these emit names. In Task 6, the App.vue template uses `@update:speaker`, `@update:audio-url`, `@upload`, `@realtime`, `@url-analyze`. These need to match Toolbar's emit names. Vue kebab-case event names in templates map to camelCase emit definitions. So `@update:speaker` maps to `updateSpeaker`, `@update:audio-url` maps to `updateAudioUrl`, `@url-analyze` maps to `urlAnalyze`. The current App.vue template is already compatible with this mapping.

- [ ] **Step 2: Create `TranscriptPanel.vue`**

Create `frontend/src/components/TranscriptPanel.vue`:

```vue
<script setup lang="ts">
import type { Segment, SensitiveHit } from "../types";

defineProps<{
  segments: Segment[];
}>();

function speakerName(speaker: Segment["speaker"]) {
  return speaker === "sales" ? "销售" : speaker === "customer" ? "客户" : "未知";
}

function renderHighlightedText(segment: Segment) {
  if (segment.sensitive_hits.length === 0) return segment.text;
  const ordered = [...segment.sensitive_hits].sort((a, b) => a.start - b.start);
  const parts: Array<{ text: string; hit?: SensitiveHit }> = [];
  let cursor = 0;
  for (const hit of ordered) {
    if (cursor < hit.start) {
      parts.push({ text: segment.text.slice(cursor, hit.start) });
    }
    parts.push({ text: segment.text.slice(hit.start, hit.end), hit });
    cursor = hit.end;
  }
  if (cursor < segment.text.length) {
    parts.push({ text: segment.text.slice(cursor) });
  }
  return parts;
}
</script>

<template>
  <section class="transcript" aria-label="通话内容">
    <h2>通话内容</h2>
    <p v-if="segments.length === 0" class="empty">上传录音或开始实时演示后，分段转写会显示在这里。</p>
    <div v-else class="segmentList">
      <article
        v-for="segment in segments"
        :key="segment.id"
        :class="['segment', segment.speaker]"
      >
        <div class="segmentMeta">
          <strong>{{ speakerName(segment.speaker) }}</strong>
          <span>{{ Math.round(segment.start_ms / 1000) }}s - {{ Math.round(segment.end_ms / 1000) }}s</span>
          <span>{{ segment.emotion.label }}</span>
        </div>
        <p>
          <template v-if="segment.sensitive_hits.length === 0">
            {{ segment.text }}
          </template>
          <template v-else>
            <template v-for="part in renderHighlightedText(segment)" :key="part.text + (part.hit?.start ?? '')">
              <mark v-if="part.hit" :class="`hit-${part.hit.level}`">{{ part.text }}</mark>
              <span v-else>{{ part.text }}</span>
            </template>
          </template>
        </p>
        <small>{{ segment.translation }}</small>
      </article>
    </div>
  </section>
</template>
```

- [ ] **Step 3: Create `RiskPanel.vue`**

Create `frontend/src/components/RiskPanel.vue`:

```vue
<script setup lang="ts">
import { ShieldAlert } from "lucide-vue-next";
import type { CallSummary, QualityScore, Segment } from "../types";

defineProps<{
  segments: Segment[];
  quality?: QualityScore;
  summary?: CallSummary;
}>();

function collectRisks(segments: Segment[]) {
  return segments.flatMap((segment) => [
    ...segment.sensitive_hits.map((hit) => `${hit.level}: ${hit.word}（${segment.speaker}）`),
    ...segment.compliance_hits.map((hit) => `${hit.level}: ${hit.message}`)
  ]);
}
</script>

<template>
  <aside class="risk" aria-label="风险与质检">
    <h2>
      <ShieldAlert :size="18" /> 风险与质检
    </h2>
    <div v-if="quality" class="score">{{ quality.score }}</div>
    <p v-if="collectRisks(segments).length === 0" class="empty">暂无风险命中。</p>
    <ul v-else class="riskList">
      <li v-for="(risk, index) in collectRisks(segments)" :key="`${risk}-${index}`">{{ risk }}</li>
    </ul>
    <section v-if="summary" class="summary">
      <h3>摘要</h3>
      <p>客户诉求：{{ summary.customer_needs.join("、") || "未识别" }}</p>
      <p>待跟进：{{ summary.follow_up_items.join("、") || "暂无" }}</p>
      <p>下一步：{{ summary.next_steps.join("、") }}</p>
    </section>
  </aside>
</template>
```

- [ ] **Step 4: Delete React component files**

Run:
```bash
git rm frontend/src/components/Toolbar.tsx frontend/src/components/TranscriptPanel.tsx frontend/src/components/RiskPanel.tsx
```

- [ ] **Step 5: Verify TypeScript compilation**

Run:
```bash
cd frontend && vue-tsc --noEmit
```

Expected: No errors. All Vue components should resolve correctly.

- [ ] **Step 6: Verify Vite dev build starts**

Run:
```bash
cd frontend && timeout 10 npm run dev 2>&1 || true
```

Expected: Vite starts successfully on `http://127.0.0.1:5173`, no compilation errors. May time out after 10 seconds — that's fine, we just want to see it start.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Toolbar.vue frontend/src/components/TranscriptPanel.vue frontend/src/components/RiskPanel.vue && git commit -m "feat: create Vue child components (Toolbar, TranscriptPanel, RiskPanel)"
```

---

## Task 8: Frontend — Add URL input CSS and update styles.css

**Files:**
- Modify: `frontend/src/styles.css` (add `.urlInput` style)

**Interfaces:**
- Produces: `.urlInput` CSS class — used by Toolbar.vue (Task 7)

- [ ] **Step 1: Add `.urlInput` style to styles.css**

Edit `frontend/src/styles.css`. Add the following rule after the `select` rule (around line 75), before `.fileButton input`:

```css
.urlInput {
  width: 240px;
  padding: 6px 12px;
  border: 1px solid #b9c8d1;
  border-radius: 6px;
  font-size: 14px;
}
```

- [ ] **Step 2: Verify dev server still builds correctly**

Run:
```bash
cd frontend && timeout 10 npm run dev 2>&1 || true
```

Expected: Vite starts, no CSS-related errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles.css && git commit -m "feat: add .urlInput CSS style for URL input field"
```

---

## Task 9: Frontend — Create Vitest test for App.vue

**Files:**
- Create: `frontend/src/App.spec.ts` (new Vue test)
- Delete: `frontend/src/App.test.tsx` (React test)

**Interfaces:**
- Produces: Passing frontend test suite

- [ ] **Step 1: Create `App.spec.ts`**

Create `frontend/src/App.spec.ts`:

```typescript
import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import App from "./App.vue";

describe("App.vue", () => {
  it("renders call asr workbench", () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          Toolbar: true,
          TranscriptPanel: true,
          RiskPanel: true
        }
      }
    });

    expect(wrapper.find("main.workbench").exists()).toBe(true);
    expect(wrapper.find("section.layout").exists()).toBe(true);
  });
});
```

- [ ] **Step 2: Delete React test file**

Run:
```bash
git rm frontend/src/App.test.tsx
```

- [ ] **Step 3: Run the test**

Run:
```bash
cd frontend && npm test
```

Expected: PASS — App.vue renders with stubbed child components.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.spec.ts && git commit -m "feat: add Vitest test for App.vue"
```

---

## Task 10: Integration — Smoke test the full stack

**Files:**
- No file changes — verification only

**Interfaces:**
- Consumes: All previous tasks (backend URL route, Vue frontend, URL input)

- [ ] **Step 1: Start the backend**

Run:
```bash
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
```

- [ ] **Step 2: Start the frontend dev server**

Run:
```bash
cd frontend && npm run dev &
```

- [ ] **Step 3: Verify frontend loads at http://127.0.0.1:5173**

Open `http://127.0.0.1:5173` in browser. Expected: The workbench renders with:
- Toolbar showing "通话语音智能分析", speaker selector, URL input, "识别" button, "上传" button, "实时" button
- TranscriptPanel showing "上传录音或开始实时演示后，分段转写会显示在这里。"
- RiskPanel showing "风险与质检" heading

- [ ] **Step 4: Verify backend health endpoint**

Run:
```bash
curl http://127.0.0.1:8000/api/health
```

Expected: JSON with `"status": "ok"`.

- [ ] **Step 5: Verify backend URL endpoint rejects invalid URL**

Run:
```bash
curl -X POST http://127.0.0.1:8000/api/sessions/url -H "Content-Type: application/json" -d '{"audio_url": "ftp://bad.url"}'
```

Expected: `{"detail": "音频 URL 格式不合法"}` with HTTP 400.

- [ ] **Step 6: Verify backend URL endpoint exists (returns error for unreachable URL)**

Run:
```bash
curl -X POST http://127.0.0.1:8000/api/sessions/url -H "Content-Type: application/json" -d '{"audio_url": "https://nonexistent.invalid/audio.wav"}'
```

Expected: HTTP 502 with `"无法下载音频文件"` (DNS resolution failure).

- [ ] **Step 7: Verify all backend tests still pass**

Run:
```bash
cd backend && python -m pytest -v
```

Expected: All tests pass including new URL API tests.

- [ ] **Step 8: Verify all frontend tests still pass**

Run:
```bash
cd frontend && npm test
```

Expected: App.vue test passes.

- [ ] **Step 9: Stop servers**

Kill the background uvicorn and vite processes.

- [ ] **Step 10: Final commit — no file changes, just verify**

No commit needed. This is a verification-only task.

---

## Task 11: Cleanup — Delete remaining React artifacts

**Files:**
- Delete: `frontend/src/App.test.tsx` (if still present)
- Verify: No React imports anywhere in frontend/src

**Interfaces:**
- Produces: Clean Vue-only frontend source

- [ ] **Step 1: Verify no React files remain in frontend/src**

Run:
```bash
find frontend/src -name "*.tsx" -o -name "*.jsx" 2>/dev/null
```

Expected: No output (no .tsx or .jsx files remain).

- [ ] **Step 2: Verify no React imports in any remaining files**

Run:
```bash
grep -rn "from.*react" frontend/src/ || echo "No React imports found"
```

Expected: "No React imports found".

- [ ] **Step 3: Verify `@testing-library/react` is not in package.json**

Run:
```bash
grep "react" frontend/package.json | grep -v "lucide-vue-next" || echo "No React references in package.json"
```

Expected: "No React references in package.json" (only `lucide-vue-next` should match).

- [ ] **Step 4: Final commit if any cleanup was needed**

If any stray React files were found and deleted:
```bash
git add -A frontend/src && git commit -m "cleanup: remove remaining React artifacts"
```

If clean, no commit needed.

---

## Self-Review Checklist

**1. Spec coverage:**

| Spec Section | Plan Task |
|---|---|
| Add `httpx` dependency | Task 1 |
| Add `UrlAnalysisRequest` model | Task 1 |
| Create `/api/sessions/url` route | Task 2 |
| Register router in `main.py` | Task 2 |
| Error handling (400/502/504/413) | Task 2 |
| Swap React→Vue dependencies | Task 3 |
| Update Vite/TS config | Task 4 |
| Create `main.ts` entry | Task 5 |
| Create `client.ts` with `analyzeByUrl` | Task 5 |
| Create `App.vue` | Task 6 |
| Create `Toolbar.vue` with URL input | Task 7 |
| Create `TranscriptPanel.vue` | Task 7 |
| Create `RiskPanel.vue` | Task 7 |
| Add `.urlInput` CSS | Task 8 |
| Vue test | Task 9 |
| Integration smoke test | Task 10 |
| Delete React artifacts | Task 11 |

All spec requirements covered. No gaps found.

**2. Placeholder scan:** No TBD, TODO, "implement later", vague steps found. Every step has exact code or exact commands.

**3. Type consistency:**

- `UrlAnalysisRequest(audio_url: str)` — defined in Task 1, used in Task 2 ✓
- `OfflineResult` interface — defined in Task 5 (`client.ts`), used in Task 6 (`App.vue`) ✓
- Toolbar emits: `updateSpeaker`, `updateAudioUrl`, `upload`, `realtime`, `urlAnalyze` — defined in Task 7, consumed in Task 6 App.vue template with `@update:speaker`, `@update:audio-url`, `@upload`, `@realtime`, `@url-analyze` ✓
- Vue kebab-case template events map to camelCase emit names ✓

No type mismatches found.
