import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ReportCheck, ReportPrint, ReportPrintPart, RunOutput } from '../../../api/types.ts';
import { DOWNLOADS, GLB, artifactNamed, checkText, fileNameOf, numText, printPartText, printSkipText, tally } from './modelFacts.ts';

const check = (verdict: ReportCheck['verdict']): ReportCheck =>
  ({ name: 'c', actual: 1, op: '>=', target: 2, tolerance: 0, rests_on: [], verdict });

test('a download is named from the piece title, in a slug, with the file kind as its extension', () => {
  assert.equal(fileNameOf('Pi case, v2', 'stl'), 'pi-case-v2.stl');
  assert.equal(fileNameOf('  Crème brûlée  ', '3mf'), 'creme-brulee.3mf');
  assert.equal(fileNameOf('///', 'glb'), 'model.glb');
});

test('a number is written with at most three decimals and none trailing', () => {
  assert.equal(numText(2), '2');
  assert.equal(numText(1.23456), '1.235');
  assert.equal(numText(0.5), '0.5');
});

test('a check reads actual, operator, target and the tolerance only when there is one', () => {
  assert.equal(checkText({ ...check('pass'), actual: 5, op: '==', target: 8, tolerance: 0.5 }), '5 == 8 ± 0.5');
  assert.equal(checkText({ ...check('pass'), actual: 2, op: '>=', target: 1.6 }), '2 ≥ 1.6');
  assert.equal(checkText({ ...check('pass'), actual: 71, op: '<=', target: 180 }), '71 ≤ 180');
  assert.equal(checkText({ ...check('pass'), actual: 1, op: '<', target: 2 }), '1 < 2');
});

test('the tally counts each verdict', () => {
  assert.deepEqual(tally([check('pass'), check('fail'), check('fail'), check('unconfirmed')]), { pass: 1, fail: 2, unconfirmed: 1 });
  assert.deepEqual(tally([]), { pass: 0, fail: 0, unconfirmed: 0 });
});

test('a kept file is found by its name, and a name the run did not keep is none', () => {
  const out = { artifacts: [{ name: 'model.glb', size_bytes: 1, media_type: 'model/gltf-binary', url: 'u', expires_at: 1 }] } as unknown as RunOutput;
  assert.equal(artifactNamed(out, 'model.glb')?.url, 'u');
  assert.equal(artifactNamed(out, 'model.stl'), null);
});

// The names and types a real build123d run on a bench kept (captured from a live run's `run_output.artifacts`).
const LIVE = [
  { name: 'out/model.3mf', size_bytes: 1697, media_type: 'model/3mf' },
  { name: 'out/model.glb', size_bytes: 4180, media_type: 'model/gltf-binary' },
  { name: 'out/model.stl', size_bytes: 684, media_type: 'model/stl' },
];

test('the model and every download are found among the files a real run keeps', () => {
  const out = { artifacts: LIVE.map((a) => ({ ...a, url: `u:${a.name}`, expires_at: 1 })) } as unknown as RunOutput;
  assert.equal(artifactNamed(out, GLB)?.media_type, 'model/gltf-binary');
  for (const d of DOWNLOADS) assert.equal(artifactNamed(out, d.name)?.url, `u:${d.name}`);
});

const printed = (over: Partial<ReportPrint> = {}): ReportPrint =>
  ({ skip_reason: null, printed: [], bed_fit_skipped: 'no_bed', max_triangles: null, ...over });
const gate: ReportPrintPart = { name: 'gate_test_block', bed_z: -6, support_area_mm2: 1040.471, bed_contact_mm2: 287.243,
  fits_bed: null, islands: [], islands_total: 2 };

test('a print check that did not run says why, and one that ran says nothing here', () => {
  assert.equal(printSkipText(null, 10), 'Printing was not checked on this run.');
  assert.match(printSkipText(printed({ skip_reason: 'no_settings' }), 10) ?? '', /no printer settings/);
  assert.equal(printSkipText(printed({ skip_reason: 'too_many_triangles', max_triangles: 200000 }), 300000),
    'Printing was not checked: the model has 300000 triangles, more than the 200000 the check reads.');
  assert.match(printSkipText(printed({ skip_reason: 'no_printed_parts' }), 10) ?? '', /stands in for a real object/);
  assert.equal(printSkipText(printed(), 10), null);
});

test('a printed part reads its support area, its bed contact and its bed fit only when a bed is known', () => {
  assert.equal(printPartText(gate, printed()),
    'needs support under 1040 mm² · 287 mm² on the bed · bed size not set, so fit not checked');
  const bed = printed({ bed_fit_skipped: null });
  assert.match(printPartText({ ...gate, fits_bed: true }, bed), /fits the bed$/);
  assert.match(printPartText({ ...gate, fits_bed: false, support_area_mm2: 0 }, bed), /^needs no support .* too big for the bed$/);
});
