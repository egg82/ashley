// Removing a connection: what the confirmation says, and whether what was typed confirms it.
import type { ConnectionKindInfo } from '../../../api/types';

/** Whether `typed` is the connection's `name`, ignoring case and the space round it. */
export function confirmsRemoval(typed: string, name: string): boolean {
  return typed.trim().toLowerCase() === name.trim().toLowerCase();
}

/** What a person has to do to bring it back. */
export function bringBack(kind: ConnectionKindInfo): string {
  if (kind.connect === 'oauth') return 'sign in again';
  return `paste a new ${kind.secret_noun || 'login'}`;
}

/** The kind's own sentence for what removing costs, without its leading "Removed.". */
export function costOf(kind: ConnectionKindInfo): string {
  return kind.removed.replace(/^Removed\.\s*/, '');
}
