import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import TtsPanel from "./TtsPanel.vue";

describe("TtsPanel", () => {
  it("preloads transcript text and requires voice authorization", () => {
    const wrapper = mount(TtsPanel, { props: { initialText: "需要朗读的句子。" } });
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("需要朗读的句子。");
    expect(wrapper.text()).toContain("请先确认声音使用授权");
    expect(wrapper.get("button.ttsSubmit").attributes("disabled")).toBeDefined();
  });
});
