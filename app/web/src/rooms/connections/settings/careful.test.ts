import assert from 'node:assert/strict';
import { test } from 'node:test';
import { handledAnyway } from './careful.ts';

test('locks, alarms, garage doors and outlets are handled with care without being listed', () => {
  for (const thing of [
    { domain: 'lock', device_class: null }, { domain: 'alarm_control_panel', device_class: null },
    { domain: 'cover', device_class: 'garage' }, { domain: 'switch', device_class: 'outlet' }, { domain: 'script', device_class: null },
  ]) assert.ok(handledAnyway(thing), JSON.stringify(thing));
});

test('lights, fans, plain switches and blinds are changed freely, so listing them matters', () => {
  for (const thing of [
    { domain: 'light', device_class: null }, { domain: 'fan', device_class: null }, { domain: 'switch', device_class: null },
    { domain: 'switch', device_class: 'switch' }, { domain: 'cover', device_class: 'blind' }, { domain: 'cover', device_class: null },
  ]) assert.ok(!handledAnyway(thing), JSON.stringify(thing));
});
