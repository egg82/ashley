import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ListedDevice } from '../../api/types';
import { firstSelected, placeCount, planOf } from './plan.ts';

const dev = (id: number, patch: Partial<ListedDevice> = {}): ListedDevice =>
  ({ id, name: `d${id}`, place: 'hallway', form: 'other', audience: 'present', medium: 'spoken', takes_controls: false, ...patch });

test('devices share a room when their places match, however it is written', () => {
  const plan = planOf([dev(1), dev(2, { place: ' Hallway ' }), dev(3, { place: 'office' })]);
  assert.deepEqual(plan.rooms.map((r) => [r.name, r.devices.map((d) => d.id)]), [['hallway', [1, 2]], ['office', [3]]]);
});

test('the house and a Discord server are drawn by what they are wired to, whatever their place or name', () => {
  const plan = planOf([dev(1, { form: 'house', place: 'kitchen' }), dev(2, { form: 'discord_server', place: 'hallway', name: 'house' }), dev(3)]);
  assert.deepEqual(plan.whole.map((d) => d.id), [1]);
  assert.deepEqual(plan.online.map((d) => d.id), [2]);
  assert.deepEqual(plan.rooms.map((r) => r.name), ['hallway']);
});

test('every device is drawn exactly once', () => {
  const all = [dev(1), dev(2, { form: 'house' }), dev(3, { form: 'discord_server' }), dev(4, { place: 'office' })];
  const plan = planOf(all);
  const drawn = [...plan.rooms.flatMap((r) => r.devices), ...plan.whole, ...plan.online].map((d) => d.id).sort();
  assert.deepEqual(drawn, [1, 2, 3, 4]);
});

test('places are counted where they have a device, and none for none', () => {
  assert.equal(placeCount(planOf([])), 0);
  assert.equal(placeCount(planOf([dev(1), dev(2, { form: 'house' }), dev(3, { form: 'discord_server' })])), 3);
});

test('the first device shown is one that takes controls, else the first', () => {
  assert.equal(firstSelected([dev(1), dev(2, { takes_controls: true })]), 2);
  assert.equal(firstSelected([dev(1), dev(2)]), 1);
  assert.equal(firstSelected([]), null);
});
