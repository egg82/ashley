// What "this one" means when a message is sent on a bench: the piece under the cursor, otherwise the last one tapped.
// The canvas feeds the two signals; the talk takes it with each message (`talk.ts`), which clears the tap.
import { computed, signal } from '@preact/signals';

export const hovered = signal<number | null>(null);
export const tapped = signal<number | null>(null);
/** Whether the bench's composer holds something to send. */
export const typing = signal(false);

/** The piece that is marked while the person types: the one a message sent now would point at. */
export const marked = computed(() => (typing.value ? hovered.value ?? tapped.value : null));

/** The piece a message sent now points at, if it is one of `ids`; the tap is spent, as the message is sent. */
export function takePointing(ids: ReadonlySet<number>): number | null {
  const at = hovered.value ?? tapped.value;
  tapped.value = null;
  return at !== null && ids.has(at) ? at : null;
}

export function clearPointing(): void {
  hovered.value = null;
  tapped.value = null;
}
