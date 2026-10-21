import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import StatusPill from "./StatusPill.vue";

describe("StatusPill", () => {
  it("describes each status in plain words", () => {
    expect(mount(StatusPill, { props: { status: "succeeded" } }).text()).toContain("Ready");
    expect(mount(StatusPill, { props: { status: "failed" } }).text()).toContain("Failed");
    expect(mount(StatusPill, { props: { status: "queued" } }).text()).toContain("In the queue");
  });

  it("shows the percentage while a render is running", () => {
    const wrapper = mount(StatusPill, { props: { status: "processing", progress: 42 } });

    expect(wrapper.text()).toContain("42%");
  });

  it("omits a meaningless 0% at the very start of a render", () => {
    const wrapper = mount(StatusPill, { props: { status: "processing", progress: 0 } });

    expect(wrapper.text()).not.toContain("0%");
    expect(wrapper.text()).toContain("Working on it");
  });
});
