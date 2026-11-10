// The microphone, opened only when the person presses to talk and closed as soon as they stop: its samples are
// collected in this tab and become one WAV (`wav.ts`). Nothing is sent while recording.
import { Quiet, type QuietTuning } from './quiet';
import { downsample, wav } from './wav';

export type MicRefusal = 'denied' | 'no-mic' | 'unsupported';

export class MicRefused extends Error {
  constructor(readonly why: MicRefusal) {
    super(why);
  }
}

export interface Recording {
  /** Stops and answers what was heard as a WAV of at most `maxMs`. */
  stop(): Promise<Blob>;
  /** Stops and throws the audio away. */
  cancel(): void;
}

// The processor runs on the audio thread and hands each block of samples back; it is a module of its own there.
const TAP = `registerProcessor('ashley-tap', class extends AudioWorkletProcessor {
  process(inputs) { const c = inputs[0] && inputs[0][0]; if (c) this.port.postMessage(c.slice(0)); return true; }
});`;

export function canRecord(): boolean {
  return typeof navigator.mediaDevices?.getUserMedia === 'function' && typeof AudioWorkletNode === 'function';
}

function refusal(error: unknown): MicRefusal {
  const name = error instanceof DOMException ? error.name : '';
  return name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'no-mic';
}

async function open(): Promise<MediaStream> {
  if (!canRecord()) throw new MicRefused('unsupported');
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (error) {
    throw new MicRefused(refusal(error));
  }
}

/** Opens the microphone and records until stopped, or until `maxMs`, when `onFull` is called, or until the person
 *  stops talking by `quiet`, when `onQuiet` is called (the recording goes on until it is stopped). Throws MicRefused. */
export async function record(maxMs: number, onFull: () => void, quiet: QuietTuning, onQuiet: () => void):
    Promise<Recording> {
  const stream = await open();
  const context = new AudioContext();
  const blocks: Float32Array[] = [];
  const most = Math.floor((maxMs / 1000) * context.sampleRate);
  const ender = new Quiet(quiet, context.sampleRate);
  let held = 0;
  let quieted = false;
  const close = () => {
    stream.getTracks().forEach((t) => t.stop());
    void context.close();
  };
  try {
    await context.resume();
    const url = URL.createObjectURL(new Blob([TAP], { type: 'text/javascript' }));
    await context.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const tap = new AudioWorkletNode(context, 'ashley-tap');
    tap.port.onmessage = (e: MessageEvent<Float32Array>) => {
      if (held >= most) return;
      const block = e.data.subarray(0, most - held);
      blocks.push(block);
      held += block.length;
      if (held >= most) onFull();
      if (!quieted && ender.push(block)) {
        quieted = true;
        onQuiet();
      }
    };
    context.createMediaStreamSource(stream).connect(tap).connect(context.destination);
  } catch {
    close();
    throw new MicRefused('unsupported');
  }
  return {
    async stop() {
      const rate = context.sampleRate;
      close();
      const all = new Float32Array(held);
      blocks.reduce((at, b) => (all.set(b, at), at + b.length), 0);
      return wav(downsample(all, rate));
    },
    cancel: close,
  };
}
