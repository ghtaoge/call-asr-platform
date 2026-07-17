import { describe, expect, it } from "vitest";
import { encodeAudioFrame } from "./frame";

describe("encodeAudioFrame", () => {
  it("writes the versioned big-endian header and little-endian PCM", () => {
    const frame = encodeAudioFrame(7, 1784300000000n, new Int16Array([1, -2]));
    const view = new DataView(frame);
    expect(view.getUint8(0)).toBe(1);
    expect(view.getUint32(4, false)).toBe(7);
    expect(view.getBigUint64(8, false)).toBe(1784300000000n);
    expect(view.getInt16(16, true)).toBe(1);
    expect(view.getInt16(18, true)).toBe(-2);
  });
});
