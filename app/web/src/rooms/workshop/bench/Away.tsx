// Her latest change to a piece the person can't see (scrolled away, or Talk shown on a phone): a line at the foot of
// the floor says what she did to which piece, and takes them there.
import type { BenchDetail } from '../../../api/types';
import { reduced } from '../../../shell/motion';
import { away } from '../pieces/marks';
import { pieceEl } from '../pieces/PieceGrid';

const DID = { add: 'added', edit: 'changed', move: 'moved', remove: 'removed', run: 'ran', propose: 'proposed installing', install: 'installed', archive: 'archived', restore: 'restored', point: 'pointed at', undo: 'undid a change to' } as const;

export function Away({ bench, showPieces }: { bench: BenchDetail; showPieces: () => void }) {
  const there = away.value;
  const piece = there && bench.pieces.find((p) => p.id === there.piece);
  if (!there || !piece) return null;
  const go = () => {
    showPieces();
    requestAnimationFrame(() => pieceEl(document.querySelector('.ws .pgrid'), piece.id)
      ?.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth', block: 'center' }));
    away.value = null;
  };
  return (
    <button class="pill ws-away" type="button" onClick={go}>
      Ashley {DID[there.did]} “{piece.title}”
    </button>
  );
}
