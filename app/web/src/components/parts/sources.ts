// What a part reads and does, handed in by the shell that draws it: a shell backs these with its own signals and routes,
// so the same part serves the kiosk's cookie routes and a person's session alike.
import type { ReadonlySignal } from '@preact/signals';
import type { HouseAttention, HousePrinter, KioskControl, MemoryFact, Voiceprint } from '../../api/types';

export type ControlState = 'running' | 'done' | 'failed' | 'busy';

export interface ControlsSource {
  /** The controls: null when they could not be read, undefined before they are. */
  controls: ReadonlySignal<readonly KioskControl[] | null | undefined>;
  /** Each control's press state by name; a control not pressed lately has none. */
  states: ReadonlySignal<Readonly<Record<string, ControlState>>>;
  press(name: string): Promise<void>;
}

export interface HomeSource {
  /** Who is home: null when presence cannot say, undefined before it is read. */
  home: ReadonlySignal<readonly string[] | null | undefined>;
}

export interface AttentionSource {
  /** What needs the person: null when none of it could be read, undefined before it is. */
  attention: ReadonlySignal<HouseAttention | null | undefined>;
}

export interface PrinterSource {
  /** The household's printers: null when they cannot be read, undefined before they are. */
  printers: ReadonlySignal<readonly HousePrinter[] | null | undefined>;
  /** Keeps the printers read while a card shows them; returns the stop. */
  watch(): () => void;
}

export interface PersonSource {
  /** What she knows about the person and the household, as `rooms/memory` keeps it: null when it cannot be read,
   * undefined before it is. A fact corrected or forgotten in place changes this list. */
  facts: ReadonlySignal<readonly MemoryFact[] | null | undefined>;
  /** The person's voiceprints, null when they cannot be read, undefined before they are. */
  prints: ReadonlySignal<readonly Voiceprint[] | null | undefined>;
  /** Reads both again. */
  read(): Promise<void>;
}
