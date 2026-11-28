// A control's press as every shell shows it: running, then done, failed or busy for a moment, then nothing. Each shell
// hands in its own route and what to read again after, so the kiosk's cookie routes and a person's session share it.
import type { Signal } from '@preact/signals';
import { ApiError } from '../../api/client';
import type { ControlState } from './sources';

export const CONTROL_SHOWN_MS = 2500;

export interface Pressing {
  states: Signal<Readonly<Record<string, ControlState>>>;
  /** Carries out the control; whether her tool reported it done. */
  run(name: string): Promise<boolean>;
  /** Reads the controls again after a press, for a light's new state. */
  reread(): Promise<void>;
  /** A shell's own handling of a failed press (a kiosk unpaired); true when it handled it and nothing is shown. */
  handled?(error: unknown): boolean;
}

function set(states: Pressing['states'], name: string, state: ControlState | null): void {
  const next = { ...states.value };
  if (state === null) delete next[name];
  else next[name] = state;
  states.value = next;
}

/** The press of `name`: shown running, then done or failed (busy on a 429) for CONTROL_SHOWN_MS. */
export function pressWith(p: Pressing): (name: string) => Promise<void> {
  return async (name) => {
    set(p.states, name, 'running');
    let shown: ControlState;
    try {
      shown = (await p.run(name)) ? 'done' : 'failed';
      await p.reread();
    } catch (error) {
      if (p.handled?.(error)) return;
      shown = error instanceof ApiError && error.status === 429 ? 'busy' : 'failed';
    }
    set(p.states, name, shown);
    setTimeout(() => {
      if (p.states.value[name] === shown) set(p.states, name, null);
    }, CONTROL_SHOWN_MS);
  };
}
