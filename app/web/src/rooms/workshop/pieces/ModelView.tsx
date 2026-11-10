// A model piece (a code piece in `build123d`): what its latest run made, as a 3D picture, downloads, the checks the
// run reported and what printing it needs, with the source folded under them. A piece never run, or whose run kept no model, says so in the
// picture's place.
import type { BenchPiece, PieceKind, RunOutput } from '../../../api/types';
import { CodeBlock } from '../../../highlight/CodeBlock';
import { languageNamed } from '../../../highlight/languages';
import { ModelCanvas } from './ModelCanvas';
import { ModelChecks } from './ModelChecks';
import { ModelPrint } from './ModelPrint';
import { DOWNLOADS, GLB, artifactNamed, fileNameOf, outputOf } from './modelFacts';

function Downloads({ piece, out }: { piece: BenchPiece; out: RunOutput }) {
  const got = DOWNLOADS.flatMap((d) => {
    const a = artifactNamed(out, d.name);
    return a?.url ? [{ ...d, url: a.url }] : [];
  });
  if (!got.length) return null;
  return (
    <div class="mdl" role="group" aria-label="Downloads">
      {got.map((d) => <a key={d.name} class="btn sm" href={d.url} download={fileNameOf(piece.title, d.ext)}>{d.label}</a>)}
    </div>
  );
}

function Empty({ piece }: { piece: BenchPiece }) {
  const last = piece.last_run;
  const why = !last ? 'Not run yet. Run it to see the model.'
    : !last.run_output ? 'The last run left no result.'
    : last.run_output.run_outcome === 'ran' ? 'The last run made no model: it never called show().'
    : 'The last run did not finish, so there is no model.';
  return <p class="mview-none meta">{why}</p>;
}

export function ModelView({ piece, kind }: { piece: BenchPiece; kind: PieceKind }) {
  if (!piece.body.trim()) return <div class="pbody"><span class="meta">Empty. Edit to write in it.</span></div>;
  const out = outputOf(piece);
  const glb = out ? artifactNamed(out, GLB) : null;
  return (
    <div class="pbody pmodel">
      {glb?.url && piece.last_run
        ? <ModelCanvas url={glb.url} runId={piece.last_run.run_id} title={piece.title} />
        : <Empty piece={piece} />}
      {out && <Downloads piece={piece} out={out} />}
      {out && <ModelChecks report={out.report} />}
      {out?.report && <ModelPrint report={out.report} />}
      <details class="mview-src">
        <summary class="meta">Source</summary>
        <div class="code"><CodeBlock code={piece.body} language={languageNamed(kind.language)} /></div>
      </details>
    </div>
  );
}
