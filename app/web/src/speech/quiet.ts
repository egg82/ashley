// When the person has stopped talking, judged from the microphone's own samples: energy per short window, since the
// browser has no voice-activity model. The timings are the server's (`SpokenLimits`), the Echo's `end_of_speech`.

export interface QuietTuning {
  /** Speech heard, in all, before a silence can end the utterance. */
  speechMs: number;
  /** Quiet, unbroken, that ends the utterance once enough speech was heard. */
  silenceMs: number;
  /** A window whose RMS (samples in -1..1) is at least this is speech. */
  threshold: number;
}

/** Longest stretch judged as one: shorter than a voice's pitch period would read speech as flicker. */
export const WINDOW_MS = 20;

export class Quiet {
  private energy = 0;
  private count = 0;
  private spoken = 0;
  private silent = 0;
  private done = false;

  private readonly tuning: QuietTuning;
  private readonly rate: number;

  constructor(tuning: QuietTuning, rate: number) {
    this.tuning = tuning;
    this.rate = rate;
  }

  /** Takes the next samples, of any length; answers true from the moment the person has stopped talking. */
  push(block: Float32Array): boolean {
    const size = Math.round((WINDOW_MS / 1000) * this.rate);
    for (const sample of block) {
      this.energy += sample * sample;
      if (++this.count >= size) this.judge(Math.sqrt(this.energy / this.count));
    }
    return this.done;
  }

  private judge(rms: number): void {
    const ms = (this.count / this.rate) * 1000;
    this.energy = 0;
    this.count = 0;
    if (rms >= this.tuning.threshold) {
      this.spoken += ms;
      this.silent = 0;
    } else if (this.spoken >= this.tuning.speechMs) {
      this.silent += ms;
      if (this.silent >= this.tuning.silenceMs) this.done = true;
    }
  }
}
