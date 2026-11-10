// A source piece with the pieces derived from it (`model/derived.ts`, today a recording and its transcript) as one card:
// the source's own body on top and the derived pieces in a panel below, which a person can fold. At phone width the
// card shows Player / panel tabs instead; the hidden half stays mounted, so a recording keeps playing under the other tab.
// The derived pieces stay pieces: archive and remove act on them from the panel, and the card's tools act on the source.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece, PieceKind } from '../../../api/types';
import { derivedLabel } from '../model/derived';
import { useNarrow } from './narrow';
import type { PieceActions } from './PieceCard';
import { PieceBody } from './renderers';

type Tab = 'source' | 'derived';

interface Props {
  bench: number;
  piece: BenchPiece;
  kind: PieceKind | undefined;
  kinds: ReadonlyMap<string, PieceKind>;
  derived: readonly BenchPiece[];
  closed: boolean;
  act: Pick<PieceActions, 'archive' | 'remove'>;
}

/** Opens the panel when a derived piece is newly pointed at, so her highlight is seen. */
function useOpenOnPoint(derived: readonly BenchPiece[], show: () => void): void {
  const seen = useRef<string | null>(null);
  const key = derived.map((d) => d.pointer?.seq ?? '').join(',');
  useEffect(() => {
    if (seen.current !== null && seen.current !== key && derived.some((d) => d.pointer)) show();
    seen.current = key;
  }, [key]);
}

function Bar({ narrow, open, tab, label, panel, setOpen, setTab }: {
  narrow: boolean; open: boolean; tab: Tab; label: string; panel: string;
  setOpen: (v: boolean) => void; setTab: (t: Tab) => void;
}) {
  if (!narrow) {
    return (
      <button class="pair-toggle" type="button" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}>
        <span class="pair-caret" aria-hidden="true">{open ? '▾' : '▸'}</span> {label}
      </button>
    );
  }
  const tabs: [Tab, string][] = [['source', 'Player'], ['derived', label]];
  return (
    <div class="pair-tabs seg" role="tablist" aria-label="Show">
      {tabs.map(([t, text]) => (
        <button key={t} type="button" role="tab" aria-selected={tab === t} aria-pressed={tab === t} onClick={() => setTab(t)}>{text}</button>
      ))}
    </div>
  );
}

export function PairedBody({ bench, piece, kind, kinds, derived, closed, act }: Props) {
  const narrow = useNarrow();
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState<Tab>('source');
  useOpenOnPoint(derived, () => { setOpen(true); setTab('derived'); });
  const label = derived.length === 1 && derived[0] ? derivedLabel(derived[0]) : 'Related';
  const panel = `pair-${bench}-${piece.id}`;
  return (
    <div class="pair" data-narrow={narrow ? 'true' : undefined}>
      <div class="pair-source" hidden={narrow && tab !== 'source'}>
        <PieceBody bench={bench} piece={piece} kind={kind} closed={closed} />
      </div>
      <Bar narrow={narrow} open={open} tab={tab} label={label} panel={panel} setOpen={setOpen} setTab={setTab} />
      <div class="pair-derived" id={panel} hidden={narrow ? tab !== 'derived' : !open}>
        {derived.map((d) => (
          <section key={d.id} class="pair-item" aria-label={d.title}>
            <PieceBody bench={bench} piece={d} kind={kinds.get(d.kind)} closed={closed} />
            {!closed && (
              <div class="pair-tools">
                <button class="btn sm ghost" type="button" onClick={() => act.archive(d)}>Archive {derivedLabel(d).toLowerCase()}</button>
                <button class="btn sm ghost" type="button" onClick={() => act.remove(d)}>Remove {derivedLabel(d).toLowerCase()}</button>
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
