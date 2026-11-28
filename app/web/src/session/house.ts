// The house as a signed-in person's screens show it: the parts' sources backed by the person's routes (`api/house.ts`).
// Nothing announces a person coming or going, so the glance is read on a timer; it is also read when the live feed
// (re)opens and on a turn on any thread, since a turn can leave something waiting on the person. A light's state is read
// with it, and after every press.
import { computed, signal } from '@preact/signals';
import { ApiError } from '../api/client';
import { getHouseControls, getHouseGlance, pressHouseControl } from '../api/house';
import type { HouseGlance, KioskControl } from '../api/types';
import { pressWith } from '../components/parts/press';
import type { AttentionSource, ControlState, ControlsSource, HomeSource } from '../components/parts/sources';
import { onResync, onThreadTurn } from './live';
import { load as reloadSession } from './session';

export const GLANCE_MS = 60_000;

const glance = signal<HouseGlance | null | undefined>(undefined);
const controls = signal<readonly KioskControl[] | null | undefined>(undefined);
const states = signal<Readonly<Record<string, ControlState>>>({});

function signedOut(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 401) return false;
  void reloadSession();
  return true;
}

async function readControls(): Promise<void> {
  try {
    controls.value = await getHouseControls();
  } catch (error) {
    if (!signedOut(error)) controls.value = null;
  }
}

/** Reads the glance again, and the controls with it while any of them shows a light's state. */
export async function readGlance(): Promise<void> {
  try {
    glance.value = await getHouseGlance();
  } catch (error) {
    if (!signedOut(error)) glance.value = null;
  }
  if (controls.value?.some((c) => c.on !== null)) await readControls();
}

export const houseControls: ControlsSource = {
  controls,
  states,
  press: pressWith({ states, run: pressHouseControl, reread: readControls, handled: signedOut }),
};
export const houseHome: HomeSource = { home: computed(() => glance.value?.home) };
export const houseAttention: AttentionSource = {
  attention: computed(() => (glance.value === undefined ? undefined : glance.value?.needs_attention ?? null)),
};

/** Reads the house now, then on the glance's timer while the page is visible and on each cue above; returns the stop. */
export function watchHouse(): () => void {
  void Promise.all([readGlance(), readControls()]);
  const timer = setInterval(() => {
    if (!document.hidden) void readGlance();
  }, GLANCE_MS);
  const off = [onResync(() => void Promise.all([readGlance(), readControls()])), onThreadTurn(() => void readGlance())];
  return () => {
    clearInterval(timer);
    off.forEach((o) => o());
  };
}
