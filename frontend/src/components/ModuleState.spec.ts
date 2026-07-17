import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ModuleState from "./ModuleState.vue";

describe("ModuleState", () => {
  it("retries only the failed module", async () => {
    const wrapper = mount(ModuleState, {
      props: {
        module: "emotion",
        label: "情绪分析",
        status: "failed",
        error: "模型暂时不可用"
      }
    });

    expect(wrapper.text()).toContain("模型暂时不可用");
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("retry")).toEqual([["emotion"]]);
  });
});
