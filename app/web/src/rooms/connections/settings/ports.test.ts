import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SettingInfo } from '../../../api/types';
import { entriesOf } from './draft.ts';
import { flipped, portLines, portsOf } from './ports.ts';

const declared: SettingInfo[] = [
  { key: 'reads', field: { type: 'action_list', domains: ['script'] }, decides: 'read' },
  { key: 'ports_off', field: { type: 'port_switches', ports: ['automations', 'house'] }, decides: 'ports' },
];

test('every declared port is a line, on until the draft lists it off', () => {
  assert.deepEqual(portLines(declared, {}).map((l) => [l.port, l.on]), [['automations', true], ['house', true]]);
  assert.deepEqual(portLines(declared, { ports_off: { '': ['house'] } }).map((l) => [l.port, l.on]), [['automations', true], ['house', false]]);
});

test('a kind with no switches has no ports', () => {
  assert.deepEqual(portsOf(declared.slice(0, 1)), []);
});

test('flipping a port off lists it and flipping it on again sends nothing', () => {
  const off = flipped({}, 'house');
  assert.deepEqual(entriesOf(off), [{ key: 'ports_off', ids: ['house'], per_action: [] }]);
  assert.deepEqual(entriesOf(flipped(off, 'house')), []);
});
