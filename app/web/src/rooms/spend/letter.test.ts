import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SpendBalance } from '../../api/types.ts';
import { NONE, priced, provider, response } from './fixtures.ts';
import { letterOf, type Paragraph } from './letter.ts';

const text = (ps: Paragraph[]) => ps.map((p) => p.map((r) => r.text).join(''));
const quota = (remaining: number): SpendBalance => ({
  state: 'read', quota: { unit: 'characters', used: 1, limit: remaining + 1, remaining, resets_at: '2026-12-03T00:00:00Z' },
  read_at: '2026-11-13T11:59:00Z', why: null, docs_url: null,
});

const month = response([
  provider('anthropic', 'Anthropic', {
    brainstorm: { month: priced(600, 43.12, { metered_calls: 590 }) },
    chat: { month: priced(24, 0.5) },
  }),
  provider('gemini', 'Gemini', { chat: { month: priced(140, 2.22, { unpriced_calls: 3 }) } }),
  provider('openai', 'OpenAI', { command: { month: { ...NONE, calls: 2 } } }),
  provider('elevenlabs', 'ElevenLabs', { speak: { month: { ...NONE, calls: 8, metered_calls: 8, unpriced_calls: 8 } } }, { balance: quota(243_632) }),
]);

test('the letter states the total as a lower bound, what it leaves out, the biggest provider and task, and the one balance', () => {
  assert.deepEqual(text(letterOf(month, 'month')), [
    'Her calls this month cost the household at least $45.84, across 774 calls. 11 calls have no known price and 12 calls reported no usage, so they are not in that figure.',
    'Anthropic took 95% of it. Brainstorm alone was at least $43.12.',
    'ElevenLabs has 243,632 characters left until Dec 3. The other 3 paid providers don’t say what is left.',
  ]);
});

test('every figure in the letter is marked and comes from the payload', () => {
  const figs = letterOf(month, 'month').flat().filter((r) => r.fig).map((r) => r.text);
  assert.deepEqual(figs.slice(0, 3), ['$45.84', '774 calls', 'Anthropic']);
});

test('a window with no calls says so and never gives a zero cost', () => {
  const joined = text(letterOf(month, 'today'));
  assert.equal(joined[0], 'She made no calls today.');
  assert.ok(!joined.join(' ').includes('$0'));
  assert.equal(joined.length, 2, 'no share sentence without a cost');
});

test('calls that reported no usage, or have no price, give no cost to add up', () => {
  const none = response([provider('openai', 'OpenAI', { command: { month: { ...NONE, calls: 2 } } })]);
  assert.equal(text(letterOf(none, 'month'))[0], 'She made 2 calls this month, and none reported what it used, so there is no cost to give.');
  const unpriced = response([provider('eleven', 'ElevenLabs', { speak: { month: { ...NONE, calls: 3, metered_calls: 3, unpriced_calls: 3 } } })]);
  assert.equal(text(letterOf(unpriced, 'month'))[0], 'She made 3 calls this month, but none has a known price, so there is no cost to add up.');
});

test('a total with nothing left out is stated flat, and a single provider takes all of it', () => {
  const one = response([provider('anthropic', 'Anthropic', { chat: { month: priced(3, 1.5) } }, { kind: 'local' })]);
  assert.deepEqual(text(letterOf(one, 'month')), ['Her calls this month cost the household $1.50, across 3 calls.', 'Anthropic took all of it.']);
});

test('balances that could not be read are named, and providers that give none are counted', () => {
  const s = response([
    provider('a', 'Alpha', { chat: { month: priced(1, 1) } }, { balance: { state: 'failed', quota: null, read_at: null, why: null, docs_url: null } }),
    provider('b', 'Beta', { chat: { month: priced(1, 1) } }),
  ]);
  const last = text(letterOf(s, 'month')).at(-1);
  assert.equal(last, 'The paid provider doesn’t say what is left. Couldn’t read what Alpha has left.');
});
