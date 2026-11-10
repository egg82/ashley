// One piece on the bench: a typed tile header (grip, glyph, title, who changed it last), its body through its kind's
// renderer or, while it is being edited, the editor, a code piece's runs (`PieceRun.tsx`), an automation's install
// (`PieceInstall.tsx`), and its tools (size, edit,
// archive to the bench's shelf, remove). A piece someone just changed
// says who for a moment, in their colour; her mark sits on it while she is shown changing it.
import type { BenchPiece, PieceKind, PieceSize, WorkshopKinds } from '../../../api/types';
import { moment } from '../../memory/facts';
import { beginDraft, draftOf } from '../model/drafts';
import { shortOf } from '../model/layout';
import { herAt, marks, type Mark } from './marks';
import { PieceEdit } from './PieceEdit';
import { InstallStrip } from './PieceInstall';
import { RunStrip } from './PieceRun';
import { PairedBody } from './PairedBody';
import { glyphOf, PieceBody } from './renderers';

export interface PieceActions {
  /** Moves the piece to index `to` of the order shown, keyboard or drop. */
  moveTo(id: number, to: number): void;
  resize(piece: BenchPiece, size: PieceSize): void;
  remove(piece: BenchPiece): void;
  archive(piece: BenchPiece): void;
  grab(e: PointerEvent, id: number): void;
}

interface Props {
  bench: number;
  piece: BenchPiece;
  kind: PieceKind | undefined;
  index: number;
  count: number;
  sizes: readonly PieceSize[];
  titleMax: number;
  closed: boolean;
  rules: WorkshopKinds | null;
  /** The pieces derived from this one (`model/derived.ts`), shown inside its card. */
  derived: readonly BenchPiece[];
  act: PieceActions;
}

const MARK: Record<Mark['did'], string> = { add: 'added this', edit: 'changed this', move: 'moved this', remove: 'removed this', run: 'ran this', propose: 'proposed installing this', install: 'installed this', archive: 'archived this', restore: 'restored this', point: 'pointed at this', undo: 'undid a change here' };

function Who({ piece, mark }: { piece: BenchPiece; mark: Mark | undefined }) {
  if (mark) return <span class={`pill who-tag ${mark.by === 'ashley' ? 'her' : 'you'}`}>{mark.by === 'ashley' ? 'Ashley' : 'You'}<span class="pwhen"> {MARK[mark.did]}</span></span>;
  const hers = piece.changed_author === 'ashley';
  return <span class={`meta pwho${hers ? ' her-meta' : ''}`}>{hers ? 'Ashley' : 'you'}<span class="pwhen"> · {moment(piece.changed_at)}</span></span>;
}

function Grip({ piece, index, count, act }: Pick<Props, 'piece' | 'index' | 'count' | 'act'>) {
  const keys: Record<string, number> = { ArrowUp: index - 1, ArrowLeft: index - 1, ArrowDown: index + 1, ArrowRight: index + 1, Home: 0, End: count - 1 };
  return (
    <button class="grip" type="button" aria-label={`Move ${piece.title}, ${index + 1} of ${count}`}
      aria-keyshortcuts="ArrowUp ArrowDown Home End"
      onPointerDown={(e) => act.grab(e, piece.id)}
      onKeyDown={(e) => {
        const to = keys[e.key];
        if (to === undefined || to < 0 || to >= count || to === index) return;
        e.preventDefault();
        act.moveTo(piece.id, to);
      }}>⋮⋮</button>
  );
}

function Tools({ piece, sizes, act, edit }: Pick<Props, 'piece' | 'sizes' | 'act'> & { edit: (() => void) | null }) {
  return (
    <footer class="ptools">
      <div class="seg sizes" role="group" aria-label="Size">
        {sizes.map((s) => (
          <button key={s} type="button" aria-pressed={piece.placement.size === s} aria-label={s} title={s}
            onClick={() => piece.placement.size !== s && act.resize(piece, s)}>{shortOf(s)}</button>
        ))}
      </div>
      {edit && <button class="btn sm ghost" type="button" onClick={edit}>Edit</button>}
      <button class="btn sm ghost" type="button" onClick={() => act.archive(piece)}>Archive</button>
      <button class="btn sm ghost" type="button" onClick={() => act.remove(piece)}>Remove</button>
    </footer>
  );
}

export function PieceCard(props: Props) {
  const { bench, piece, kind, closed } = props;
  const draft = draftOf(bench, piece.id);
  const ids = [piece.id, ...props.derived.map((d) => d.id)];
  const mark = ids.map((i) => marks.value.get(i)).find((m) => m);
  // A reader's text is the page as read, a file's content is its bytes and a job's card is written by the job runner: none is something to type over.
  const edit = !closed && kind?.format !== 'reader' && kind?.format !== 'job' && kind?.family !== 'large' ? () => beginDraft(bench, piece) : null;
  const cls = ['piece', draft && 'editing', mark && `mark-${mark.by === 'ashley' ? 'her' : 'you'}`].filter(Boolean).join(' ');
  return (
    <article class={cls} data-piece={piece.id} data-with={props.derived.map((d) => d.id).join(' ') || undefined} data-family={kind?.family ?? 'unknown'} data-size={piece.placement.size}
      aria-label={piece.title}>
      <header>
        {!closed && <Grip {...props} />}
        <span class="ptype">{glyphOf(kind)}</span>
        <span class="ptitle" onDblClick={edit ?? undefined}>{piece.title}</span>
        {ids.includes(herAt.value ?? -1) && <span class="piece-dock" data-dock />}
        <Who piece={piece} mark={mark} />
      </header>
      <div class="pmain">
        {draft
          ? <PieceEdit bench={bench} piece={piece} kind={kind} draft={draft} titleMax={props.titleMax} />
          : <div onDblClick={edit ?? undefined}>{props.derived.length
            ? <PairedBody bench={bench} piece={piece} kind={kind} kinds={new Map(props.rules?.kinds.map((k) => [k.name, k]) ?? [])} derived={props.derived} closed={closed} act={props.act} />
            : <PieceBody bench={bench} piece={piece} kind={kind} closed={closed} />}</div>}
      </div>
      {kind?.format === 'code' && !draft && <RunStrip piece={piece} kind={kind} rules={props.rules} closed={closed} />}
      {kind?.format === 'automation' && !draft && <InstallStrip piece={piece} closed={closed} />}
      {!closed && !draft && <Tools {...props} edit={edit} />}
    </article>
  );
}
