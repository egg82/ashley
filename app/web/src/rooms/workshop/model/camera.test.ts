import assert from 'node:assert/strict';
import { test } from 'node:test';
import { framing, lookAt, onScreen, openingZoom, panBy, toBench, worldTransform, Z_MAX, zoomAt, type Cam } from './camera.ts';

const V = { w: 1200, h: 700 };
const near = (a: number, b: number) => assert.ok(Math.abs(a - b) < 1e-6, `${a} vs ${b}`);

test('a bench opens at zoom 1 on a laptop and closer on a garage screen, never past 1.5', () => {
  assert.equal(openingZoom({ w: 1000, h: 640 }), 1);
  assert.ok(openingZoom({ w: 2500, h: 1300 }) > 1.4);
  assert.equal(openingZoom({ w: 8000, h: 5000 }), 1.5);
});

test('zooming about a point keeps the bench point under it', () => {
  const cam: Cam = { x: 100, y: -40, z: 1 };
  const s = { x: 900, y: 120 };
  const before = toBench(cam, V, s);
  const after = zoomAt(cam, 1.2, s, V, 0.5);
  const there = toBench(after, V, s);
  near(there.x, before.x);
  near(there.y, before.y);
  assert.equal(after.z, 1.2);
});

test('zoom is held between the floor given and Z_MAX', () => {
  const cam: Cam = { x: 0, y: 0, z: 1 };
  assert.equal(zoomAt(cam, 0.01, { x: 0, y: 0 }, V, 0.6).z, 0.6);
  assert.equal(zoomAt(cam, 100, { x: 0, y: 0 }, V, 0.6).z, Z_MAX);
});

test('a pan moves the bench with the pointer, at any zoom', () => {
  const cam: Cam = { x: 0, y: 0, z: 2 };
  const moved = panBy(cam, { x: 100, y: -50 });
  assert.deepEqual(moved, { x: -50, y: 25, z: 2 });
});

test('the world transform puts the camera point at the middle of the viewport', () => {
  assert.equal(worldTransform({ x: 10, y: 20, z: 2 }, V), 'translate(580px, 310px) scale(2)');
});

test('a framing fits everything with a margin, capped, and centres what is too big at the floor', () => {
  const boxes = [{ x: -500, y: -100, w: 200, h: 100 }, { x: 300, y: 50, w: 200, h: 100 }];
  const f = framing(boxes, V, 0.3, 1);
  assert.equal(f.x, 0);
  assert.equal(f.y, 25);
  assert.ok(f.z * 1000 <= V.w - 96 + 1e-9);
  assert.equal(framing(boxes, { w: 3000, h: 3000 }, 0.3, 1).z, 1, 'never closer than the cap');
  const huge = [{ x: 0, y: 0, w: 100000, h: 100 }];
  assert.deepEqual(framing(huge, V, 0.5, 1), { x: 50000, y: 50, z: 0.5 });
});

test('a focus change frames the neighbourhood when it fits, else the focus alone', () => {
  const focus = { x: 0, y: 0, w: 300, h: 200 };
  const near1 = { x: 400, y: 0, w: 300, h: 200 };
  assert.deepEqual(lookAt([focus, near1], focus, V, 1), { x: 350, y: 100, z: 1 });
  const far = { x: 3000, y: 0, w: 300, h: 200 };
  assert.deepEqual(lookAt([focus, far], focus, V, 1), { x: 150, y: 100, z: 1 });
});

test('a box is on screen when its header shows', () => {
  const cam: Cam = { x: 0, y: 0, z: 1 };
  assert.ok(onScreen(cam, V, { x: 0, y: 0, w: 100, h: 100 }));
  assert.ok(!onScreen(cam, V, { x: 2000, y: 0, w: 100, h: 100 }));
  assert.ok(!onScreen(cam, V, { x: 0, y: 340, w: 100, h: 100 }), 'its header is below the bottom edge');
});
