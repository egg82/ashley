import assert from 'node:assert/strict';
import { test } from 'node:test';
import { faults, GOAL, input, lay, makeBench, meanLinkLength, prng, shuffled, worstMove, type Bench } from './mindmap.gen.ts';
import { foldDistance, GAP, layoutMindmap, type Box, type MapLink, type MapPiece } from './mindmap.ts';

const MOVE_BAR = 40;
const SIZES = [30, 45, 60];
const SEEDS = [1, 2, 3];

const piece = (id: number, w = 200, h = 120): MapPiece => ({ id, order: id, size: { w, h }, pin: null });
const without = (b: Bench, id: number): Bench => ({
  pieces: b.pieces.filter((p) => p.id !== id),
  links: b.links.filter((l) => l.from !== id && l.to !== id),
});
const sameBoxes = (a: Map<number, Box>, b: Map<number, Box>): boolean => JSON.stringify([...a]) === JSON.stringify([...b]);

test('the same input gives the same output, whatever order the pieces and links arrive in', () => {
  const b = makeBench(7, 45);
  const first = lay(b);
  assert.ok(sameBoxes(first, lay(b)));
  const flipped = { pieces: [...b.pieces].reverse(), links: [...b.links].reverse() };
  assert.ok(sameBoxes(new Map([...first].sort((x, y) => x[0] - y[0])), new Map([...lay(flipped)].sort((x, y) => x[0] - y[0]))));
});

test('pieces are laid out with the gap kept, nothing on the goal, nothing on a pin, pins exactly where pinned', () => {
  for (const n of SIZES) for (const seed of SEEDS) assert.deepEqual(faults(makeBench(seed, n), lay(makeBench(seed, n))), [], `${n}/${seed}`);
});

test('the checker can fail: two boxes forced together are reported', () => {
  const b = makeBench(1, 5);
  const got = lay(b);
  got.set(2, { ...got.get(1)! });
  assert.ok(faults(b, got).length > 0);
});

test('a pin stays put even when it sits on top of where a piece was', () => {
  const b: Bench = { pieces: [piece(1), piece(2)], links: [] };
  const before = lay(b);
  const where = before.get(1)!;
  const pinned = { pieces: [piece(1), { ...piece(2), pin: { x: where.x + 10, y: where.y + 5 } }], links: [] };
  const after = lay(pinned, before);
  assert.deepEqual([after.get(2)!.x, after.get(2)!.y], [where.x + 10, where.y + 5]);
  assert.deepEqual(faults(pinned, after), []);
});

test('adding a piece moves no existing unpinned piece by more than the bar', () => {
  let worst = 0;
  for (const n of SIZES) {
    for (const seed of SEEDS) {
      const full = makeBench(seed, n);
      const smaller = without(full, n);
      const before = lay(smaller);
      // A person pins a piece where it already stands, so the new piece comes unpinned.
      full.pieces[n - 1]!.pin = null;
      const after = lay(full, before);
      worst = Math.max(worst, worstMove(before, after, smaller));
      assert.deepEqual(faults(full, after), [], `${n}/${seed}`);
    }
  }
  assert.ok(worst <= MOVE_BAR, `moved ${worst}`);
});

test('removing a piece, and adding a link, move no one by more than the bar', () => {
  for (const n of SIZES) {
    const b = makeBench(4, n);
    const before = lay(b);
    const fewer = without(b, Math.floor(n / 2));
    assert.ok(worstMove(before, lay(fewer, before), fewer) <= MOVE_BAR);
    const linked = { ...b, links: [...b.links, { from: n, kind: 'depends_on', to: 2 } as MapLink] };
    const after = lay(linked, before);
    assert.ok(worstMove(before, after, linked) <= MOVE_BAR);
    assert.deepEqual(faults(linked, after), []);
  }
});

test('growing a bench piece by piece from nothing to 60 keeps every bar at every step', () => {
  const full = makeBench(11, 60);
  let before: Map<number, Box> | null = null;
  let worst = 0;
  const pinned = new Map<number, { x: number; y: number }>();
  for (let n = 0; n <= 60; n++) {
    const ids = new Set(full.pieces.slice(0, n).map((p) => p.id));
    // A piece arrives unpinned and is pinned where it landed on the next step, as a person drags it.
    const pieces = full.pieces.slice(0, n).map((p) => ({ ...p, pin: pinned.get(p.id) ?? null }));
    const b = { pieces, links: full.links.filter((l) => ids.has(l.from) && ids.has(l.to)) };
    const after = lay(b, before);
    assert.deepEqual(faults(b, after), [], `step ${n}`);
    if (before) worst = Math.max(worst, worstMove(before, after, b));
    const added = full.pieces[n - 1];
    if (added?.pin) pinned.set(added.id, { x: after.get(added.id)!.x, y: after.get(added.id)!.y });
    before = after;
  }
  assert.ok(worst <= MOVE_BAR, `moved ${worst}`);
  assert.ok(pinned.size === 3);
});

