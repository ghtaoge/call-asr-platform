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
