import assert from 'node:assert/strict';
import { test } from 'node:test';
import { aside, badgeSize, placeAsides, SAYS, type AsideWant, type Placed } from './aside.ts';
import { drawnRect, lift, type Form } from './fold.ts';
import { GOAL, lay, makeBench } from './mindmap.gen.ts';
import type { Box } from './mindmap.ts';

const GOAL_BOX: Box = { x: -GOAL.w / 2, y: -GOAL.h / 2, ...GOAL };
const touches = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const within = (a: Box, b: Box) => a.x >= b.x - 1e-9 && a.y >= b.y - 1e-9 && a.x + a.w <= b.x + b.w + 1e-9 && a.y + a.h <= b.y + b.h + 1e-9;

/** What is wrong with a placement: a line or badge over another piece's box, the goal, or another line or badge. */
function faults(placed: Map<number, Placed>, boxes: Map<number, Box>, anchors: Map<number, Box>): string[] {
  const out: string[] = [];
  const all = [...placed];
  for (const [id, p] of all) {
    if (p.kind === 'inside') {
      if (!within(p.box, anchors.get(id)!)) out.push(`${id} inside spills out of its piece`);
      continue;
    }
    if (touches(p.box, GOAL_BOX)) out.push(`${id} over the goal`);
    for (const [other, b] of boxes) if (other !== id && touches(p.box, b)) out.push(`${id} over piece ${other}`);
    for (const [other, q] of all) if (other !== id && touches(p.box, q.box)) out.push(`${id} over ${other}'s ${q.kind}`);
  }
  return out;
}

function scene(seed: number, n: number, z: number, form: Form) {
  const boxes = lay(makeBench(seed, n));
  const anchors = new Map([...boxes].map(([id, b]) => [id, drawnRect(b, form, z)]));
  const wants: AsideWant[] = [...boxes.keys()].filter((id) => id % 3 === 0).map((id) => ({ id, anchor: anchors.get(id)!, says: id % 2 ? 'a line of hers' : null, badge: '2 lines' }));
  return { boxes, anchors, placed: placeAsides(wants, boxes, [GOAL_BOX], lift(z)) };
}

test('lines and badges never cover another piece, the goal or each other, on benches of 30 to 60, as cards and as chips', () => {
  for (const [z, form] of [[1, 'card'], [0.5, 'chip'], [0.8, 'chip']] as const) {
    for (const n of [30, 45, 60]) for (const seed of [1, 2, 3]) {
      const { boxes, anchors, placed } = scene(seed, n, z, form);
      assert.ok(placed.size > 5, 'the scene places something');
      assert.deepEqual(faults(placed, boxes, anchors), [], `${n}/${seed} at ${z}`);
    }
  }
});

test('the checker can fail: a badge forced onto another piece is reported', () => {
  const { boxes, anchors, placed } = scene(1, 30, 1, 'card');
  const [id] = [...placed.keys()];
  const other = [...boxes].find(([o]) => o !== id)![1];
  placed.set(id!, { kind: 'badge', box: { ...other, w: 10, h: 10 } });
  assert.ok(faults(placed, boxes, anchors).length > 0);
});

test('the sides are tried right, left, above, below', () => {
  const a: Box = { x: 0, y: 0, w: 100, h: 50 };
  const size = { w: 40, h: 20 };
  assert.ok(aside(a, size, 1, [])!.x >= 100, 'right first');
  const leftOnly = aside(a, size, 1, [{ x: 100, y: -100, w: 500, h: 500 }])!;
  assert.ok(leftOnly.x + leftOnly.w <= 0, 'then left');
  const above = aside(a, size, 1, [{ x: 100, y: -100, w: 500, h: 500 }, { x: -600, y: -100, w: 600, h: 500 }])!;
  assert.ok(above.y + above.h <= 0 && above.x >= 0, 'then above');
});

test('a line with no clear side folds to its badge, and a badge with none sits inside its own piece', () => {
  const a: Box = { x: 0, y: 0, w: 400, h: 200 };
  const walls: Box[] = [{ x: 401, y: -1000, w: 40, h: 3000 }, { x: -41, y: -1000, w: 40, h: 3000 }, { x: 0, y: -41, w: 400, h: 40 }, { x: 0, y: 232, w: 400, h: 40 }];
  const boxes = new Map([[1, a]]);
  const tight = placeAsides([{ id: 1, anchor: a, says: 'hello', badge: '1 line' }], boxes, walls, 1).get(1)!;
  assert.equal(tight.kind, 'badge', 'the badge fits below where the line does not');
  assert.ok(SAYS.h > 25 && badgeSize('1 line').h < 25);
  const shut = placeAsides([{ id: 1, anchor: a, says: 'hello', badge: '1 line' }], boxes, [...walls, { x: 0, y: 201, w: 400, h: 30 }], 1).get(1)!;
  assert.equal(shut.kind, 'inside');
  assert.ok(within(shut.box, a));
});
