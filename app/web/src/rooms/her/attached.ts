// The paste a person has put in a composer and not sent, by thread, as the chip beside what they typed. A paste longer
// than `PASTE_MIN` is taken at paste time and never reaches the text box (`Composer.tsx`); a second one joins the first.
// This tab only, in memory, like `unsent.ts`.
import { signal } from '@preact/signals';
import { PASTE_MIN } from './limit.ts';

const attached = signal<ReadonlyMap<string, string>>(new Map());

/** Whether pasting `text` makes an attachment rather than text in the box. */
export function isLongPaste(text: string): boolean {
  return text.length > PASTE_MIN;
}

/** `drafts` with `text` added to `thread`'s paste (after a blank line when it holds one); an empty `text` clears it. */
export function withAttached(drafts: ReadonlyMap<string, string>, thread: string, text: string): ReadonlyMap<string, string> {
  const next = new Map(drafts);
  if (text) next.set(thread, text);
  else next.delete(thread);
  return next;
}

/** The paste held on `thread`, or null. */
export function attachedOn(thread: string): string | null {
  return attached.value.get(thread) ?? null;
}

/** `text` was pasted on `thread`: it joins what is held there. */
export function pastedOn(thread: string, text: string): void {
  const held = attached.value.get(thread);
  attached.value = withAttached(attached.value, thread, held ? `${held}\n\n${text}` : text);
}

/** The paste on `thread` was removed, or sent. */
export function unattachedOn(thread: string): void {
  attached.value = withAttached(attached.value, thread, '');
}

/** The first non-blank line of `text`, cut to `max` characters, as the title of what it became; '' when there is none. */
export function firstLine(text: string, max: number): string {
  const line = text.split('\n').find((l) => l.trim() !== '') ?? '';
  return [...line.trim()].slice(0, max).join('');
}
