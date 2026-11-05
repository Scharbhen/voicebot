// AudioWorklet: берёт звук с микрофона, пересэмплирует в targetRate и отдаёт PCM16 кусками ~100 мс.
class PcmCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = options.processorOptions.targetRate;
    this.ratio = sampleRate / this.targetRate; // входных сэмплов на один выходной
    this.pos = 0;           // дробная позиция чтения во входном потоке
    this.prev = 0;          // последний сэмпл предыдущего блока (для интерполяции)
    this.chunk = new Int16Array(Math.round(this.targetRate / 10));
    this.fill = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    let level = 0;
    // линейная интерполяция; индекс -1 — это this.prev
    while (this.pos < input.length) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = i === 0 ? this.prev : input[i - 1];
      const b = input[i];
      let s = a + (b - a) * frac;
      s = Math.max(-1, Math.min(1, s));
      level = Math.max(level, Math.abs(s));
      this.chunk[this.fill++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.fill === this.chunk.length) {
        this.port.postMessage({ pcm: this.chunk.buffer, level }, [this.chunk.buffer]);
        this.chunk = new Int16Array(Math.round(this.targetRate / 10));
        this.fill = 0;
        level = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= input.length;
    this.prev = input[input.length - 1];
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);
