// One utterance as the transcript routes take it: 16 kHz 16-bit mono PCM behind a 44-byte WAV header, made from the
// microphone's float samples at whatever rate the browser's audio runs.

export const RATE = 16000;

/** `samples` (at `fromRate`, -1..1) at 16 kHz, each output sample the mean of the input samples it covers. */
export function downsample(samples: Float32Array, fromRate: number): Int16Array<ArrayBuffer> {
  const ratio = fromRate / RATE;
  const out = new Int16Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.max(start + 1, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j]!;
    const mean = Math.max(-1, Math.min(1, sum / (end - start)));
    out[i] = mean < 0 ? mean * 0x8000 : mean * 0x7fff;
  }
  return out;
}

/** `pcm` (16 kHz mono) as a WAV file. */
export function wav(pcm: Int16Array<ArrayBuffer>): Blob {
  const header = new DataView(new ArrayBuffer(44));
  const text = (at: number, s: string) => [...s].forEach((c, i) => header.setUint8(at + i, c.charCodeAt(0)));
  const bytes = pcm.length * 2;
  text(0, 'RIFF');
  header.setUint32(4, 36 + bytes, true);
  text(8, 'WAVEfmt ');
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true); // PCM
  header.setUint16(22, 1, true); // mono
  header.setUint32(24, RATE, true);
  header.setUint32(28, RATE * 2, true);
  header.setUint16(32, 2, true);
  header.setUint16(34, 16, true);
  text(36, 'data');
  header.setUint32(40, bytes, true);
  return new Blob([header, pcm], { type: 'audio/wav' });
}
