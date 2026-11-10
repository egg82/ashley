import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionCatalogue } from '../../../api/types';
import { found, listLines, lookupLines, needLines, nameOf } from './house.ts';

const thing = (entity_id: string, name: string, device_class: string | null = null) =>
  ({ entity_id, name, domain: entity_id.split('.')[0] ?? '', device_class });
const house: ConnectionCatalogue = {
  entities: [thing('todo.shop', 'Shopping'), thing('todo.chores', 'Chores'), thing('script.where', 'Where is everyone'),
    thing('script.bed', 'Bedtime'), thing('lock.front', 'Front door'), thing('switch.rack', 'Server rack'), thing('light.den', 'Den')],
  actions: [{ name: 'script.where', domain: 'script', looks_up_only: false }, { name: 'script.bed', domain: 'script', looks_up_only: false },
    { name: 'weather.get_forecasts', domain: 'weather', looks_up_only: true }, { name: 'light.turn_on', domain: 'light', looks_up_only: false }],
  read_at: '2026-11-07T00:00:00Z',
};

test('every list the house has is a row, named, with the marked ones on, and a stored list the house lost stays marked', () => {
  const rows = listLines(house, ['todo.shop', 'todo.gone']);
  assert.deepEqual(rows.map((r) => [r.name, r.only, r.missing]), [['Chores', false, false], ['Gone', true, true], ['Shopping', true, false]]);
});

test('scripts and look-up actions are rows by their friendly names, the house-marked one fixed, other domains left out', () => {
  const rows = lookupLines(house, { reads: ['script.where'], service: ['weather.get_forecasts'] });
  assert.deepEqual(rows.map((r) => [r.name, r.choice, r.fixed]),
    [['Bedtime', 'changes', false], ['Get forecasts', 'finds_out_trusted', true], ['Where is everyone', 'finds_out', false]]);
});

test('without an answer from the house nothing is marked missing and names come from the ids', () => {
  const rows = lookupLines(null, { reads: ['script.drive_time'], service: [] });
  assert.deepEqual(rows.map((r) => [r.name, r.missing]), [['Drive time', false]]);
  assert.equal(nameOf(null, 'todo.weekly_shopping'), 'Weekly shopping');
});

test('a listed thing is marked when she handles it with care anyway, and a lost one is marked missing', () => {
  const rows = needLines(house, ['switch.rack', 'lock.front', 'switch.old']);
  assert.deepEqual(rows.map((r) => [r.name, r.already, r.missing]), [['Server rack', false, false], ['Front door', true, false], ['Old', false, true]]);
});

test('search finds what is not listed yet by name or id, says Already for a lock, and counts what it hides', () => {
  const got = found(house, 'DOOR', []);
  assert.deepEqual(got.shown.map((r) => [r.name, r.already]), [['Front door', true]]);
  assert.deepEqual(found(house, 'rack', ['switch.rack']).shown, []);
  assert.deepEqual(found(house, '  ', []), { shown: [], more: 0 });
  const many: ConnectionCatalogue = { ...house, entities: Array.from({ length: 12 }, (_, i) => thing(`light.l${i}`, `Lamp ${i}`)) };
  assert.deepEqual([found(many, 'lamp', []).shown.length, found(many, 'lamp', []).more], [8, 4]);
});
