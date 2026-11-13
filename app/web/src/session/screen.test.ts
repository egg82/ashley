import assert from 'node:assert/strict';
import { test } from 'node:test';
import { signal } from '@preact/signals';
import { createReporting, REPORT_MS, screenToken, type Page } from './screen.ts';

/** A page whose visibility, change events and heartbeat the test drives. */
function fakePage(): Page & { show(visible: boolean): void; beat(): void; listening(): number; beating(): number } {
  let visible = true;
  const heard = new Set<() => void>();
  const ticks = new Set<() => void>();
  return {
    visible: () => visible,
    onChange(h) {
      heard.add(h);
      return () => heard.delete(h);
    },
    every(tick, ms) {
      assert.equal(ms, REPORT_MS);
      ticks.add(tick);
      return () => ticks.delete(tick);
    },
    show(v) {
      visible = v;
      heard.forEach((h) => h());
    },
    beat: () => ticks.forEach((t) => t()),
    listening: () => heard.size,
    beating: () => ticks.size,
  };
}

function rig() {
  const sent: boolean[] = [];
  const up = signal(false);
  const page = fakePage();
  const reporting = createReporting(up, async (v) => void sent.push(v), page);
  return { sent, up, page, reporting };
}

test('the token is a version-4 UUID', () => {
  assert.match(screenToken, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test('nothing is reported while the feed is down, and the first report comes when it comes up', () => {
  const { sent, up, page, reporting } = rig();
  reporting.start();
  page.show(false);
  page.beat();
  assert.deepEqual(sent, []);
  up.value = true;
  assert.deepEqual(sent, [false]);
});

test('a change of visibility is reported at once, and the heartbeat repeats the current state', () => {
  const { sent, up, page, reporting } = rig();
  reporting.start();
  up.value = true;
  page.show(false);
  page.show(true);
  page.beat();
  assert.deepEqual(sent, [true, false, true, true]);
});

test('a feed that drops stops the reports and one that returns reports again', () => {
  const { sent, up, page, reporting } = rig();
  reporting.start();
  up.value = true;
  up.value = false;
  assert.equal(page.listening() + page.beating(), 0);
  page.show(false);
  assert.deepEqual(sent, [true]);
  up.value = true;
  assert.deepEqual(sent, [true, false]);
});

test('stopping releases the page and reports nothing more', () => {
  const { sent, up, page, reporting } = rig();
  reporting.start();
  reporting.start();
  up.value = true;
  assert.equal(page.listening(), 1);
  reporting.stop();
  assert.equal(page.listening() + page.beating(), 0);
  up.value = false;
  up.value = true;
  assert.deepEqual(sent, [true]);
});

test('a report that fails is dropped and the next goes out', async () => {
  const up = signal(true);
  const page = fakePage();
  let calls = 0;
  createReporting(up, async () => {
    calls += 1;
    throw new Error('503');
  }, page).start();
  page.beat();
  await Promise.resolve();
  assert.equal(calls, 2);
});
