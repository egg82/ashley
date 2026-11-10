import assert from 'node:assert/strict';
import { test } from 'node:test';
import { choiceOf, type Choice, type Stored, withChoice } from './lookups.ts';

const ALL: Choice[] = ['changes', 'finds_out', 'finds_out_trusted'];
const ID = 'script.where';

function starts(): Stored[] {
  const out: Stored[] = [];
  for (const reads of [[], [ID]]) for (const service of [[], [ID]]) out.push({ reads: [...reads, 'script.other'], service: [...service] });
  return out;
}

test('every choice, from every stored state, reads back as itself', () => {
  for (const start of starts()) for (const to of ALL) {
    assert.equal(choiceOf(ID, withChoice(ID, to, start, false), false), to, `${JSON.stringify(start)} -> ${to}`);
  }
});

test('a trusted answer is never stored without the look-up that makes it count', () => {
  for (const start of starts()) for (const to of ALL) {
    const got = withChoice(ID, to, start, false);
    assert.ok(!got.service.includes(ID) || got.reads.includes(ID), `${JSON.stringify(start)} -> ${to}`);
  }
});

test('the choice is stored as: nothing, the look-up, or the look-up and the trust', () => {
  const none: Stored = { reads: [], service: [] };
  assert.deepEqual(withChoice(ID, 'changes', { reads: [ID], service: [ID] }, false), none);
  assert.deepEqual(withChoice(ID, 'finds_out', none, false), { reads: [ID], service: [] });
  assert.deepEqual(withChoice(ID, 'finds_out_trusted', none, false), { reads: [ID], service: [ID] });
});

test('a choice leaves every other id where it was', () => {
  const start: Stored = { reads: ['script.a', ID], service: ['script.a', 'weather.get_forecasts'] };
  for (const to of ALL) {
    const got = withChoice(ID, to, start, false);
    assert.ok(got.reads.includes('script.a') && got.service.includes('script.a') && got.service.includes('weather.get_forecasts'));
  }
});

test('a stored trust with no look-up beside it does nothing, so it reads as makes changes', () => {
  assert.equal(choiceOf(ID, { reads: [], service: [ID] }, false), 'changes');
});

test('what Home Assistant says only finds things out is always a look-up and keeps only its trust', () => {
  const none: Stored = { reads: [], service: [] };
  assert.equal(choiceOf('weather.get_forecasts', none, true), 'finds_out');
  assert.equal(choiceOf('weather.get_forecasts', { reads: [], service: ['weather.get_forecasts'] }, true), 'finds_out_trusted');
  assert.deepEqual(withChoice('weather.get_forecasts', 'finds_out_trusted', none, true), { reads: [], service: ['weather.get_forecasts'] });
  assert.deepEqual(withChoice('weather.get_forecasts', 'finds_out', { reads: [], service: ['weather.get_forecasts'] }, true), none);
  assert.deepEqual(withChoice('weather.get_forecasts', 'changes', none, true), none, 'cannot be made to change things');
});
