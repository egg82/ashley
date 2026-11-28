// What a drop or a paste on the Pocket is, and what goes with files. Files open a bench (the one route bytes take in);
// a line of text or a link is a chat message, and a long one becomes the composer's attached chip.
import { isLongPaste } from '../attached.ts';

export type Drop = 'files' | 'chip' | 'line' | 'none';

/** The words that go with files when the person typed none. */
export const FILES_WORDS = 'I put this here.';

/** Common files the picker offers; the server's sniff decides what it keeps. */
export const ACCEPT = 'image/*,audio/*,video/*,application/pdf,.zip,.stl,.3mf,.glb';

/** What `text` and `files` arriving together are. Files win: a dragged file can carry its name as text. */
export function classifyDrop(text: string, files: number): Drop {
  if (files > 0) return 'files';
  if (text.trim() === '') return 'none';
  return isLongPaste(text) ? 'chip' : 'line';
}

/** The text a drop carries: plain text, else the link's address. */
export function textOf(data: Pick<DataTransfer, 'getData'>): string {
  const plain = data.getData('text/plain');
  if (plain) return plain;
  return data.getData('text/uri-list').split('\n').find((l) => l !== '' && !l.startsWith('#')) ?? '';
}

/** The words sent with files: what the person typed, or `FILES_WORDS`. */
export function wordsFor(typed: string): string {
  return typed.trim() || FILES_WORDS;
}
