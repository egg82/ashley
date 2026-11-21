// Whether a connection's kind lets its owner write a few words about what it reaches (a herdr bridge's machine).
import type { ConnectionKindInfo } from '../../api/types';

export const DESCRIPTION_MAX = 280;

export function takesDescription(kinds: readonly ConnectionKindInfo[], kind: string): boolean {
  return kinds.some((k) => k.name === kind && k.takes_description);
}
