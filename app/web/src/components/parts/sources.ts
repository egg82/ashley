// What a part reads and does, handed in by the shell that draws it: a shell backs these with its own signals and routes,
// so the same part serves the kiosk's cookie routes and a person's session alike.
import type { ReadonlySignal } from '@preact/signals';
import type { KioskControl } from '../../api/types';

export type ControlState = 'running' | 'done' | 'failed' | 'busy';

export interface ControlsSource {
  controls: ReadonlySignal<readonly KioskControl[]>;
  /** Each control's press state by name; a control not pressed lately has none. */
  states: ReadonlySignal<Readonly<Record<string, ControlState>>>;
  press(name: string): Promise<void>;
}

export interface HomeSource {
  /** Who is home: null when presence cannot say, undefined before it is read. */
  home: ReadonlySignal<readonly string[] | null | undefined>;
}
