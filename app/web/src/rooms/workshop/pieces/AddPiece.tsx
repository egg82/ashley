// Adding a piece: a card at the end of the grid with the kinds a person can add (the `stored` ones the rules list but
// a reader or a recipe, each a page Ashley read, and the framed `site` and `video`) and a title; a framed kind also takes its address (and a video where it starts). Once a
// stored piece is on the bench it opens in the editor for its text. A draft whose piece was taken off the
// bench while it was being written stays here too, until it is added back or let go.
import { useState } from 'preact/hooks';
import type { PieceSize, WorkshopKinds } from '../../../api/types';
import { apply, detail, type Outcome } from '../model/bench';
import { beginDraft, dropDraft, type Draft } from '../model/drafts';
import { framedBody, isFramed, parseStart } from '../model/frames';
import { whyNot } from './why';

const DEFAULT_SIZE: PieceSize = 'medium';

async function addPiece(bench: number, kind: string, title: string, body: string, size: PieceSize): Promise<Outcome> {
  const got = await apply({ type: 'add', kind, title, body, size });
  const piece = got.ok ? detail.value?.pieces.find((p) => p.id === got.piece) : undefined;
  if (piece && !body) beginDraft(bench, piece);
  return got;
}

export function AddPiece({ bench, rules, done }: { bench: number; rules: WorkshopKinds; done: () => void }) {
  const writable = rules.kinds.filter((k) => (k.family === 'stored' && k.format !== 'reader' && k.format !== 'recipe') || isFramed(k.format));
  const [kind, setKind] = useState(writable[0]?.name ?? '');
  const [title, setTitle] = useState('');
  const [url, setUrl] = useState('');
  const [startText, setStartText] = useState('');
  const format = writable.find((k) => k.name === kind)?.format;
  const framed = format !== undefined && isFramed(format);
  const start = parseStart(startText);
  const ready = !!title.trim() && !!kind && (!framed || (!!url.trim() && (format !== 'video' || start !== null)));
  const [failed, setFailed] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const size = rules.sizes.includes(DEFAULT_SIZE) ? DEFAULT_SIZE : rules.sizes[0]!;
  const submit = async (e: Event) => {
    e.preventDefault();
    if (busy || !ready || !format) return;
    setBusy(true);
    const body = framed ? framedBody(format, url, start ?? 0) : '';
    const got = await addPiece(bench, kind, title.trim(), body, size);
    setBusy(false);
    if (got.ok) done();
    else setFailed(got);
  };
  return (
    <form class="piece adding" data-size="medium" onSubmit={(e) => void submit(e)}>
      <header><span class="ptitle">Add a piece</span></header>
      <div class="padd">
        <div class="seg" role="group" aria-label="Kind">
          {writable.map((k) => (
            <button key={k.name} type="button" aria-pressed={kind === k.name} onClick={() => setKind(k.name)}>{k.label}</button>
          ))}
        </div>
        <input autoFocus class="pedit-title" value={title} maxLength={rules.title_max_chars} placeholder="Title" aria-label="Title"
          onInput={(e) => setTitle(e.currentTarget.value)} />
        {framed && (
          <input class="pedit-title" type="url" value={url} placeholder="https://" aria-label="Address" inputMode="url"
            onInput={(e) => setUrl(e.currentTarget.value)} />
        )}
        {format === 'video' && (
          <input class="pedit-title" value={startText} placeholder="Starts at (1:30, or seconds)" aria-label="Starts at"
            aria-invalid={start === null} onInput={(e) => setStartText(e.currentTarget.value)} />
        )}
        {failed && !failed.ok && <p class="pedit-err" role="alert">{whyNot(failed.why)}</p>}
        <div class="pedit-acts">
          <button class="btn sm primary" type="submit" disabled={busy || !ready}>Add</button>
          <button class="btn sm ghost" type="button" onClick={done}>Cancel</button>
        </div>
      </div>
    </form>
  );
}

/** A draft whose piece is no longer on the bench: what was typed, kept, to add back as a new piece or let go. */
export function Orphan({ bench, piece, draft }: { bench: number; piece: number; draft: Draft }) {
  const [failed, setFailed] = useState<Outcome | null>(null);
  const back = async () => {
    const got = await addPiece(bench, draft.kind, draft.title.trim() || 'Untitled', draft.body, draft.size);
    if (got.ok) dropDraft(bench, piece);
    else setFailed(got);
  };
  return (
    <div class="piece orphan" data-size="medium">
      <header><span class="ptitle">{draft.title}</span><span class="pill">taken off the bench</span></header>
      <div class="padd">
        <p class="pedit-says">This piece was taken off the bench while you were writing. What you wrote is here.</p>
        <pre class="orphan-text">{draft.body}</pre>
        {failed && !failed.ok && <p class="pedit-err" role="alert">{whyNot(failed.why)}</p>}
        <div class="pedit-acts">
          <button class="btn sm primary" type="button" onClick={() => void back()}>Add it back</button>
          <button class="btn sm ghost" type="button" onClick={() => dropDraft(bench, piece)}>Discard</button>
        </div>
      </div>
    </div>
  );
}
