import { describe, expect, it } from "vitest";

import { aspectLabel, formatBytes, formatDuration, formatTimecode, speedLabel } from "./format";

describe("formatBytes", () => {
  it("handles zero and nonsense", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(null)).toBe("0 B");
    expect(formatBytes(-5)).toBe("0 B");
  });

  it("shows bytes, kilobytes, megabytes and gigabytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB");
  });

  it("drops the decimal once the number is large enough not to need it", () => {
    expect(formatBytes(15 * 1024 * 1024)).toBe("15 MB");
  });
});

describe("formatDuration", () => {
  it("formats under a minute", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(9)).toBe("0:09");
    expect(formatDuration(59)).toBe("0:59");
  });

  it("formats minutes and hours", () => {
    expect(formatDuration(60)).toBe("1:00");
    expect(formatDuration(605)).toBe("10:05");
    expect(formatDuration(3661)).toBe("1:01:01");
  });

  it("does not produce something misleading for bad input", () => {
    expect(formatDuration(-1)).toBe("0:00");
    expect(formatDuration(Number.NaN)).toBe("0:00");
    expect(formatDuration(undefined)).toBe("0:00");
  });
});

describe("formatTimecode", () => {
  it("keeps a tenth of a second, which trim points need", () => {
    expect(formatTimecode(0)).toBe("0:00.0");
    expect(formatTimecode(5.44)).toBe("0:05.4");
    expect(formatTimecode(65.5)).toBe("1:05.5");
  });

  it("pads the seconds so the width does not jump while dragging", () => {
    expect(formatTimecode(61.2)).toBe("1:01.2");
  });
});

describe("labels", () => {
  it("names the speeds the way the UI shows them", () => {
    expect(speedLabel(1)).toBe("Normal");
    expect(speedLabel(0.5)).toBe("0.5x");
    expect(speedLabel(2)).toBe("2x");
  });

  it("names aspect ratios in plain words", () => {
    expect(aspectLabel("9:16")).toBe("Vertical 9:16");
    expect(aspectLabel("original")).toBe("Original");
    expect(aspectLabel("unknown-key")).toBe("unknown-key");
  });
});
