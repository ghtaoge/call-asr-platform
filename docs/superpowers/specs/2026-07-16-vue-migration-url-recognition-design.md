# Vue 3 Migration + URL Audio Recognition — Design Spec

**Date**: 2026-07-16
**Status**: Approved

## Summary

Two merged tasks in one design:

1. **Migrate frontend from React to Vue 3** (Composition API + TypeScript + pure CSS)
2. **Add URL audio recognition** — a new input field in the Toolbar where users paste a remote audio file URL; the backend downloads the audio and runs the existing analysis pipeline.

The backend adds a single new route (`POST /api/sessions/url`) using `httpx` to fetch the remote audio. The frontend gets a URL text input and "识别" button alongside the existing upload and realtime controls. All existing functionality (file upload, realtime WebSocket) is preserved.

## Backend: URL Audio Recognition API

### New Endpoint

```
POST /api/sessions/url
Content-Type: application/json

Request body:
{
  "audio_url": "https://cctestcall.gooeto.com:6243/audio/file?linkId=juse-f47cfc64-e7dd-475b-9b3e-bbe538199a9e&nonce_str=...&Token=...&timestamp=...&key=...&sign=..."
}
```

**Response**: identical to `POST /api/sessions/offline` — uses existing `OfflineAnalysisResponse` model (session_id, segments, quality, summary).

### Implementation

1. **Add `httpx` dependency** to `backend/pyproject.toml`. `httpx` is an async HTTP client that replaces the need for `requests`/`aiohttp`.

2. **Create `backend/app/api/url.py`**:
   - Accept `UrlAnalysisRequest` body with `audio_url: str` field.
   - Validate the URL starts with `http://` or `https://`.
   - Use `httpx.AsyncClient` to download audio bytes with timeout (default 30s) and max-size guard (default 50MB).
   - Pass downloaded bytes to `SessionService.analyze_offline(audio)` — **fully reuse existing pipeline**.
   - Return `OfflineAnalysisResponse`.

3. **Add `UrlAnalysisRequest` model** to `backend/app/core/models.py`:
   ```python
   class UrlAnalysisRequest(BaseModel):
       audio_url: str
   ```

4. **Register the router** in `backend/app/main.py` — include `url.router` alongside existing routers.

5. **CORS**: no changes needed; existing config already allows frontend origins.

### Error Handling

| Scenario | HTTP Status | Error Detail |
|---|---|---|
| URL format invalid (not http/https) | 400 | "音频 URL 格式不合法" |
| Download fails (network error, DNS failure) | 502 | "无法下载音频文件" |
| Remote server returns non-audio content | 400 | "URL 返回的内容不是有效的音频文件" |
| Download timeout (exceeds 30s) | 504 | "下载音频文件超时" |
| Downloaded file exceeds 50MB | 413 | "音频文件过大" |

### Files Modified/Created

| File | Action |
|---|---|
| `backend/pyproject.toml` | Add `httpx` dependency |
| `backend/app/core/models.py` | Add `UrlAnalysisRequest` |
| `backend/app/api/url.py` | New file — route handler |
| `backend/app/main.py` | Include new router |

## Frontend: React → Vue 3 Migration

### Project Structure

```
frontend/
  src/
    main.ts              # Entry: createApp + mount
    App.vue              # Root component (replaces App.tsx)
    api/
      client.ts          # API client (migrated + new analyzeByUrl)
    components/
      Toolbar.vue        # Toolbar (migrated + URL input added)
      TranscriptPanel.vue # Transcript panel (migrated)
      RiskPanel.vue      # Risk panel (migrated)
    types.ts             # TypeScript types (unchanged)
    styles.css           # Global CSS (unchanged, minor Vue tweaks)
  index.html             # HTML entry
  vite.config.ts         # Vite config (@vitejs/plugin-vue)
  tsconfig.json          # TS config for Vue
  package.json           # Dependencies updated
```

### Dependency Changes

| Remove | Replace With |
|---|---|
| `react`, `react-dom` | `vue` |
| `@vitejs/plugin-react` | `@vitejs/plugin-vue` |
| `@types/react`, `@types/react-dom` | `vue-tsc` |
| `lucide-react` | `lucide-vue-next` |

