import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { MemoryFact } from '../../api/types';
import { personView, printsOldestFirst } from './personView.ts';

const NOW = Date.parse('2026-11-27T12:00:00Z');
const daysAgo = (d: number) => new Date(NOW - d * 86_400_000).toISOString();

function fact(id: number, kind: MemoryFact['kind'], ago: number, household = false): MemoryFact {
  return {
    id, kind, text: `fact ${id}`, valid_from: daysAgo(ago), about: household ? null : { id: 1, name: 'Maya' },
    owner: household ? null : { id: 1, name: 'Maya' }, visibility: 'shared',
  } as unknown as MemoryFact;
}

const ids = (list: MemoryFact[]) => list.map((f) => f.id);

test('what is new this week leads, newest first, and is not listed again below', () => {
  const view = personView([fact(1, 'plan', 20), fact(2, 'routine', 6), fact(3, 'routine', 1), fact(4, 'plan', 8)], NOW);
  assert.deepEqual(ids(view.fresh), [3, 2]);
  assert.deepEqual(ids(view.yours).sort(), [1, 4]);
});

test('seven days is the edge: just inside is new, just outside is not', () => {
  const view = personView([fact(1, 'plan', 6.99), fact(2, 'plan', 7.01)], NOW);
  assert.deepEqual(ids(view.fresh), [1]);
  assert.deepEqual(ids(view.yours), [2]);
});

test('the rest of theirs is grouped by kind, the newest first within a kind', () => {
  const view = personView([fact(1, 'health', 30), fact(2, 'preference', 40), fact(3, 'preference', 20), fact(4, 'routine', 25)], NOW);
  assert.deepEqual(ids(view.yours), [3, 2, 4, 1]);
});

test("the household's facts are their own group, new ones first, and never in theirs", () => {
  const view = personView([fact(1, 'home', 30, true), fact(2, 'home', 2, true), fact(3, 'plan', 3)], NOW);
  assert.deepEqual(ids(view.household), [2, 1]);
  assert.deepEqual(ids(view.fresh), [3]);
  assert.deepEqual(view.yours, []);
});

test('voiceprints list oldest first without disturbing the read', () => {
  const read = [{ device: 'Kitchen', enrolled_at: daysAgo(1) }, { device: 'Den', enrolled_at: daysAgo(9) }];
  assert.deepEqual(printsOldestFirst(read).map((p) => p.device), ['Den', 'Kitchen']);
  assert.equal(read[0]?.device, 'Kitchen');
});
