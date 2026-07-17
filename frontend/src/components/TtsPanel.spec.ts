import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import TtsPanel from "./TtsPanel.vue";

vi.mock("../api/client", () => ({
  cloneTtsVoice: vi.fn(),
  createTtsJob: vi.fn(),
  getTtsJob: vi.fn(),
  getTtsPresetVoices: vi.fn().mockResolvedValue([
    { id: "zh_female", voice_id: "preset:zh_female", label: "普通话女声", language: "普通话", gender: "female" },
    { id: "zh_male", voice_id: "preset:zh_male", label: "普通话男声", language: "普通话", gender: "male" }
  ]),
  ttsAudioUrl: vi.fn()
}));

describe("TtsPanel", () => {
  it("preloads transcript text and offers default voices before custom cloning", async () => {
    const wrapper = mount(TtsPanel, { props: { initialText: "需要朗读的句子。" } });
    await flushPromises();

    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("需要朗读的句子。");
    expect(wrapper.get("select[aria-label='选择默认音色']").findAll("option")).toHaveLength(2);
    expect(wrapper.get("button.ttsSubmit").attributes("disabled")).toBeUndefined();

    await wrapper.get(".voiceMode button:nth-child(2)").trigger("click");
    expect(wrapper.text()).toContain("请先确认声音使用授权");
    expect(wrapper.get("button.ttsSubmit").attributes("disabled")).toBeDefined();
  });
});
