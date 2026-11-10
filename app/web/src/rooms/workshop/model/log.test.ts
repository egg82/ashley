import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { BenchDetail, LoggedCommand } from '../../../api/types';
import { stampsOf, undoTarget } from './log.ts';

const cmd = (seq: number, type: LoggedCommand['type'], author: LoggedCommand['author'], piece: number | null,
             outcome: LoggedCommand['outcome'] = 'accepted'): LoggedCommand =>
  ({ seq, at: '2026-10-29T12:00:00Z', author, person_id: author === 'person' ? 1 : null, type, outcome, piece_id: piece });
const bench = (id: number, recent: LoggedCommand[]): BenchDetail => ({
  bench: { id, title: 'b', opened_at: '2026-10-29T12:00:00Z', closed_at: null, work: null, piece_count: 0, last_changed_at: null, thread: `bench:${id}` }, pieces: [], recent, undo_next: null, shelf: [],
});

test('a first read has no stamps', () => {
  assert.deepEqual(stampsOf(null, bench(1, [cmd(1, 'add', 'person', 1)])), []);
});

test('stamps are the accepted commands after the last one seen, oldest first, with who made them', () => {
  const before = bench(1, [cmd(1, 'add', 'person', 1)]);
  const after = bench(1, [cmd(1, 'add', 'person', 1), cmd(2, 'edit', 'ashley', 1), cmd(3, 'edit', 'person', 1, 'stale_base'), cmd(4, 'move', 'person', 1)]);
  assert.deepEqual(stampsOf(before, after), [
    { piece: 1, by: 'ashley', did: 'edit', seq: 2 }, { piece: 1, by: 'person', did: 'move', seq: 4 },
  ]);
});

test('a read of another bench stamps nothing', () => {
  assert.deepEqual(stampsOf(bench(1, []), bench(2, [cmd(1, 'add', 'person', 1)])), []);
});

test('after an empty log every accepted command is new', () => {
  assert.equal(stampsOf(bench(1, []), bench(1, [cmd(1, 'add', 'ashley', 1)])).length, 1);
});

test('undo names the command the server walked to, and has none when nothing is left', () => {
  const recent = [cmd(1, 'add', 'person', 1), cmd(2, 'edit', 'ashley', 1)];
  assert.equal(undoTarget({ recent, undo_next: null }), null);
  assert.deepEqual(undoTarget({ recent, undo_next: 2 }), { seq: 2, command: recent[1] ?? null });
  assert.deepEqual(undoTarget({ recent, undo_next: 1 }), { seq: 1, command: recent[0] ?? null });
  assert.deepEqual(undoTarget({ recent: recent.slice(1), undo_next: 1 }), { seq: 1, command: null });
});

test('a rename changes the bench, not a piece, so it stamps none', () => {
  const after = bench(1, [cmd(1, 'rename', 'ashley', null), cmd(2, 'edit', 'ashley', 1)]);
  assert.deepEqual(stampsOf(bench(1, []), after), [{ piece: 1, by: 'ashley', did: 'edit', seq: 2 }]);
});