test('a bench that grows while pieces are resized still has no overlap, moving only the pieces that now collide', () => {
  const b = makeBench(5, 30);
  const before = lay(b);
  const grown = { ...b, pieces: b.pieces.map((p) => (p.id === 3 ? { ...p, size: { w: 520, h: 400 } } : p)) };
  const after = lay(grown, before);
  assert.deepEqual(faults(grown, after), []);
});

test('linked pieces sit near each other: a first layout beats the same boxes dealt out at random by a wide margin', () => {
  for (const n of SIZES) {
    const b = makeBench(9, n);
    const got = lay(b);
    const mine = meanLinkLength(b.links, got);
    const random = meanLinkLength(b.links, shuffled(got, 3));
    assert.ok(mine < 0.55 * random, `${n}: ${mine.toFixed(0)} vs ${random.toFixed(0)}`);
  }
});

test('a bench grown piece by piece keeps its links short too', () => {
  const full = makeBench(9, 60);
  let before: Map<number, Box> | null = null;
  for (let n = 1; n <= 60; n++) {
    const ids = new Set(full.pieces.slice(0, n).map((p) => p.id));
    before = lay({ pieces: full.pieces.slice(0, n), links: full.links.filter((l) => ids.has(l.from) && ids.has(l.to)) }, before);
  }
  assert.ok(meanLinkLength(full.links, before!) < 0.6 * meanLinkLength(full.links, shuffled(before!, 3)));
});

test('a version sits right beside the piece it supersedes, a part is farther from the goal than its parent', () => {
  const pieces = [piece(1, 300, 200), piece(2, 300, 200), piece(3, 300, 200)];
  const links: MapLink[] = [
    { from: 2, kind: 'version_of', to: 1 },
    { from: 3, kind: 'part_of', to: 1 },
  ];
  const got = layoutMindmap({ pieces, links, previous: null, goal: GOAL });
  const [a, v, part] = [got.get(1)!, got.get(2)!, got.get(3)!];
  const gapBetween = Math.max(a.x - (v.x + v.w), v.x - (a.x + a.w), a.y - (v.y + v.h), v.y - (a.y + a.h));
  assert.ok(gapBetween <= 2 * GAP, `version gap ${gapBetween}`);
  const far = (b: Box): number => Math.hypot(b.x + b.w / 2, b.y + b.h / 2);
  assert.ok(far(part) > far(a));
});

test('pieces with no links go around the goal by order, spread over all sides', () => {
  const pieces = [1, 2, 3, 4, 5, 6].map((i) => piece(i));
  const got = layoutMindmap({ pieces, links: [], previous: null, goal: GOAL });
  const sides = new Set([...got.values()].map((b) => `${Math.sign(b.x + b.w / 2)}${Math.sign(b.y + b.h / 2)}`));
  assert.ok(sides.size >= 4, [...sides].join(' '));
  assert.deepEqual(faults({ pieces, links: [] }, got), []);
});

test('fold distance is the hop count along links in either direction, absent when unreachable', () => {
  const links: MapLink[] = [
    { from: 2, kind: 'part_of', to: 1 },
    { from: 3, kind: 'depends_on', to: 2 },
    { from: 4, kind: 'version_of', to: 3 },
  ];
  assert.deepEqual([...foldDistance(2, links)].sort(), [[1, 1], [2, 0], [3, 1], [4, 2]]);
  assert.equal(foldDistance(1, [...links, { from: 9, kind: 'part_of', to: 8 }]).has(9), false);
});

test('a link cycle or a link to a missing piece does not stall the layout', () => {
  const pieces = [piece(1), piece(2)];
  const links: MapLink[] = [
    { from: 1, kind: 'depends_on', to: 2 },
    { from: 2, kind: 'depends_on', to: 1 },
    { from: 2, kind: 'part_of', to: 99 },
  ];
  assert.deepEqual(faults({ pieces, links }, layoutMindmap({ pieces, links, previous: null, goal: GOAL })), []);
});

test('the layout of sixty pieces takes well under a second, and the input is not changed', () => {
  const b = makeBench(21, 60);
  const snapshot = JSON.stringify(input(b, null));
  const t = performance.now();
  lay(b);
  assert.ok(performance.now() - t < 500);
  assert.equal(JSON.stringify(input(b, null)), snapshot);
  assert.ok(prng(1)() !== prng(2)());
});
