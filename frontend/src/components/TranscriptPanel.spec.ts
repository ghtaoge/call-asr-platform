import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";
import TranscriptPanel from "./TranscriptPanel.vue";
import type { Segment } from "../types";

function segment(id: string, start: number, end: number, text: string): Segment {
  return {
    id,
    session_id: "call_1",
    speaker: "customer",
    start_ms: start,
    end_ms: end,
    text,
    translation: "",
    language: "zh",
    target_language: "zh",
    emotion: { label: "neutral", confidence: 0.8, score: 0 },
    sensitive_hits: [],
    compliance_hits: [],
    confidence: 0.9,
    is_final: true
  };
}

describe("TranscriptPanel", () => {
  it("shows sentence time ranges and follows audio progress", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView
    });
    const wrapper = mount(TranscriptPanel, {
      props: {
        segments: [
          segment("first", 1000, 2500, "第一句话。"),
          segment("second", 3000, 4800, "第二句话。")
        ],
        activeTime: 0,
        mode: "sentence",
        speaker: "all"
      }
    });

    expect(wrapper.text()).toContain("00:01 - 00:02");
    await wrapper.setProps({ activeTime: 3200 });
    await nextTick();

    expect(wrapper.find(".segmentRow.active").text()).toContain("第二句话。");
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "nearest" });

    await wrapper.setProps({ activeTime: 6000 });
    await nextTick();
    expect(wrapper.find(".segmentRow.active").text()).toContain("第二句话。");

    await wrapper.findAll("button[aria-label='朗读本句']")[1].trigger("click");
    expect(wrapper.emitted("synthesize")?.[0]).toEqual(["第二句话。"]);
    expect(wrapper.find(".segmentRow").attributes("role")).toBeUndefined();
  });
});
