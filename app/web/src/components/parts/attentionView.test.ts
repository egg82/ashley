import assert from 'node:assert/strict';
import { test } from 'node:test';
import { attentionView } from './attentionView.ts';

const texts = (lines: { text: string }[]) => lines.map((l) => l.text);

test('every part read as zero or false is clear, and only then', () => {
  const view = attentionView({ waiting_on_you: 0, printer_faults: 0, house_unreadable: false });
  assert.deepEqual(view, { needs: [], unknown: [], clear: true });
});

test('a part that cannot be read is unknown, never zero, and the rest is not called clear', () => {
  const view = attentionView({ waiting_on_you: null, printer_faults: 0, house_unreadable: false });
  assert.deepEqual(texts(view.unknown), ['Waiting on you']);
  assert.deepEqual(view.needs, []);
  assert.equal(view.clear, false);
});

test('nothing read at all, or not read yet, lists every part as unknown', () => {
  for (const read of [null, undefined]) {
    const view = attentionView(read);
    assert.deepEqual(view.unknown.map((l) => l.key), ['waiting', 'house', 'printer']);
    assert.equal(view.clear, false);
  }
});

test('what needs the person is counted in words, and unknowns stay beside it', () => {
  const view = attentionView({ waiting_on_you: 2, printer_faults: null, house_unreadable: true });
  assert.deepEqual(texts(view.needs), ['2 things waiting on you', "The house isn't answering"]);
  assert.deepEqual(texts(view.unknown), ['Printers']);
  assert.deepEqual(texts(attentionView({ waiting_on_you: 1, printer_faults: 1, house_unreadable: false }).needs),
    ['1 thing waiting on you', '1 printer reports a fault']);
});
