// A photo or a file put on the Pocket: a new bench opens, the files go to it, and the person's words go on that bench
// with the first kept piece named (`BenchMessage.piece_id`), so she knows what just arrived. Chat takes no bytes.
import { signal } from '@preact/signals';
import { openBench, sendOnBench } from '../../../api/client';
import { uploadAll } from '../../workshop/model/upload';
import { whyNot } from '../../workshop/pieces/why';
import { firstLine } from '../attached';
import { sentOn, typedOn, unsentOn } from '../unsent';
import { wordsFor } from './drops';

const TITLE_MAX = 60;

/** Where a drop got to: working, the bench it ended up on, or what went wrong. */
export const dropped = signal<{ working: boolean; bench: number | null; said: string | null }>({ working: false, bench: null, said: null });

const set = (working: boolean, bench: number | null, said: string | null) => { dropped.value = { working, bench, said }; };

/** Opens a bench for `files` and sends the words typed on `thread` there. Answers the bench when the files and words
 * both went; otherwise null, and `dropped` says what happened. */
export async function dropOnBench(thread: string, files: readonly File[]): Promise<number | null> {
  if (dropped.value.working || files.length === 0) return null;
  const typed = unsentOn(thread);
  set(true, null, null);
  let id: number;
  try {
    id = (await openBench({ title: firstLine(files[0]?.name ?? '', TITLE_MAX) || 'Dropped files' })).id;
  } catch {
    set(false, null, "Couldn't open a bench for that. Nothing was sent.");
    return null;
  }
  const outcomes = await uploadAll(id, files);
  const taken = outcomes.find((o) => o.ok && o.piece !== null);
  const refused = outcomes.find((o) => !o.ok);
  const why = refused && !refused.ok ? whyNot(refused.why) : null;
  if (!taken || !taken.ok) {
    set(false, id, why ?? 'None of it was kept.');
    return null;
  }
  sentOn(thread);
  try {
    await sendOnBench(id, { text: wordsFor(typed), piece_id: taken.piece });
  } catch {
    typedOn(thread, typed);
    set(false, id, "It's on a new bench, but she didn't get your words.");
    return null;
  }
  set(false, id, null);
  return id;
}
