// Made-up facts and voiceprints for the person card harness: a fixture household's, nobody's real ones. Dates are
// relative to the harness's clock, so what is "new this week" stays so.
import type { MemoryFact, Voiceprint } from '../../src/api/types';

const DAY = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();
const maya = { id: 1, household_id: 1, name: 'Maya', admin: true } as MemoryFact['owner'];
const source = (days: number, channel: 'voice' | 'discord' | 'web', place: string | null): MemoryFact['source'] => ({
  conversation_id: 31, conversation_kind: 'chat', started_at: ago(days), took_part: true, channel, place,
});

function fact(id: number, kind: MemoryFact['kind'], text: string, days: number, over: Partial<MemoryFact> = {}): MemoryFact {
  return {
    id, text, kind, standing: false, visibility: 'shared', about: maya, owner: maya, valid_from: ago(days), replaced: null,
    source: source(days, 'web', null), ...over,
  } as MemoryFact;
}

export const FACTS: MemoryFact[] = [
  fact(1, 'preference', 'Takes her coffee black, and only after eight in the morning.', 1.2, { source: source(1.2, 'voice', 'kitchen') }),
  fact(2, 'plan', 'Flying to Lisbon on the 14th, back on the 21st; the neighbour waters the balcony.', 3, { visibility: 'private' }),
  fact(3, 'routine', 'Runs on Tuesday and Thursday mornings before the school drop-off.', 2, { replaced: { text: 'Runs on Monday mornings.', valid_to: ago(2) } }),
  fact(4, 'diet', 'Does not eat shellfish; Theo is fine with it.', 40),
  fact(5, 'health', 'Takes a vitamin D tablet with breakfast.', 60, { visibility: 'private' }),
  fact(6, 'preference', 'Likes the living room at 21 degrees in the evening.', 90),
  fact(7, 'person', 'Her sister Priya lives in Leeds and calls on Sundays.', 120, { visibility: 'discreet' }),
  fact(8, 'home', 'The bins go out on Wednesday night.', 2, { about: null, owner: null }),
  fact(9, 'home', 'The spare key lives in the blue pot by the back door.', 200, { about: null, owner: null, visibility: 'members' }),
  fact(10, 'routine', 'Dinner is at half past six on weekdays.', 75, { about: null, owner: null }),
];

export const PRINTS: Voiceprint[] = [
  { device: 'Kitchen speaker', enrolled_at: ago(30) },
  { device: 'Hallway tablet with a long device name that wraps', enrolled_at: ago(4) },
];
