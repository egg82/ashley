// Below the Desk's width: the board and the house folded into two toggles above the conversation, one open at a time.
import { useState } from 'preact/hooks';
import { Board, boardSummary } from '../board/Board';
import { House, houseSummary } from './House';

type Open = 'board' | 'house' | null;

function Summary({ text }: { text: string | null }) {
  return text === null ? <span class="unk">unknown</span> : <span class="meta">{text}</span>;
}

export function Folds({ open }: { open: number | null }) {
  const [shown, setShown] = useState<Open>(null);
  const toggle = (which: Exclude<Open, null>) => setShown(shown === which ? null : which);
  return (
    <div class="desk-folds">
      <div class="desk-toggles">
        <button type="button" class="desk-toggle" aria-expanded={shown === 'board'} aria-controls="desk-fold-board"
          onClick={() => toggle('board')}>
          <span>Board</span><Summary text={boardSummary()} />
        </button>
        <button type="button" class="desk-toggle" aria-expanded={shown === 'house'} aria-controls="desk-fold-house"
          onClick={() => toggle('house')}>
          <span>House</span><Summary text={houseSummary()} />
        </button>
      </div>
      {shown === 'board' && <div id="desk-fold-board" class="desk-fold"><Board open={open} /></div>}
      {shown === 'house' && <div id="desk-fold-house" class="desk-fold"><House /></div>}
    </div>
  );
}
