// What a person can still add: the kinds the server offers that their owner holds fewer of than the kind allows, and Discord's own link, which is
// the one personal connection that is an account and not a kind. Search is a filter over these, nothing more.
import type { ConnectionKindInfo, HouseholdConnection, LinkedAccount } from '../../api/types';

/** Who may hold a kind: only the signed-in person, only the household, or either. */
export type Whose = 'yours' | 'household' | 'either';

export function whose(kind: ConnectionKindInfo): Whose {
  const person = kind.holders.includes('person');
  const household = kind.holders.includes('household');
  return person && household ? 'either' : person ? 'yours' : 'household';
}

const WORDS: Record<Whose, string> = { yours: 'yours', household: 'household', either: 'yours household' };

export interface Choice {
  /** A kind's `name`, or `discord`. */
  id: string;
  title: string;
  what: string;
  blurb: string;
  whose: Whose;
  /** The kind to open the form of; null for Discord, whose link goes through Discord itself. */
  kind: ConnectionKindInfo | null;
}

export const DISCORD: Choice = {
  id: 'discord',
  title: 'Discord',
  what: 'your DMs',
  blurb: 'Talk to her from Discord as yourself. Only you see your DMs with her.',
  whose: 'yours',
  kind: null,
};

export function addable(
  kinds: readonly ConnectionKindInfo[],
  held: readonly HouseholdConnection[],
  accounts: readonly LinkedAccount[],
): Choice[] {
  const kindChoices = kinds
    .filter((k) => held.filter((c) => c.kind === k.name).length < k.most)
    .map((k): Choice => ({ id: k.name, title: k.title, what: k.what, blurb: k.blurb, whose: whose(k), kind: k }));
  return accounts.some((a) => a.system === 'discord') ? kindChoices : [DISCORD, ...kindChoices];
}

/** The choices whose title, what or description holds every word typed, ignoring case; all of them for no words. */
export function matching(choices: readonly Choice[], query: string): Choice[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return choices.filter((c) => {
    const text = `${c.title} ${c.what} ${c.blurb} ${WORDS[c.whose]}`.toLowerCase();
    return words.every((w) => text.includes(w));
  });
}
