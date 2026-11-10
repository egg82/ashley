// How long a message may be, as the server counts it (`api/models.py`: 1 to 4000 characters, counted as code points),
// and what a composer says about it. A composer never cuts text: past the limit it says so and holds Send.
import { locale } from '../../household/format.ts';

export const MAX_CHARS = 4000;

/** A paste longer than this becomes an attachment at paste time, not text in the box. */
export const PASTE_MIN = 1500;

/** The longest attachment a chat message takes, as the server counts it (`ChatAttachment`). */
export const ATTACH_MAX = 20000;

const NEAR = 3600;

/** The characters of `text` as the server counts them. */
export function charCount(text: string): number {
  let n = 0;
  for (const _ of text) n += 1;
  return n;
}

export type Limit = { over: boolean; note: string | null };

/** What to show under a message of `sent` (the trimmed text): nothing while it is short, a quiet count near the limit,
 * and past it the count with how much to cut. */
export function limitOf(sent: string): Limit {
  const n = charCount(sent);
  const count = `${n.toLocaleString(locale())} / ${MAX_CHARS.toLocaleString(locale())}`;
  if (n > MAX_CHARS) return { over: true, note: `${count}. Too long to send: cut ${(n - MAX_CHARS).toLocaleString(locale())}.` };
  return { over: false, note: n >= NEAR ? count : null };
}
