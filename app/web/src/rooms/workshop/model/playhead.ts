// Where each recording piece's player is, for a transcript beside it to follow. Held in this page only: a playhead is
// nobody's state to keep, and a screen that opens later asks the player.
import { useEffect, useState } from 'preact/hooks';

export interface Playhead {
  seconds: number;
  playing: boolean;
}

const heads = new Map<string, Playhead>();
const followers = new Map<string, Set<(head: Playhead | null) => void>>();

const keyOf = (bench: number, piece: number): string => `${bench}/${piece}`;

/** Records the player of `piece` as at `head`, or gone (null), and tells whoever follows it. */
export function setPlayhead(bench: number, piece: number, head: Playhead | null): void {
  const key = keyOf(bench, piece);
  if (head) heads.set(key, head);
  else heads.delete(key);
  followers.get(key)?.forEach((f) => f(head));
}

/** The playhead of `piece` on `bench` as it moves; null while there is none, and for no piece. */
export function usePlayhead(bench: number, piece: number | null): Playhead | null {
  const [head, setHead] = useState<Playhead | null>(null);
  useEffect(() => {
    if (piece === null) return;
    const key = keyOf(bench, piece);
    const set = followers.get(key) ?? new Set<(head: Playhead | null) => void>();
    followers.set(key, set);
    set.add(setHead);
    setHead(heads.get(key) ?? null);
    return () => {
      set.delete(setHead);
      setHead(null);
    };
  }, [bench, piece]);
  return head;
}
