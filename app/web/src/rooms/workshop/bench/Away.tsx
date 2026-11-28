// Her latest change to a piece the person can't see (off the canvas's view): a line above the talk says what she did to
// which piece, and takes them there.
import type { BenchDetail } from '../../../api/types';
import { focusAsk } from '../canvas/state';
import { away } from '../pieces/marks';

const DID = { add: 'added', edit: 'changed', move: 'moved', remove: 'removed', run: 'ran', propose: 'proposed installing', install: 'installed', archive: 'archived', restore: 'restored', point: 'pointed at', undo: 'undid a change to', link: 'linked', unlink: 'unlinked' } as const;

export function Away({ bench }: { bench: BenchDetail }) {
  const there = away.value;
  const piece = there && bench.pieces.find((p) => p.id === there.piece);
  if (!there || !piece) return null;
  const go = () => {
    focusAsk.value = piece.id;
    away.value = null;
  };
  return (
    <button class="pill ws-away" type="button" onClick={go}>
      Ashley {DID[there.did]} “{piece.title}”
    </button>
  );
}
