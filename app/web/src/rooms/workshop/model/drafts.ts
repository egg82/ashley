// What the person is typing into pieces, by bench and piece, kept here rather than in a component so a read-back, a
// move or leaving the room never drops it. A draft names the version it was begun from; once the piece has moved past
// that version (her edit, another tab's), the draft is in conflict and both texts are shown until the person picks.
import { signal } from '@preact/signals';
import type { BenchPiece } from '../../../api/types';

export interface Draft {
  title: string;
  body: string;
  /** The piece's `piece_version` the draft was begun from or last reapplied onto. */
  base: number;
  /** The piece's kind and size, so a draft whose piece was removed can be added back as it was. */
  kind: string;
  size: BenchPiece['placement']['size'];
}

const drafts = signal<ReadonlyMap<string, Draft>>(new Map());

function key(bench: number, piece: number): string {
  return `${bench}:${piece}`;
}

function put(k: string, draft: Draft | null): void {
  const next = new Map(drafts.value);
  if (draft) next.set(k, draft);
  else next.delete(k);
  drafts.value = next;
}

/** The draft for a piece, if one is open. */
export function draftOf(bench: number, piece: number): Draft | null {
  return drafts.value.get(key(bench, piece)) ?? null;
}

/** The pieces of `bench` that have a draft open, with it. */
export function draftsOn(bench: number): [number, Draft][] {
  const prefix = `${bench}:`;
  return [...drafts.value].filter(([k]) => k.startsWith(prefix)).map(([k, d]) => [Number(k.slice(prefix.length)), d]);
}

/** Opens a draft from the piece as it stands, unless one is open already. */
export function beginDraft(bench: number, piece: BenchPiece): void {
  if (draftOf(bench, piece.id)) return;
  put(key(bench, piece.id), {
    title: piece.title, body: piece.body, base: piece.piece_version, kind: piece.kind, size: piece.placement.size,
  });
}

export function updateDraft(bench: number, piece: number, change: Partial<Draft>): void {
  const now = draftOf(bench, piece);
  if (now) put(key(bench, piece), { ...now, ...change });
}

/** Closes a draft: it was saved, or the person let it go. */
export function dropDraft(bench: number, piece: number): void {
  put(key(bench, piece), null);
}

/** Whether `piece` changed after the draft was begun, so saving it as it stands would be refused `stale_base`. */
export function inConflict(draft: Draft, piece: BenchPiece): boolean {
  return piece.piece_version !== draft.base;
}
