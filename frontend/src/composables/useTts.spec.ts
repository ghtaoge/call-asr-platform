import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTts } from "./useTts";

const api = vi.hoisted(() => ({
  cloneTtsVoice: vi.fn(),
  createTtsJob: vi.fn(),
  getTtsJob: vi.fn(),
  ttsAudioUrl: vi.fn((jobId: string, download = false) =>
    `/api/tts/jobs/${jobId}/audio${download ? "?download=true" : ""}`
  )
}));

vi.mock("../api/client", () => api);

describe("useTts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls a synthesis job until playable audio is available", async () => {
    api.createTtsJob.mockResolvedValue({
      job_id: "tts_1",
      voice_id: "voice_1",
      status: "queued"
    });
    api.getTtsJob
      .mockResolvedValueOnce({ job_id: "tts_1", voice_id: "voice_1", status: "running" })
      .mockResolvedValueOnce({ job_id: "tts_1", voice_id: "voice_1", status: "completed" });

    let tts!: ReturnType<typeof useTts>;
    const wrapper = mount(defineComponent({
      setup() {
        tts = useTts();
        return () => h("div");
      }
    }));
    tts.voice.value = {
      voice_id: "voice_1",
      prompt_text: "参考内容。",
      expires_at: "2026-07-24T00:00:00Z"
    };

    await tts.synthesize("需要合成的内容。");
    await vi.runAllTimersAsync();

    expect(tts.job.value?.status).toBe("completed");
    expect(tts.audioUrl.value).toBe("/api/tts/jobs/tts_1/audio");
    expect(tts.downloadUrl.value).toBe("/api/tts/jobs/tts_1/audio?download=true");
    wrapper.unmount();
  });
});
