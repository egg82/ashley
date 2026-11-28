import assert from 'node:assert/strict';
import { test } from 'node:test';
import { CARD_TEXT_PX, CHIP, CHIP_TEXT_PX, cardsReadable, drawnRect, formsOf, GHOST_H, lift, keptInView, keptWants, minZoom, shotWants, READ_FLOOR_PX, supersededBy, type FoldInput } from './fold.ts';
import { lookAt } from './camera.ts';
import type { MapLink } from './mindmap.ts';

// 1 - 2 - 3 - 4, and 5 on its own.
const LINKS: MapLink[] = [
  { from: 2, kind: 'part_of', to: 1 },
  { from: 3, kind: 'depends_on', to: 2 },
  { from: 4, kind: 'part_of', to: 3 },
];
const base: FoldInput = { ids: [1, 2, 3, 4, 5], focus: 2, links: LINKS, pinned: new Set(), superseded: new Set(), z: 1 };
const forms = (f: Partial<FoldInput>) => Object.fromEntries(formsOf({ ...base, ...f }));

test('cards are readable exactly while their smallest text stays at the 12 px floor', () => {
  const edge = READ_FLOOR_PX / CARD_TEXT_PX;
  assert.ok(cardsReadable(edge));
  assert.ok(!cardsReadable(edge - 0.01));
  assert.ok(cardsReadable(2));
});

test('the focus and pieces one link away draw in full; further, and unreachable, fold to chips', () => {
  assert.deepEqual(forms({}), { 1: 'card', 2: 'card', 3: 'card', 4: 'chip', 5: 'chip' });
  assert.deepEqual(forms({ focus: 4 }), { 1: 'chip', 2: 'chip', 3: 'card', 4: 'card', 5: 'chip' });
});

test('past the readable zoom everything is a chip, focus and pins included', () => {
  const z = READ_FLOOR_PX / CARD_TEXT_PX - 0.05;
  assert.deepEqual(forms({ z, pinned: new Set([4]) }), { 1: 'chip', 2: 'chip', 3: 'chip', 4: 'chip', 5: 'chip' });
});

test('a pinned piece draws in full however far from the focus; no focus draws all in full', () => {
  assert.equal(forms({ pinned: new Set([5]) })[5], 'card');
  assert.deepEqual(forms({ focus: null }), { 1: 'card', 2: 'card', 3: 'card', 4: 'card', 5: 'card' });
});

test('an old version is a ghost beside the new one, unless it is the focus', () => {
  const links: MapLink[] = [...LINKS, { from: 5, kind: 'version_of', to: 1 }];
  const old = supersededBy(links, new Set([1, 2, 3, 4, 5]));
  assert.deepEqual([...old], [1]);
  assert.equal(forms({ links, superseded: old })[1], 'ghost');
  assert.equal(forms({ links, superseded: old, focus: 1 })[1], 'card');
  assert.deepEqual([...supersededBy(links, new Set([2, 3, 4, 5]))], [], 'only when both ends are on the bench');
});

test('a chip keeps its title at the floor on screen at any zoom', () => {
  for (const z of [0.3, 0.5, 0.8, 1, 1.5]) {
    assert.ok(CHIP_TEXT_PX * lift(z) * z >= READ_FLOOR_PX - 1e-9, `zoom ${z}`);
  }
  assert.equal(lift(1.5), 1, 'never smaller than its own size');
});

test('a chip is centred inside its box, a ghost is its top, a card is the box', () => {
  const box = { x: 100, y: 200, w: 400, h: 300 };
  assert.deepEqual(drawnRect(box, 'card', 1), box);
  const chip = drawnRect(box, 'chip', 1);
  assert.deepEqual(chip, { x: 100 + (400 - CHIP.w) / 2, y: 200 + (300 - CHIP.h) / 2, w: CHIP.w, h: CHIP.h });
  assert.deepEqual(drawnRect(box, 'ghost', 1), { x: 100, y: 200, w: 400, h: GHOST_H });
  const far = drawnRect(box, 'chip', 0.4);
  assert.ok(far.x >= box.x && far.y >= box.y && far.x + far.w <= box.x + box.w + 1e-9 && far.y + far.h <= box.y + box.h + 1e-9);
});

