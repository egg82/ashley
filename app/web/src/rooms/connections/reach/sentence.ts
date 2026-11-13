// The sentence a connection reads as: what she does with it, from its kind, who holds it and what it reaches. Kinds the
// table does not name read as "She reaches <it> for <holder>".
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';

export interface Sentence {
  before: string;
  /** The service, set apart in the line. */
  name: string;
  after: string;
  /** Where it is, under the sentence: the host of its address, or the one mailbox it reaches; null where neither says more. */
  address: string | null;
}

/** The household's, or the holder's own, as the possessive a sentence needs. */
export function ownerOf(c: HouseholdConnection): string {
  if (!c.personal) return 'the household’s';
  return c.added_by ? `${c.added_by.name}’s` : 'your';
}

/** Who holds it: the household, or the person's name (`one person` when it is no longer known). */
export function holderOf(c: HouseholdConnection): string {
  return c.personal ? (c.added_by?.name ?? 'one person') : 'the household';
}

export function hostOf(address: string): string {
  const bare = address.replace(/#.*$/, '');
  try {
    return new URL(bare).host;
  } catch {
    return bare.replace(/^bridge:\/\//, '');
  }
}

type Say = (c: HouseholdConnection, own: string) => [string, string];

const SAYS: Record<string, Say> = {
  home_assistant: () => ['She sees and runs the house through ', ''],
  sure: () => ['She reads the household’s accounts in ', ''],
  gitlab: (_, own) => [`She reads ${own} repositories on `, ''],
  github: (_, own) => [`She reads ${own} repositories on `, ''],
  herdr: (_, own) => [`She can see and drive ${own} `, ' sessions'],
  google: (_, own) => [`She works in ${own} `, ' account'],
  proton: (c) => [`She reads ${c.resources.length} `, c.resources.length === 1 ? ' mailbox through the bridge' : ' mailboxes through the bridge'],
  elevenlabs: () => ['She speaks through ', ' on the household’s key'],
  anthropic: () => ['She reaches ', ' on the household’s key'],
  openai: () => ['She reaches ', ' on the household’s key'],
  gemini: () => ['She reaches ', ' on the household’s key'],
};

function addressOf(c: HouseholdConnection, kind: ConnectionKindInfo): string | null {
  if (kind.takes_address) return hostOf(c.base_url);
  return c.resources.length === 1 ? (c.resources[0]?.name ?? null) : null;
}

export function sentenceOf(c: HouseholdConnection, kind: ConnectionKindInfo): Sentence {
  const own = ownerOf(c);
  const [before, after] = (SAYS[c.kind] ?? (() => ['She reaches ', ` for ${holderOf(c)}`]))(c, own);
  return { before, name: c.label || kind.title, after, address: addressOf(c, kind) };
}
