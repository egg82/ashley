// What the person has typed into a composer and not sent, by thread (their web chat, each bench's talk), kept here
// rather than in the composer so leaving the room (following her included) never drops it. This tab only, in memory.
import { signal } from '@preact/signals';

const unsent = signal<ReadonlyMap<string, string>>(new Map());

/** `drafts` with `thread`'s unsent text set to `text`; an empty text leaves nothing kept for it. */
export function withUnsent(drafts: ReadonlyMap<string, string>, thread: string, text: string): ReadonlyMap<string, string> {
  const next = new Map(drafts);
  if (text) next.set(thread, text);
  else next.delete(thread);
  return next;
}

/** The text typed on `thread` and not sent, or ''. */
export function unsentOn(thread: string): string {
  return unsent.value.get(thread) ?? '';
}

/** The person typed `text` on `thread`. */
export function typedOn(thread: string, text: string): void {
  unsent.value = withUnsent(unsent.value, thread, text);
}

/** What was typed on `thread` was sent. */
export function sentOn(thread: string): void {
  typedOn(thread, '');
}
