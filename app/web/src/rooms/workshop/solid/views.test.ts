import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { SIDES, VIEWS, distanceToFit, extentText, orthoHalfHeight, sideNamed, unit } from './views.ts';

test('the sheet is isometric, front, top, right, and no view looks along its own up', () => {
  assert.deepEqual(VIEWS.map((v) => v.id), ['iso', 'front', 'top', 'right']);
  for (const v of VIEWS) {
    const t = unit(v.toward);
    const dot = t[0] * v.up[0] + t[1] * v.up[1] + t[2] * v.up[2];
    assert.ok(Math.abs(dot) < 0.8, `${v.id} is not edge-on to its up`);
  }
});

test('the front looks from -Y at Z up and the top from +Z with Y up the screen', () => {
  const by = Object.fromEntries(VIEWS.map((v) => [v.id, v]));
  assert.deepEqual(by.front?.toward, [0, -1, 0]);
  assert.deepEqual(by.front?.up, [0, 0, 1]);
  assert.deepEqual(by.top?.toward, [0, 0, 1]);
  assert.deepEqual(by.top?.up, [0, 1, 0]);
});

test('a perspective camera sits far enough that the sphere spans the narrower field', () => {
  const wide = distanceToFit(10, 60, 2);
  const tall = distanceToFit(10, 60, 0.5);
  assert.ok(Math.abs(wide - 20) < 1e-9);
  assert.ok(tall > wide);
  assert.ok(Math.abs(Math.sin(Math.atan(Math.tan(Math.PI / 6) * 0.5)) * tall - 10) < 1e-9);
});

test('an orthographic frame is as tall as the sphere with a margin, and taller when the view is narrow', () => {
  assert.ok(Math.abs(orthoHalfHeight(10, 2) - 11.5) < 1e-9);
  assert.ok(Math.abs(orthoHalfHeight(10, 0.5) - 23) < 1e-9);
});

test('an extent is millimetres, whole from a hundred up and one decimal below', () => {
  assert.equal(extentText([120, 80, 40]), '120 × 80 × 40 mm');
  assert.equal(extentText([71, 62.04, 28.26]), '71 × 62 × 28.3 mm');
  assert.equal(extentText([100.4, 9.96, 0.04]), '100 × 10 × 0 mm');
});

test('a unit vector has length one', () => {
  assert.ok(Math.abs(Math.hypot(...unit([1, -1, 0.9])) - 1) < 1e-12);
});

test('the sides she may ask for are the ids the server accepts, in the server\'s order', () => {
  const served: unknown = JSON.parse(readFileSync(new URL('../../../../../ashley/looks/views.json', import.meta.url), 'utf8'));
  assert.deepEqual(SIDES.map((s) => s.id), served);
});

test('every side looks at the model from outside along its own axis, upright, and the sheet is among them', () => {
  const axes = new Set(SIDES.filter((s) => s.id !== 'iso').map((s) => s.toward.join()));
  assert.equal(axes.size, 6);
  for (const s of SIDES) {
    const t = unit(s.toward);
    assert.ok(Math.abs(t[0] * s.up[0] + t[1] * s.up[1] + t[2] * s.up[2]) < 0.8, `${s.id} is not edge-on to its up`);
  }
  for (const v of VIEWS) assert.equal(sideNamed(v.id), v);
});

test('the back looks from +Y, the left from -X and the bottom from -Z; an unknown name is no side', () => {
  assert.deepEqual(sideNamed('back')?.toward, [0, 1, 0]);
  assert.deepEqual(sideNamed('left')?.toward, [-1, 0, 0]);
  assert.deepEqual(sideNamed('bottom')?.toward, [0, 0, -1]);
  assert.equal(sideNamed('sideways'), null);
  assert.equal(sideNamed(null), null);
});
