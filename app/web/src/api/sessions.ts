import type { paths } from './schema';
import { answer } from './client';

const ROUTE = '/api/claude/sessions/{session_id}/screen';
export type SessionScreen = paths[typeof ROUTE]['get']['responses'][200]['content']['application/json'];

/** A session and the machine (the label of the person's bridge) it is on; null for the person's default machine. */
export type SessionRef = { id: string; machine: string | null };

/** The end of Claude Code session `session`'s screen, from the person's own bridge; `seen` is the digest of the screen
 *  already shown, so an unchanged one comes back without its text. */
export async function sessionScreen(session: SessionRef, seen: string | null, signal: AbortSignal): Promise<SessionScreen> {
  const query = new URLSearchParams();
  if (seen !== null) query.set('seen', seen);
  if (session.machine !== null) query.set('machine', session.machine);
  const text = query.size === 0 ? '' : `?${query}`;
  return answer(await fetch(`/api/claude/sessions/${encodeURIComponent(session.id)}/screen${text}`, { signal }), 200, `GET ${ROUTE}`);
}
