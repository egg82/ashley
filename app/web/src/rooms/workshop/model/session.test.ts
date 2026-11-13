import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SessionScreen } from '../../../api/sessions';
import { FAILED_MS, follow, sessionOf, type Follow, type Shown } from './session.ts';

const ID = '0a1b2c3d-0000-4000-8000-00000000abcd';

test('a session body names its session; anything else names none', () => {
  assert.equal(sessionOf(JSON.stringify({ source: 'herdr', session: ID })), ID);
  for (const body of ['', 'x', '[]', JSON.stringify({ session: ID }), JSON.stringify({ source: 'tmux', session: ID }),
    JSON.stringify({ source: 'herdr', session: ID.toUpperCase() }), JSON.stringify({ source: 'herdr', session: `../${ID}` })]) {
    assert.equal(sessionOf(body), null, body);
  }
});

const live = (text: string | null, digest: string, status: SessionScreen['status'] = 'working'): SessionScreen =>
  ({ state: 'live', status, digest, text, truncated: false, again_ms: 1500 });

/** A follow over scripted answers (an Error is a failed request): records each read's `seen` and each wait, and
 *  aborts once the answers run out. `hiddenFor` reads report the page hidden first. */
function scripted(answers: (SessionScreen | Error)[], hiddenFor = 0) {
  const stop = new AbortController();
  const seen: (string | null)[] = [];
  const waits: number[] = [];
  const shown: Shown[] = [];
  let hidden = hiddenFor;
  let shownWaits = 0;
  const deps: Follow = {
    read: async (session, s) => {
      assert.equal(session, ID);
      seen.push(s);
      const next = answers.shift()!;
      if (next instanceof Error) throw next;
      return next;
    },
    wait: async (ms) => {
      waits.push(ms);
      if (answers.length === 0) stop.abort();
    },
    visible: () => hidden === 0,
    shown: async () => { shownWaits += 1; hidden -= 1; },
  };
  const done = follow(ID, (s) => shown.push(s), deps, stop.signal);
  return { done, seen, waits, shown, shownWaits: () => shownWaits };
}

test('a screen is shown, kept while unchanged, and replaced when it changes', async () => {
  const run = scripted([live('one', 'a'), live(null, 'a', 'idle'), live('two', 'b')]);
  await run.done;
  assert.deepEqual(run.seen, [null, 'a', 'a']);
  assert.deepEqual(run.shown.map((s) => [s.state, s.status, s.text]), [['live', 'working', 'one'], ['live', 'idle', 'one'], ['live', 'working', 'two']]);
  assert.deepEqual(run.waits, [1500, 1500, 1500]);
});

test('a session that ends or a bridge that stops answering keeps the last screen, and asks for it whole again', async () => {
  const away: SessionScreen = { state: 'unreachable', status: null, digest: null, text: null, truncated: false, again_ms: 20000 };
  const run = scripted([live('one', 'a'), away, live('one', 'a'), { ...away, state: 'gone', again_ms: 6000 }]);
  await run.done;
  assert.deepEqual(run.seen, [null, 'a', null, 'a']);
  assert.deepEqual(run.shown.map((s) => [s.state, s.text]), [['live', 'one'], ['unreachable', 'one'], ['live', 'one'], ['gone', 'one']]);
  assert.deepEqual(run.waits, [1500, 20000, 1500, 6000]);
});

test('a request that fails in the page shows the bridge unreachable and waits the longest', async () => {
  const run = scripted([live('one', 'a'), new Error('offline'), live('one', 'a')]);
  await run.done;
  assert.deepEqual(run.shown.map((s) => [s.state, s.text]), [['live', 'one'], ['unreachable', 'one'], ['live', 'one']]);
  assert.deepEqual(run.waits, [1500, FAILED_MS, 1500]);
  assert.deepEqual(run.seen, [null, 'a', null]);
});

test('nothing is asked while the page is hidden', async () => {
  const run = scripted([live('one', 'a')], 2);
  await run.done;
  assert.equal(run.shownWaits(), 2);
  assert.deepEqual(run.seen, [null]);
});

test('an aborted follow asks nothing', async () => {
  const stop = new AbortController();
  stop.abort();
  let asked = 0;
  await follow(ID, () => {}, { read: async () => { asked += 1; return live('x', 'a'); }, wait: async () => {}, visible: () => true, shown: async () => {} }, stop.signal);
  assert.equal(asked, 0);
});
