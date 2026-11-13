import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NONE, priced, provider, response } from './fixtures.ts';
import { layoutOf } from './flowLayout.ts';
import { beadCount, cableKind, cableWidth, flowGraph, flowsOf, heavier } from './flowModel.ts';
import { spanOf } from './certainty.ts';

const s = response([
  provider('anthropic', 'Anthropic', {
    brainstorm: { month: priced(10, 40), today: priced(1, 2) },
    chat: { month: priced(20, 1) },
  }),
  provider('gemini', 'Gemini', { chat: { month: priced(5, 0.5, { metered_calls: 4 }) } }),
  provider('wyoming', 'Wyoming', { transcribe: { month: { ...NONE, calls: 7, metered_calls: 7, unpriced_calls: 7 } } }),
  provider('quiet', 'Quiet', { chat: { month: NONE } }),
]);
const name = (t: string) => t.toUpperCase();

test('only what had calls is drawn, heaviest first, with unpriced after every cost', () => {
  const g = flowGraph(s, 'month', name);
  assert.deepEqual(g.providers.map((p) => p.id), ['anthropic', 'gemini', 'wyoming']);
  assert.deepEqual(g.tasks.map((t) => t.label), ['BRAINSTORM', 'CHAT', 'TRANSCRIBE']);
  assert.deepEqual(g.flows.map((f) => f.id), ['anthropic|brainstorm', 'anthropic|chat', 'gemini|chat', 'wyoming|transcribe']);
  assert.equal(g.peak, 40);
});

test('a task is the sum of the providers that answered it, and keeps its own certainty', () => {
  const g = flowGraph(s, 'month', name);
  const chat = g.tasks.find((t) => t.id === 'chat')!;
  assert.equal(chat.totals.calls, 25);
  assert.equal(chat.span.kind, 'partial');
});

test('a window with calls in none of them draws nothing', () => {
  const g = flowGraph(s, 'week', name);
  assert.deepEqual([g.tasks, g.providers, g.flows], [[], [], []]);
  assert.equal(g.peak, 0);
});

test('cables are solid, solid with a question mark, dashed or dotted by what is known', () => {
  assert.equal(cableKind(spanOf(priced(2, 1))), 'measured');
  assert.equal(cableKind(spanOf(priced(2, 1, { metered_calls: 1 }))), 'partial');
  assert.equal(cableKind(spanOf({ ...NONE, calls: 2, metered_calls: 2, unpriced_calls: 2 })), 'unpriced');
  assert.equal(cableKind(spanOf({ ...NONE, calls: 2 })), 'noUsage');
});

test('cable width follows cost by square root, and a cable with no cost is a thin fixed line', () => {
  const full = cableWidth({ kind: 'measured', usd: 40 }, 40);
  const quarter = cableWidth({ kind: 'measured', usd: 10 }, 40);
  assert.ok(full > quarter && quarter > 1.6);
  assert.equal(full, 11);
  assert.equal(cableWidth({ kind: 'measured', usd: 0 }, 40), 1.6);
  assert.equal(cableWidth({ kind: 'unpriced', unpriced: 3, noUsage: 0 }, 40), 2.4);
});

test('beads are calls by log, one at the least and nine at the most', () => {
  assert.equal(beadCount(1), 1);
  assert.equal(beadCount(7), 3);
  assert.equal(beadCount(100_000), 9);
});

test('a pick covers its own flows only', () => {
  const g = flowGraph(s, 'month', name);
  assert.deepEqual(flowsOf(g, { kind: 'task', id: 'chat' }).map((f) => f.id), ['anthropic|chat', 'gemini|chat']);
  assert.deepEqual(flowsOf(g, { kind: 'provider', id: 'wyoming' }).map((f) => f.id), ['wyoming|transcribe']);
  assert.deepEqual(flowsOf(g, { kind: 'flow', id: 'gemini|chat' }).map((f) => f.id), ['gemini|chat']);
  assert.deepEqual(flowsOf(g, null), []);
});

test('a cost sorts before an unknown one, and calls break a tie', () => {
  const cost = { span: spanOf(priced(1, 1)), totals: priced(1, 1) };
  const none = { span: spanOf({ ...NONE, calls: 9 }), totals: { ...NONE, calls: 9 } };
  assert.ok(heavier(cost, none) < 0);
  assert.ok(heavier(none, { ...none, totals: { ...NONE, calls: 2 } }) < 0);
});

test('the layout keeps every node and every cable end inside the picture, at a phone-ish and a wide width', () => {
  const g = flowGraph(s, 'month', name);
  for (const w of [520, 1000]) {
    const l = layoutOf(g, w);
    assert.ok(l.xTask < l.xProvider);
    for (const y of [...l.taskY.values(), ...l.providerY.values()]) assert.ok(y > 0 && y < l.height);
    for (const f of g.flows) {
      const nums = l.path(f.id).match(/-?\d+(\.\d+)?/g)!.map(Number);
      assert.equal(nums.length, 8);
      assert.ok(nums.every((n) => n >= 0 && n <= Math.max(w, l.height)));
    }
  }
});

test('two cables landing on one provider end a few pixels apart', () => {
  const g = flowGraph(s, 'month', name);
  const l = layoutOf(g, 1000);
  const end = (id: string) => Number(l.path(id).split(' ').at(-1));
  assert.notEqual(end('anthropic|brainstorm'), end('anthropic|chat'));
});