Keep unchanged: `vite`, `typescript`, `vitest`, `@testing-library/*`, `jsdom`.

### Component Migration

| React Component | Vue Component | Key Changes |
|---|---|---|
| `App.tsx` (useState/useRef) | `App.vue` (ref) | `useState` → `ref()`; `useRef` → `ref()`; JSX → template |
| `Toolbar.tsx` | `Toolbar.vue` | Props → `defineProps`; events → `defineEmits`; JSX → template |
| `TranscriptPanel.tsx` | `TranscriptPanel.vue` | `.map()` → `v-for`; conditional → `v-if`/`v-else` |
| `RiskPanel.tsx` | `RiskPanel.vue` | Same pattern as TranscriptPanel |

### CSS Strategy

Keep existing `styles.css` as global stylesheet. No `<style scoped>` in Vue components — consistent with the current approach. Minor adjustments only where React-specific class names or DOM structure differ.

### Testing

Replace `@testing-library/react` tests with `@testing-library/vue` (or `vue-test-utils`). The single existing test (`App.test.tsx`) will be rewritten as `App.spec.ts` using Vitest.

## Frontend: URL Input Feature

### Toolbar.vue — New Elements

Inside the `.actions` div, alongside the existing speaker selector, upload button, and realtime button:

```html
<input
  type="text"
  placeholder="输入语音文件 URL 地址"
  :value="audioUrl"
  @input="$emit('update:audioUrl', $event.target.value)"
  class="urlInput"
/>
<button
  type="button"
  title="URL 识别"
  :disabled="!audioUrl || isLoading"
  @click="$emit('urlAnalyze', audioUrl)"
>
  <Link :size="18" />
  识别
</button>
```

The `Link` icon comes from `lucide-vue-next`.

Toolbar receives `audioUrl` and `isLoading` as props from App, and emits `update:audioUrl` and `urlAnalyze` events. The state lives in `App.vue`.

### App.vue — New State and Handler

```typescript
const audioUrl = ref("");
const isLoading = ref(false);

async function handleUrlAnalyze() {
  if (!audioUrl.value || isLoading.value) return;
  // Basic format check
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
```

Toolbar emits `urlAnalyze(audioUrl)` to App. App calls `analyzeByUrl` and updates state the same way as `handleUpload`.

### API Client — New Method

```typescript
// client.ts addition
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

### URL Validation

Frontend does minimal format validation only: the URL must start with `http://` or `https://`. Accessibility and content-type checks are left to the backend.

### CSS Addition

```css
.urlInput {
  width: 240px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
}
```

## Data Flow

```
User pastes URL in Toolbar input
  → Toolbar emits urlAnalyze event with audioUrl string
  → App.handleUrlAnalyze() validates URL format
  → App calls analyzeByUrl(audioUrl) → POST /api/sessions/url
  → Backend: httpx downloads audio bytes from remote URL
  → Backend: SessionService.analyze_offline(audio_bytes) runs full pipeline
  → Backend returns OfflineAnalysisResponse
  → App updates segments, quality, summary state
  → UI renders results in TranscriptPanel and RiskPanel
```

## Scope Boundaries

- **In scope**: React→Vue migration, URL input + backend URL route, all existing features preserved
- **Out of scope**: No UI framework (Element Plus etc.), no state management library (Pinia etc.), no backend pipeline changes, no new WebSocket features, no session listing/history

## Files to Delete (React)

After migration is complete and verified:

- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `frontend/src/main.tsx`
- `frontend/src/components/Toolbar.tsx`
- `frontend/src/components/TranscriptPanel.tsx`
- `frontend/src/components/RiskPanel.tsx`
- `frontend/src/api/client.ts` (replaced by new Vue version)
- `frontend/src/lucide-react.d.ts`

## Success Criteria

1. Vue 3 frontend renders identically to the current React version for all existing features
2. URL input accepts a valid audio URL and produces the same analysis results as file upload
3. Invalid URLs show clear error messages in the status bar
4. Loading state disables the "识别" button and shows progress status
5. Backend `POST /api/sessions/url` returns same response shape as `/api/sessions/offline`
6. All existing features (upload, realtime) work unchanged
7. Tests pass for both backend and frontend
