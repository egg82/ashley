import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { CatalogueEntityInfo, DeviceControl } from '../../api/types';
import { actionFor, added, changed, complete, dirty, draftOf, MOST, moved, pickName, removed, reordered } from './controlRows.ts';

const stored: DeviceControl[] = [
  { name: 'a', label: 'A', action: 'light.turn_on', entity_id: 'light.a' },
  { name: 'b', label: 'B', action: 'light.turn_off', entity_id: 'light.b' },
];
const light = { entity_id: 'light.c', name: 'Light C', domain: 'light', device_class: null } as CatalogueEntityInfo;

test('a stored list is a draft that keeps each name', () => {
  assert.deepEqual(draftOf(stored).map((r) => r.name), ['a', 'b']);
});

test('a new row has no name and toggles the light picked', () => {
  const rows = added(draftOf(stored), light);
  assert.deepEqual(rows[2], { name: null, label: 'Light C', action: 'light.toggle', entity_id: 'light.c' });
});

test('nothing is added past the most, or when there is no light to pick', () => {
  const full = Array.from({ length: MOST }, () => draftOf(stored)[0]!);
  assert.equal(added(full, light).length, MOST);
  assert.equal(added(draftOf(stored), undefined).length, 2);
});

test('a move swaps neighbours and stays put at either end', () => {
  const rows = draftOf(stored);
  assert.deepEqual(moved(rows, 0, 1).map((r) => r.name), ['b', 'a']);
  assert.deepEqual(moved(rows, 0, -1), rows);
  assert.deepEqual(moved(rows, 1, 1), rows);
});

test('a change touches one row and a removal drops one', () => {
  const rows = changed(draftOf(stored), 1, { label: 'Z' });
  assert.deepEqual(rows.map((r) => r.label), ['A', 'Z']);
  assert.deepEqual(removed(rows, 0).map((r) => r.name), ['b']);
});

test('a list is complete when every label fits and every light is picked', () => {
  assert.equal(complete(draftOf(stored)), true);
  assert.equal(complete(changed(draftOf(stored), 0, { label: '  ' })), false);
  assert.equal(complete(changed(draftOf(stored), 0, { label: 'x'.repeat(41) })), false);
  assert.equal(complete(changed(draftOf(stored), 0, { entity_id: '' })), false);
});

test('a control added lands where it is dropped, and a scene is turned on', () => {
  const rows = added(draftOf(stored), light, 1);
  assert.deepEqual(rows.map((r) => r.entity_id), ['light.a', 'light.c', 'light.b']);
  assert.equal(added(draftOf(stored), { ...light, entity_id: 'scene.n', domain: 'scene' })[2]!.action, 'scene.turn_on');
});

test('a reorder puts the row where it is dropped, counted before it left', () => {
  const rows = draftOf([...stored, { name: 'c', label: 'C', action: 'light.toggle', entity_id: 'light.c' }]);
  const names = (r: typeof rows) => r.map((x) => x.name).join('');
  assert.equal(names(reordered(rows, 0, 3)), 'bca');
  assert.equal(names(reordered(rows, 2, 0)), 'cab');
  assert.equal(names(reordered(rows, 0, 1)), 'abc');
  assert.equal(names(reordered(rows, 1, 9)), 'abc');
});

test('a draft is dirty when what is shown, its order or what a control does differs from what is stored', () => {
  const rows = draftOf(stored);
  assert.equal(dirty(rows, stored), false);
  assert.equal(dirty(changed(rows, 0, { label: 'Z' }), stored), true);
  assert.equal(dirty(changed(rows, 1, { action: 'light.toggle' }), stored), true);
  assert.equal(dirty(moved(rows, 0, 1), stored), true);
  assert.equal(dirty(removed(rows, 1), stored), true);
  assert.equal(dirty(added(rows, light), stored), true);
});

test('a scene can only be turned on, and a light taking over from a scene toggles', () => {
  assert.equal(actionFor('scene.night', 'light.turn_off'), 'scene.turn_on');
  assert.equal(actionFor('light.hall', 'scene.turn_on'), 'light.toggle');
  assert.equal(actionFor('light.hall', 'light.turn_off'), 'light.turn_off');
  assert.equal(actionFor('light.hall', 'light.toggle'), 'light.toggle');
});

test('the picker tells a scene from a light', () => {
  assert.equal(pickName({ ...light, domain: 'scene', name: 'Night' }), 'Scene: Night');
  assert.equal(pickName(light), 'Light: Light C');
});
