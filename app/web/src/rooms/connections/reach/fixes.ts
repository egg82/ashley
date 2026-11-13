// The one action that fixes what a connection needs, and the same action from the opened row.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { connectOAuth } from '../oauth';
import { openForm } from '../picking';
import type { Fix } from './needs.ts';

/** Starts the fix: the service's consent screen, or the form to paste a new secret or log in to Bridge again. */
export function runFix(fix: Fix, c: HouseholdConnection, kind: ConnectionKindInfo): void {
  if (fix === 'oauth') void connectOAuth(kind, c.label, c.personal ? 'person' : 'household');
  else openForm(kind, c.base_url, false, c.id);
}

/** The words for replacing what a connection holds, by how its kind is connected. */
export function replaceWords(kind: ConnectionKindInfo): { label: string; fix: Fix } {
  if (kind.connect === 'bridge') return { label: 'Log in again', fix: 'login' };
  if (kind.connect === 'oauth') return { label: 'Reconnect', fix: 'oauth' };
  return { label: `Replace ${kind.secret_noun}`, fix: 'replace' };
}
