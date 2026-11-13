import type { paths } from './schema';
import { answer } from './client';

const ROUTE = '/api/claude/sessions/{session_id}/screen';
export type SessionScreen = paths[typeof ROUTE]['get']['responses'][200]['content']['application/json'];

/** The end of Claude Code session `session`'s screen, from the person's own bridge; `seen` is the digest of the screen
 *  already shown, so an unchanged one comes back without its text. */
export async function sessionScreen(session: string, seen: string | null, signal: AbortSignal): Promise<SessionScreen> {
  const query = seen === null ? '' : `?seen=${encodeURIComponent(seen)}`;
  return answer(await fetch(`/api/claude/sessions/${encodeURIComponent(session)}/screen${query}`, { signal }), 200, `GET ${ROUTE}`);
}
