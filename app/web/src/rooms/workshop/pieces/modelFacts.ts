// What a model piece's latest run gave, read for the page: the files it kept by name, the names downloads are saved
// under, and the numbers of a check as text. No three.js here.
import type { BenchPiece, PieceKind, ReportCheck, ReportPrint, ReportPrintPart, RunArtifact, RunOutput } from '../../../api/types';

/** The `language` of a kind whose pieces are models: its page is the picture of the run, not the source. */
export const MODEL_LANGUAGE = 'build123d';
// Artifacts are named by their path in the run's working directory; `ashley_cad.show` writes them under `out/`.
export const GLB = 'out/model.glb';
export const DOWNLOADS = [
  { name: 'out/model.stl', ext: 'stl', label: 'STL' },
  { name: 'out/model.3mf', ext: '3mf', label: '3MF' },
  { name: 'out/model.glb', ext: 'glb', label: 'GLB' },
] as const;

export function isModel(kind: PieceKind): boolean {
  return kind.format === 'code' && kind.language === MODEL_LANGUAGE;
}

/** The run the piece shows: its latest, when it left an output. */
export function outputOf(piece: BenchPiece): RunOutput | null {
  return piece.last_run?.run_output ?? null;
}

export function artifactNamed(out: RunOutput, name: string): RunArtifact | null {
  return out.artifacts.find((a) => a.name === name) ?? null;
}

/** The file name a download is saved under: the piece's title as a slug, then the extension. */
export function fileNameOf(title: string, ext: string): string {
  const slug = title.normalize('NFKD').replace(/\p{M}+/gu, '').replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').toLowerCase();
  return `${slug || 'model'}.${ext}`;
}

/** A number as written in a check: up to three decimals, none trailing. */
export function numText(n: number): string {
  return String(Number(n.toFixed(3)));
}

/** "actual ≥ target ± tolerance", with the unit the report is in. */
export function checkText(c: ReportCheck): string {
  const op = c.op === '<=' ? '≤' : c.op === '>=' ? '≥' : c.op;
  const tol = c.tolerance ? ` ± ${numText(c.tolerance)}` : '';
  return `${numText(c.actual)} ${op} ${numText(c.target)}${tol}`;
}

export function tally(checks: readonly ReportCheck[]): Record<ReportCheck['verdict'], number> {
  const got = { pass: 0, fail: 0, unconfirmed: 0 };
  for (const c of checks) got[c.verdict] += 1;
  return got;
}

/** Why the print check did not run, in plain words; null when it ran. `print` null is a run of a helper with no print check. */
export function printSkipText(print: ReportPrint | null, triangles: number): string | null {
  if (!print) return 'Printing was not checked on this run.';
  if (print.skip_reason === 'no_settings') return 'Printing was not checked: the run had no printer settings.';
  if (print.skip_reason === 'too_many_triangles') {
    const cap = print.max_triangles === null ? 'the check reads' : `the ${print.max_triangles} the check reads`;
    return `Printing was not checked: the model has ${triangles} triangles, more than ${cap}.`;
  }
  if (print.skip_reason === 'no_printed_parts') return 'Nothing here is printed: every part stands in for a real object.';
  return null;
}

/** One printed part's support and bed contact, in whole mm², and whether it fits the bed when that is known. */
export function printPartText(part: ReportPrintPart, print: ReportPrint): string {
  const support = part.support_area_mm2 > 0 ? `needs support under ${Math.round(part.support_area_mm2)} mm²` : 'needs no support';
  const bed = print.bed_fit_skipped === 'no_bed' || part.fits_bed === null ? 'bed size not set, so fit not checked'
    : part.fits_bed ? 'fits the bed' : 'too big for the bed';
  return `${support} · ${Math.round(part.bed_contact_mm2)} mm² on the bed · ${bed}`;
}
