class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input.length > 0) {
      const inputChannel = input[0];
      const pcmData = new Int16Array(inputChannel.length);
      for (let i = 0; i < inputChannel.length; i++) {
        const s = Math.max(-1, Math.min(1, inputChannel[i]));
        pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      this.port.postMessage(pcmData.buffer);
    }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);

