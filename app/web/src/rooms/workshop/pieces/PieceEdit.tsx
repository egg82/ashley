// A piece being edited in place: its title and body as the person's draft (`model/drafts.ts`), saved as one edit
// based on the version the draft began from. When the piece changed meanwhile, the newer text is shown beside the
// draft, which stays editable, until the person saves theirs over it or keeps the newer one. Nothing typed is dropped
// except by "Discard" or "Keep the newer one".
import { useEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece, PieceKind } from '../../../api/types';
import { apply, type Outcome } from '../model/bench';
import { dropDraft, inConflict, updateDraft, type Draft } from '../model/drafts';
import { PieceBody } from './renderers';
import { whyNot } from './why';

interface Props {
  bench: number;
  piece: BenchPiece;
  kind: PieceKind | undefined;
  draft: Draft;
  titleMax: number;
}

function Fields({ bench, piece, kind, draft, titleMax, save }: Props & { save: () => void }) {
  const body = useRef<HTMLTextAreaElement>(null);
  useEffect(() => body.current?.focus({ preventScroll: true }), []);
  return (
    <div class="pedit-fields" onKeyDown={(e) => (e.ctrlKey || e.metaKey) && e.key === 'Enter' && save()}>
      <input class="pedit-title" value={draft.title} maxLength={titleMax} aria-label="Title"
        onInput={(e) => updateDraft(bench, piece.id, { title: e.currentTarget.value })} />
      <textarea ref={body} class="pedit-body" value={draft.body} maxLength={kind?.max_chars} aria-label="Text"
        onInput={(e) => updateDraft(bench, piece.id, { body: e.currentTarget.value })} />
    </div>
  );
}

function Newer({ bench, piece, kind }: Pick<Props, 'bench' | 'piece' | 'kind'>) {
  const hers = piece.changed_author === 'ashley';
  return (
    <div class={`pedit-newer${hers ? ' hers' : ''}`}>
      <div class="label">{hers ? 'Ashley changed it to' : 'Changed elsewhere to'}</div>
      <b class="pedit-newer-title">{piece.title}</b>
      <PieceBody bench={bench} piece={piece} kind={kind} />
    </div>
  );
}

export function PieceEdit(props: Props) {
  const { bench, piece, draft } = props;
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<Outcome | null>(null);
  const conflict = inConflict(draft, piece);
  const save = async (over = false) => {
    if (saving || !draft.title.trim()) return;
    const base = over ? piece.piece_version : draft.base;
    if (over) updateDraft(bench, piece.id, { base });
    setSaving(true);
    setFailed(null);
    const got = await apply({ type: 'edit', piece_id: piece.id, base_version: base, title: draft.title.trim(), body: draft.body });
    setSaving(false);
    if (got.ok) dropDraft(bench, piece.id);
    else if (got.why !== 'stale_base') setFailed(got);
  };
  return (
    <div class={`pedit${conflict ? ' conflict' : ''}`}>
      {conflict && <p class="pedit-says" role="status">This changed while you were writing. Yours is kept beside it.</p>}
      <div class="pedit-sides">
        {conflict && <Newer {...props} />}
        <div class="pedit-mine">
          {conflict && <div class="label">Yours</div>}
          <Fields {...props} save={() => void save(conflict)} />
        </div>
      </div>
      {failed && !failed.ok && <p class="pedit-err" role="alert">{whyNot(failed.why)}</p>}
      <div class="pedit-acts">
        <button class="btn sm primary" type="button" disabled={saving || !draft.title.trim()} onClick={() => void save(conflict)}>
          {conflict ? 'Save mine over it' : 'Save'}
        </button>
        <button class="btn sm ghost" type="button" disabled={saving} onClick={() => dropDraft(bench, piece.id)}>
          {conflict ? 'Keep the newer one' : 'Discard'}
        </button>
      </div>
    </div>
  );
}
