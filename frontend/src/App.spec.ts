import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import App from "./App.vue";

describe("App.vue", () => {
  it("renders call asr workbench", () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          Toolbar: true,
          JobProgress: true,
          AudioPlayer: true,
          EmotionChart: true,
          TranscriptPanel: true,
          QualityPanel: true,
          SensitivePanel: true,
          SummaryPanel: true
        }
      }
    });

    expect(wrapper.find("main.workbench").exists()).toBe(true);
    expect(wrapper.find("section.initialState").exists()).toBe(true);
  });
});
