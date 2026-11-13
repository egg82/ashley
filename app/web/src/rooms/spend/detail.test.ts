import assert from 'node:assert/strict';
import { test } from 'node:test';
import { detailOf, linesOf } from './detail.ts';
import { NONE, priced, provider, response } from './fixtures.ts';
import { flowGraph } from './flowModel.ts';
import { spanOf } from './certainty.ts';

const s = response([
  provider('anthropic', 'Anthropic', { chat: { month: priced(10, 1.23456789012) } }),
  provider('eleven', 'ElevenLabs', { speak: { month: { ...NONE, calls: 3, metered_calls: 3, unpriced_calls: 3, characters: 867, audio_ms: 0 } } }),
]);
const g = flowGraph(s, 'month', (t) => t);

test('the exact lines hold what the report holds: unreported counts are absent, cost has its digits', () => {
  const t = priced(10, 1.23456789012);
  assert.deepEqual(linesOf(t, spanOf(t)), [
    ['Calls', '10'], ['Input tokens', '1,000'], ['Output tokens', '100'], ['Cost', '$1.23456789'],
  ]);
});

test('a cost that leaves calls out says so, and one that cannot be given is unknown', () => {
  const t = priced(10, 1, { metered_calls: 9 });
  const lines = linesOf(t, spanOf(t));
  assert.deepEqual(lines.find(([k]) => k === 'Not in the cost'), ['Not in the cost', '1 no usage']);
  assert.deepEqual(lines.at(-1), ['Cost', '$1 or more']);
  const e = s.providers[1]!.usage.month;
  assert.deepEqual(linesOf(e, spanOf(e)).at(-1), ['Cost', 'unknown']);
});

test('with nothing picked the detail is all calls; a pick narrows it to its own totals', () => {
  assert.equal(detailOf(s, g, 'month', null).sub, '13 calls this month');
  const flow = detailOf(s, g, 'month', { kind: 'flow', id: 'anthropic|chat' });
  assert.equal(flow.title, 'chat → Anthropic');
  assert.equal(flow.sub, '10 calls this month');
  assert.equal(detailOf(s, g, 'month', { kind: 'provider', id: 'eleven' }).span.kind, 'unpriced');
});
