// A code piece's run strip, always shown: a Run button (one per language the bench can run, when there is any) and
// what the piece's latest run gave, whoever ran it: how it ended, what it printed and the files it left. A run of an
// older version says which; a run with no recorded result says that, never a blank.
import type { BenchPiece, PieceKind, PieceRun, RunOutput, WorkshopKinds } from '../../../api/types';
import { moment } from '../../memory/facts';
import { run, running } from '../model/bench';
import { MODEL_LANGUAGE, isModel } from './modelFacts';

const ENDED: Record<RunOutput['run_outcome'], string> = {
  ran: 'ran', timed_out: 'timed out', out_of_memory: 'out of memory', failed: 'failed', unknown: 'output lost',
};

function ended(out: RunOutput): { text: string; ok: boolean | null } {
  if (out.run_outcome === 'ran') return { text: `exit ${out.exit_code ?? '—'}`, ok: out.exit_code === 0 };
  return { text: ENDED[out.run_outcome], ok: out.run_outcome === 'unknown' ? null : false };
}

function Stream({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <div class="rstream">
      <span class="meta">{label}</span>
      <pre><code>{text}</code></pre>
    </div>
  );
}

function Files({ out }: { out: RunOutput }) {
  const names = Object.keys(out.files);
  if (!names.length && !out.files_left_out.length) return null;
  return (
    <details class="rfiles">
      <summary class="meta">{names.length} {names.length === 1 ? 'file' : 'files'} left{out.files_left_out.length ? ` · ${out.files_left_out.length} not kept` : ''}</summary>
      {names.map((n) => <Stream key={n} label={n} text={out.files[n] || ' '} />)}
      {out.files_left_out.length > 0 && <p class="meta">Not kept: {out.files_left_out.join(', ')}</p>}
    </details>
  );
}

function Last({ last, version }: { last: PieceRun; version: number }) {
  const out = last.run_output;
  const older = last.piece_version !== version ? <span class="meta"> · of version {last.piece_version}</span> : null;
  if (!out) {
    return <p class="rline"><span class="rstate">No result recorded</span><span class="meta"> · started {moment(last.started_at)}</span>{older}</p>;
  }
  const end = ended(out);
  return (
    <>
      <p class="rline">
        <span class={`rstate${end.ok === true ? ' ok' : end.ok === false ? ' bad' : ''}`}>{end.text}</span>
        <span class="meta"> · {moment(last.finished_at ?? last.started_at)}</span>{older}
        {out.output_cut && <span class="meta"> · output cut</span>}
      </p>
      <Stream label="out" text={out.stdout} />
      <Stream label="err" text={out.stderr} />
      {!out.stdout && !out.stderr && <p class="meta">Printed nothing.</p>}
      <Files out={out} />
    </>
  );
}

export function RunStrip({ piece, kind, rules, closed }: { piece: BenchPiece; kind: PieceKind | undefined; rules: WorkshopKinds | null; closed: boolean }) {
  const offered = rules?.run_languages ?? [];
  const languages = kind && isModel(kind) ? offered.filter((l) => l === MODEL_LANGUAGE) : offered;
  const busy = running.value.has(piece.id);
  const runnable = piece.body.trim() !== '' && piece.body.length <= (rules?.run_max_chars ?? 0);
  if (!piece.last_run && (closed || !languages.length)) return null;
  return (
    <section class="prun" aria-label={`Runs of ${piece.title}`} aria-busy={busy}>
      {!closed && languages.map((l) => (
        <button key={l} class="btn sm prun-go" type="button" disabled={busy || !runnable}
          title={runnable ? `Run as ${l}` : 'Nothing here that can be run'} onClick={() => void run(piece, l)}>
          {busy ? 'Running…' : languages.length > 1 ? `Run ${l}` : 'Run'}
        </button>
      ))}
      <div class="prun-last">
        {piece.last_run ? <Last last={piece.last_run} version={piece.piece_version} /> : <p class="meta">Not run yet.</p>}
      </div>
    </section>
  );
}
