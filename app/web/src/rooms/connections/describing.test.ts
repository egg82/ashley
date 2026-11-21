import assert from 'node:assert/strict';
import test from 'node:test';
import type { ConnectionKindInfo } from '../../api/types.ts';
import { takesDescription } from './describing.ts';

const kind = (name: string, takes: boolean) => ({ name, takes_description: takes }) as ConnectionKindInfo;

test('only a kind that takes a description gets the field', () => {
  const offered = [kind('herdr', true), kind('sure', false)];
  assert.equal(takesDescription(offered, 'herdr'), true);
  assert.equal(takesDescription(offered, 'sure'), false);
  assert.equal(takesDescription(offered, 'unknown'), false);
  assert.equal(takesDescription([], 'herdr'), false);
});
