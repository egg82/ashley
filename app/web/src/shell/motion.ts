// Full or reduced motion. `?motion=reduced|full` wins, then the person's own switch (kept in this browser), then the
// OS setting. The choice lands on `<html data-motion>`, which every transition's reduced variant keys on.
import { effect, signal } from '@preact/signals';

export type Motion = 'full' | 'reduced';

const KEY = 'ashley.motion';
const os = matchMedia('(prefers-reduced-motion: reduce)');

function parse(value: string | null): Motion | null {
  return value === 'full' || value === 'reduced' ? value : null;
}

function stored(): Motion | null {
  try {
    return parse(localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

function initial(): Motion {
  const asked = parse(new URLSearchParams(location.search).get('motion')) ?? stored();
  return asked ?? (os.matches ? 'reduced' : 'full');
}

export const motion = signal<Motion>(initial());

effect(() => {
  document.documentElement.dataset.motion = motion.value;
});

export function reduced(): boolean {
  return motion.value === 'reduced';
}

/** The person's switch: flips motion and remembers it in this browser. */
export function toggleMotion(): void {
  motion.value = reduced() ? 'full' : 'reduced';
  try {
    localStorage.setItem(KEY, motion.value);
  } catch {
    // Storage blocked (private window): the switch still works for this visit.
  }
}

/** A pause that is skipped under reduced motion, for sequenced reveals. */
export function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, reduced() ? 0 : ms));
}