test('the camera stops pulling back where the narrowest chip still holds a title', () => {
  const sizes = [{ w: 400, h: 300 }, { w: 240, h: 120 }];
  const z = minZoom(sizes);
  assert.equal(z, CHIP.minW / 240);
  for (const s of sizes) {
    const r = drawnRect({ x: 0, y: 0, ...s }, 'chip', z);
    assert.ok(r.w * z >= CHIP.minW - 1e-9, 'wide enough on screen');
    assert.ok(r.h * z >= CHIP.h - 1e-9, 'tall enough on screen');
  }
  assert.equal(minZoom([{ w: 100, h: 80 }]), 1, 'never past 1');
  assert.equal(minZoom([]), 0.2);
});

test('a touched version keeps its other end in full, not as a ghost or chip', () => {
  const links: MapLink[] = [...LINKS, { from: 5, kind: 'version_of', to: 1 }];
  const ids = new Set([1, 2, 3, 4, 5]);
  const old = supersededBy(links, ids);
  const at = (turn: number[]) => forms({ links, superseded: old, focus: 4, kept: keptInView(links, turn, ids) });
  assert.equal(at([])[1], 'ghost');
  assert.deepEqual([at([5])[1], at([5])[5]], ['card', 'card'], 'one end touched, both in full');
  assert.deepEqual([at([1])[1], at([1])[5]], ['card', 'card']);
});

test('pieces named together in a turn stay in full; one alone, or off the bench, adds nothing', () => {
  const ids = new Set([1, 2, 3, 4, 5]);
  assert.deepEqual([...keptInView(LINKS, [4, 5], ids)].sort(), [4, 5]);
  assert.deepEqual(forms({ kept: keptInView(LINKS, [4, 5], ids) })[5], 'card');
  assert.equal(keptInView(LINKS, [4], ids).size, 0);
  assert.equal(keptInView(LINKS, [4, 9], ids).size, 0);
});

test('the camera framing a turn\'s kept pieces contains every one of them', () => {
  const boxes = new Map([[1, { x: 0, y: 0, w: 300, h: 200 }], [3, { x: 2000, y: 100, w: 300, h: 200 }], [5, { x: 2400, y: 0, w: 300, h: 200 }], [9, { x: -900, y: 0, w: 300, h: 200 }]]);
  const links: MapLink[] = [{ from: 5, kind: 'version_of', to: 3 }];
  const V = { w: 1440, h: 900 };
  const wants = keptWants(new Set([3, 5]), links, boxes, (p) => p);
  const cam = lookAt(wants, boxes.get(9)!, V, 1);
  for (const p of [3, 5]) {
    const b = boxes.get(p)!;
    assert.ok(b.x >= cam.x - V.w / 2 && b.x + b.w <= cam.x + V.w / 2 && b.y >= cam.y - V.h / 2 && b.y + b.h <= cam.y + V.h / 2, `piece ${p} in view`);
  }
  assert.deepEqual(keptWants(new Set(), links, boxes, (p) => p), []);
  const wide = new Map(boxes).set(1, { x: -9000, y: 0, w: 300, h: 200 });
  assert.equal(keptWants(new Set([1, 3, 5]), links, wide, (p) => p)[1]!.length, 2, 'else the newest and its partner');
});

test('a person\'s focus change frames the focused piece even with kept pieces present; opening and a new turn frame the kept ones', () => {
  const boxes = new Map([[3, { x: 2000, y: 100, w: 300, h: 200 }], [5, { x: 2400, y: 0, w: 300, h: 200 }], [9, { x: -900, y: 0, w: 300, h: 200 }]]);
  const links: MapLink[] = [{ from: 5, kind: 'version_of', to: 3 }];
  const V = { w: 1440, h: 900 };
  const goal = { x: -1500, y: 0, w: 100, h: 100 };
  const focus = boxes.get(9)!;
  const args = { kept: new Set([3, 5]), links, boxes, rank: (p: number) => p, goal, focus, near: [focus] };
  const sees = (why: 'open' | 'turn' | 'person', b: { x: number; w: number }) => {
    const cam = lookAt(shotWants(why, args), focus, V, 1);
    return b.x >= cam.x - V.w / 2 && b.x + b.w <= cam.x + V.w / 2;
  };
  assert.ok(sees('person', focus) && !sees('person', boxes.get(5)!));
  assert.ok(sees('turn', boxes.get(5)!) && sees('open', boxes.get(3)!));
});
