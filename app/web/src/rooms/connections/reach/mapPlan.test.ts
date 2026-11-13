import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { NODE_R, planOf } from './mapPlan.ts';

const NOW = Date.parse('2026-11-13T08:00:00Z');
const DAY = 864e5;
const sam = { id: 1, household_id: 1, name: 'Sam', admin: true };
const conn = (id: number, kind: string, over: Partial<HouseholdConnection> = {}): HouseholdConnection => ({
  id, kind, label: '', base_url: '', added_by: sam, added_at: '', checked_at: new Date(NOW - 2 * DAY).toISOString(), personal: false, needs: null,
  scopes: [], missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true, ...over,
});
const kind = (name: string, holders: ('household' | 'person')[], most = 1): ConnectionKindInfo => ({
  name, title: name, what: '', blurb: '', connected: '', removed: '', holders, most, takes_address: false, address_placeholder: '',
  secret_field: 'token', secret_label: '', secret_noun: 'token', connect: 'pasted', set_up: true, has_settings: false,
});

test('a connection sits on its holder’s hub, and a kind not yet held is a ghost on the hub that may hold it', () => {
  const plan = planOf(
    [conn(1, 'sure'), conn(2, 'gitlab', { personal: true })],
    [kind('sure', ['household']), kind('gitlab', ['person']), kind('github', ['person']), kind('ha', ['household']), kind('google', ['household', 'person'])],
    NOW, 'Sam',
  );
  const by = (key: string) => plan.nodes.find((n) => n.key === key);
  assert.equal(by('c1')?.hub, 'household');
  assert.equal(by('c2')?.hub, 'person');
  assert.deepEqual(['kgithub', 'kha', 'kgoogle'].map((k) => [by(k)?.ghost, by(k)?.hub]), [[true, 'person'], [true, 'household'], [true, 'person']]);
  assert.equal(by('ksure'), undefined);
});

test('a kind that may be held more than once keeps a ghost beside what is held', () => {
  const plan = planOf([conn(1, 'proton', { personal: true })], [kind('proton', ['person'], 5)], NOW, 'Sam');
  assert.deepEqual(plan.nodes.map((n) => [n.key, n.ghost]), [['c1', false], ['kproton', true]]);
});

test('age, band and need are read from the connection', () => {
  const plan = planOf(
    [conn(1, 'a', { checked_at: new Date(NOW - 14 * 60_000).toISOString() }), conn(2, 'b', { needs: 'reconnect' }), conn(3, 'c')],
    [kind('a', ['household']), kind('b', ['household']), kind('c', ['household'])], NOW, 'Sam',
  );
  assert.deepEqual([plan.nodes[0]!.age, plan.nodes[0]!.band], ['14 min ago', 'today']);
  assert.equal(plan.nodes[1]!.needs, true);
  assert.deepEqual([plan.nodes[2]!.age, plan.nodes[2]!.band, plan.nodes[2]!.needs], ['2 d ago', 'week', false]);
});

test('no two nodes touch and every node and its label are inside the box, even with many', () => {
  for (const n of [3, 9, 14, 26]) {
    const kinds = Array.from({ length: n }, (_, i) => kind(`k${i}`, i % 2 ? ['person'] : ['household']));
    const plan = planOf(kinds.map((k, i) => conn(i + 1, k.name, { personal: i % 2 === 1 })), kinds, NOW, 'Sam');
    for (const a of plan.nodes) {
      assert.ok(a.x - NODE_R >= 0 && a.x + NODE_R <= plan.w, `x of ${a.key} at ${n}`);
      assert.ok(a.y - NODE_R >= 0 && a.y + NODE_R + 34 <= plan.h, `y of ${a.key} at ${n}`);
      for (const b of plan.nodes) if (a !== b) assert.ok(Math.hypot(a.x - b.x, a.y - b.y) > 2 * NODE_R + 6, `${a.key} and ${b.key} at ${n}`);
    }
  }
});

test('labels go beside the nodes stacked on the outer sides and under the rest, and stay inside the box', () => {
  const kinds = Array.from({ length: 12 }, (_, i) => kind(`k${i}`, i % 2 ? ['person'] : ['household']));
  const plan = planOf(kinds.map((k, i) => conn(i + 1, k.name, { personal: i % 2 === 1 })), kinds, NOW, 'Sam');
  const sides = new Set(plan.nodes.map((n) => n.side));
  assert.deepEqual([...sides].sort(), ['below', 'left', 'right']);
  for (const n of plan.nodes) {
    if (n.side === 'left') assert.ok(n.x - NODE_R - 120 >= 0, `${n.key} label runs off the left`);
    if (n.side === 'right') assert.ok(n.x + NODE_R + 120 <= plan.w, `${n.key} label runs off the right`);
  }
});

test('the household’s hub counts what it holds, and the person’s hub says whose chats', () => {
  const plan = planOf([conn(1, 'sure'), conn(2, 'x')], [kind('sure', ['household']), kind('x', ['household'])], NOW, 'Sam');
  assert.equal(plan.hubs[0]!.sub, '2 held together');
  assert.equal(plan.hubs[1]!.sub, 'chats that are Sam’s alone');
});
