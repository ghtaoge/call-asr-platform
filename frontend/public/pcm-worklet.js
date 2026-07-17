class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = [];
    this.cursor = 0;
    this.ratio = sampleRate / 16000;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    while (this.cursor < input.length) {
      this.pending.push(Math.max(-1, Math.min(1, input[Math.floor(this.cursor)])));
      this.cursor += this.ratio;
    }
    this.cursor -= input.length;
    while (this.pending.length >= 320) {
      const pcm = new Int16Array(320);
      for (let index = 0; index < 320; index += 1) {
        pcm[index] = Math.round(this.pending[index] * 32767);
      }
      this.pending.splice(0, 320);
      this.port.postMessage(pcm, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PcmWorklet);
