// The loading reveal (T2): once the session and her health are back, the answered lines tick in 420ms apart while the
// reticle turns; on the last it locks, and the shell then pulls the camera back to the room the path names.
import { signal } from '@preact/signals';
import { pause, reduced } from '../shell/motion';

const TICK_MS = 420;
const LOCK_AFTER_MS = 300;
const LOCK_MS = 700;
/** Under reduced motion the lines appear together and stay this long, so they are read rather than flashed. */
const REDUCED_HOLD_MS = 600;

export const revealing = signal(false);
/** How many loading lines have ticked in. */
export const ticked = signal(0);
export const locked = signal(false);
/** True once the reveal has finished; the shell shows rooms only then. */
export const revealed = signal(false);

export async function reveal(lines: number): Promise<void> {
  revealing.value = true;
  locked.value = false;
  ticked.value = 0;
  if (reduced()) {
    ticked.value = lines;
    await new Promise((resolve) => setTimeout(resolve, REDUCED_HOLD_MS));
  } else {
    for (let i = 0; i < lines; i++) {
      await pause(TICK_MS);
      ticked.value = i + 1;
    }
    await pause(LOCK_AFTER_MS);
    locked.value = true;
    await pause(LOCK_MS);
  }
  revealing.value = false;
  revealed.value = true;
}

/** Back to the sign-in face: signed out, or about to load again. */
export function unreveal(): void {
  revealing.value = false;
  revealed.value = false;
  locked.value = false;
  ticked.value = 0;
}
