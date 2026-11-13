// What a connection needs from a person, from its `needs` and `missing_scopes` fields, and the one action that fixes it.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import scopes from './scopes.json' with { type: 'json' };
import { ownerOf } from './sentence.ts';

/** `oauth`: through the service's own consent screen; `replace`: a new key or token pasted; `login`: log in to Bridge again. */
export type Fix = 'oauth' | 'replace' | 'login';

export interface Need {
  title: string;
  says: string;
  /** The button's words. */
  action: string;
  fix: Fix;
}

const NAMES: Record<string, string> = scopes;

/** What a scope lets her do, in words; the last part of its address for one not known. */
export function scopeLabel(scope: string): string {
  return NAMES[scope] ?? scope.split('/').pop() ?? scope;
}

function reconnectFix(kind: ConnectionKindInfo): Fix {
  return kind.connect === 'oauth' ? 'oauth' : 'replace';
}

/** Null when nothing is asked of a person. */
export function needOf(c: HouseholdConnection, kind: ConnectionKindInfo): Need | null {
  const name = c.label || kind.title;
  if (c.needs === 'login') {
    return { title: `Log in to ${name} again`, says: `Proton signed this account out. She can’t read it until you log in again.`, action: 'Log in', fix: 'login' };
  }
  if (c.needs === 'reconnect') {
    const fix = reconnectFix(kind);
    return {
      title: `Reconnect ${name}`,
      says: `${kind.title} turned the connection away. She can’t use ${ownerOf(c)} ${name} until you connect it again.`,
      action: fix === 'oauth' ? 'Reconnect' : `Paste a new ${kind.secret_noun}`,
      fix,
    };
  }
  if (c.missing_scopes.length > 0) {
    const missing = c.missing_scopes.map(scopeLabel).join(', ');
    return { title: `Allow more access in ${kind.title}`, says: `Not granted: ${missing}. She works without it until you allow it.`, action: `Allow in ${kind.title}`, fix: reconnectFix(kind) };
  }
  return null;
}
