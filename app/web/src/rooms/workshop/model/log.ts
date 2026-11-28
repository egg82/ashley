// What a bench's command log says, as a screen needs it: what changed between two reads (so
// each change can be shown by piece id, with who made it), and which command "Undo" takes back. Pure.
import type { BenchDetail, LoggedCommand } from '../../../api/types';

export type Author = LoggedCommand['author'];
/** What a command did to a piece; a rename changes the bench, not a piece, and a cue or a record of choices shown
 * (`surfaced`, beside her reply) changes neither. */
export type Did = Exclude<LoggedCommand['type'], 'rename' | 'cue' | 'surfaced'>;

/** One accepted command between two reads: the piece it changed, who made it, and what it was. */
export interface Stamp {
  piece: number;
  by: Author;
  did: Did;
  seq: number;
}

function latestSeq(recent: readonly LoggedCommand[]): number {
  return recent.reduce((most, c) => Math.max(most, c.seq), 0);
}

/** The accepted commands `after` carries that `before` did not, oldest first. A first read (`before` null) has none. */
export function stampsOf(before: BenchDetail | null, after: BenchDetail): Stamp[] {
  if (!before || before.bench.id !== after.bench.id) return [];
  const since = latestSeq(before.recent);
  return after.recent
    .filter((c) => c.seq > since && c.outcome === 'accepted')
    .flatMap((c) => (c.piece_id === null || c.type === 'rename' || c.type === 'cue' || c.type === 'surfaced' ? [] : [{ piece: c.piece_id, by: c.author, did: c.type, seq: c.seq }]));
}

/** The command the next press of "Undo" takes back, as the server walked it (`undo_next`); `command` is null when it is
 *  older than the commands the read carries. There is no redo. */
export function undoTarget(bench: Pick<BenchDetail, 'recent' | 'undo_next'>): { seq: number; command: LoggedCommand | null } | null {
  if (bench.undo_next === null) return null;
  return { seq: bench.undo_next, command: bench.recent.find((c) => c.seq === bench.undo_next) ?? null };
}

export const DID: Record<LoggedCommand['type'], string> = { add: 'add', edit: 'edit', move: 'move', remove: 'remove', run: 'run', propose: 'proposal', install: 'install', archive: 'archive', restore: 'restore', undo: 'undo', rename: 'rename', cue: 'cue', point: 'point', surfaced: 'choices shown', link: 'link', unlink: 'unlink' };

/** What no Undo can take back, or that changes nothing on the bench: it is not listed in the stage log. */
const NOT_LISTED: ReadonlySet<LoggedCommand['type']> = new Set(['undo', 'run', 'propose', 'cue', 'point', 'surfaced']);

/** A run of the log's changes that go together: the changes of one of her turns (`turn` set), or one change alone. */
export interface Step {
  turn: number | null;
  rows: LoggedCommand[];
}

/** The accepted, undoable changes of `recent` as steps, newest first; neighbouring changes of the same turn of hers are one step. */
export function stepsOf(recent: readonly LoggedCommand[]): Step[] {
  const steps: Step[] = [];
  for (const c of recent) {
    if (c.outcome !== 'accepted' || NOT_LISTED.has(c.type)) continue;
    const last = steps[steps.length - 1];
    if (c.by_turn !== null && last?.turn === c.by_turn) last.rows.push(c);
    else steps.push({ turn: c.by_turn, rows: [c] });
  }
  return steps.reverse().map((s) => ({ ...s, rows: s.rows.reverse() }));
}

/** The step's "Undo this turn": only one of her turns has it, naming a command of the turn; `off` says why it can't be pressed. */
export function turnUndo(step: Step): { seq: number; off: string | null } | null {
  const first = step.rows[0];
  if (step.turn === null || !first || first.author !== 'ashley') return null;
  return { seq: first.seq, off: step.rows.every((c) => c.undone_by !== null) ? 'Already undone' : null };
}
