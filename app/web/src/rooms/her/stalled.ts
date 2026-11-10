// A turn that went quiet after her held line: the conversation ends on a held "let me check" (`follows`), the server
// has no work in flight for the line owed an answer, and she is not thinking. The server could not say it failed (its
// database was out of reach), so after `STALL_MS` of that the page says so itself, quietly.
import { owedAt, stillOn } from './owed.ts';
import type { Line } from './overlay.ts';

/** How long a conversation may sit on her held line, with her neither thinking nor working, before it shows unfinished. */
export const STALL_MS = 20_000;

/** Whether `lines` end on her held line with no work in flight for the line it follows. */
export function endsOnHeldLine(lines: readonly Line[]): boolean {
  const last = lines.at(-1);
  return last?.author === 'ashley' && last.follows === true && owedAt(lines) >= 0 && !stillOn(lines);
}

/** The line owed an answer, marked stalled; null when none is owed. */
export function stalledLine(lines: readonly Line[]): Line | null {
  const owed = lines[owedAt(lines)];
  return owed ? { ...owed, missed: 'stalled' } : null;
}
