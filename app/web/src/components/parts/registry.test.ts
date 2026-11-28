// The parts are .tsx, which node cannot import, so the test bundles them with esbuild (already the build's tool) and
// imports the result. Controls and Home hold no hooks, so they are called as functions and their vnode text read.
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import { signal } from '@preact/signals';
import { build, type Plugin } from 'esbuild';
import { KINDS } from '../../kiosk/layout.ts';
import { LAYOUT_KINDS, PART_KINDS } from './kinds.ts';
import type { HousePrinter, MemoryFact, Voiceprint } from '../../api/types';
import type { AttentionSource, ControlsSource, HomeSource, PersonSource, PrinterSource } from './sources.ts';

// The fact cards the person part draws import the page's motion module, which reads the browser as it loads.
const motionStub: Plugin = {
  name: 'motion-stub',
  setup(b) {
    b.onResolve({ filter: /shell\/motion$/ }, () => ({ path: 'motion', namespace: 'stub' }));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export const reduced = () => true; export const pause = async () => {};', loader: 'js' }));
  },
};

const dir = mkdtempSync(join(tmpdir(), 'parts-'));
const outfile = join(dir, 'parts.mjs');
await build({
  stdin: {
    contents: "export * from './registry.tsx'; export * from './Controls.tsx'; export * from './Home.tsx'; export * from './Attention.tsx'; export * from './Printer.tsx'; export * from './Person.tsx';",
    resolveDir: import.meta.dirname,
    loader: 'ts',
  },
  bundle: true,
  format: 'esm',
  outfile,
  jsx: 'automatic',
  jsxImportSource: 'preact',
  logLevel: 'silent',
  plugins: [motionStub],
});
const parts = await import(pathToFileURL(outfile).href);

interface Node { props?: { children?: unknown; [k: string]: unknown } }

function textOf(node: unknown): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  return textOf((node as Node).props?.children);
}

function find(node: unknown, pick: (n: Node) => boolean, out: Node[] = []): Node[] {
  if (Array.isArray(node)) node.forEach((n) => find(n, pick, out));
  else if (node && typeof node === 'object') {
    if (pick(node as Node)) out.push(node as Node);
    find((node as Node).props?.children, pick, out);
  }
  return out;
}

test('every kind has a part, and the kiosk layout accepts all but the person\'s', () => {
  assert.deepEqual([...KINDS].sort(), [...LAYOUT_KINDS].sort());
  assert.ok(!KINDS.includes('person'));
  assert.deepEqual(Object.keys(parts.PARTS).sort(), [...PART_KINDS].sort());
  for (const kind of PART_KINDS) assert.equal(typeof parts.PARTS[kind].draw, 'function', kind);
});

test('drawPart draws the conversation for a kind with no part', () => {
  const sources = { controls: stubControls(), home: stubHome(['Sam']), attention: stubAttention(null), conversation: () => 'talk' };
  assert.equal(parts.drawPart('conversation', sources), 'talk');
  assert.equal(parts.drawPart('nope', sources), 'talk');
});

function stubControls(pressed: string[] = []): ControlsSource {
  return {
    controls: signal([
      { name: 'lamp', label: 'Lamp', on: true },
      { name: 'fan', label: 'Fan', on: null },
    ]),
    states: signal({ fan: 'done' }),
    press: async (name) => { pressed.push(name); },
  } as ControlsSource;
}

function stubHome(names: readonly string[] | null | undefined): HomeSource {
  return { home: signal(names) };
}

test('controls render from a stub source and a press goes to it', () => {
  const pressed: string[] = [];
  const tree = parts.Controls({ source: stubControls(pressed) });
  const text = textOf(tree);
  assert.match(text, /Lamp.*On/);
  assert.match(text, /Fan.*Done/);
  const buttons = find(tree, (n) => typeof n.props?.onClick === 'function');
  assert.equal(buttons.length, 2);
  (buttons[0]?.props?.onClick as () => void)();
  assert.deepEqual(pressed, ['lamp']);
});

test('controls with none set say so', () => {
  const source = { ...stubControls(), controls: signal([]) } as ControlsSource;
  assert.match(textOf(parts.Controls({ source })), /none set/);
});

test('controls that could not be read say so, and are not called none set', () => {
  const unread = textOf(parts.Controls({ source: { ...stubControls(), controls: signal(null) } as ControlsSource }));
  assert.match(unread, /couldn't read/);
  assert.doesNotMatch(unread, /none set/);
  const reading = textOf(parts.Controls({ source: { ...stubControls(), controls: signal(undefined) } as ControlsSource }));
  assert.match(reading, /Reading/);
  assert.doesNotMatch(reading, /none set/);
});

function stubAttention(read: AttentionSource['attention']['value']): AttentionSource {
  return { attention: signal(read) };
}

test('needs attention shows an unread part as unknown beside its name, and zero as clear', () => {
  const unread = textOf(parts.Attention({ source: stubAttention({ waiting_on_you: null, printer_faults: 0, house_unreadable: false }) }));
  assert.match(unread, /Waiting on you.*unknown/);
  assert.doesNotMatch(unread, /Nothing needs you/);
  const clear = textOf(parts.Attention({ source: stubAttention({ waiting_on_you: 0, printer_faults: 0, house_unreadable: false }) }));
  assert.match(clear, /Nothing needs you/);
  assert.doesNotMatch(clear, /unknown/);
  assert.match(textOf(parts.Attention({ source: stubAttention(undefined) })), /Reading/);
});

test('home hands the source\'s names to the list, which says unknown or nobody otherwise', () => {
  const names = find(parts.Home({ source: stubHome(['Sam', 'Ada']) }), (n) => 'names' in (n.props ?? {}))[0];
  assert.deepEqual(names?.props?.names, ['Sam', 'Ada']);
  assert.match(textOf(parts.HomeNames({ names: ['Sam', 'Ada'] })), /Sam.*Ada/);
  assert.match(textOf(parts.HomeNames({ names: null })), /unknown/);
  assert.match(textOf(parts.HomeNames({ names: [] })), /Nobody home/);
});

function stubPrinter(printers: readonly HousePrinter[] | null | undefined): PrinterSource {
  return { printers: signal(printers), watch: () => () => undefined };
}

const RUNNING: HousePrinter = {
  printer_id: '01P', name: 'Workshop P1S', printer_model: 'P1S', online: true, state: 'RUNNING', print_name: 'benchy.3mf',
  percent: 42.5, minutes_left: 75, layer: 120, layers: 300, problems: ['Nozzle clog'],
};

test('a printer card shows the printer its ref names: the print, how far, time left and faults', () => {
  const text = textOf(parts.PrinterCard({ source: stubPrinter([RUNNING]), printerId: '01P' }));
  assert.match(text, /Workshop P1S.*Printing.*benchy\.3mf.*43%.*1 h 15 m left.*layer 120 \/ 300.*Nozzle clog/);
});

test('a printer that cannot be read, or is not in the read, is unknown and never idle', () => {
  for (const source of [stubPrinter(null), stubPrinter([RUNNING])]) {
    const text = textOf(parts.PrinterCard({ source, printerId: '02X' }));
    assert.match(text, /unknown/);
    assert.doesNotMatch(text, /Idle/);
  }
  const silent = textOf(parts.PrinterCard({ source: stubPrinter([{ ...RUNNING, state: null, print_name: null, percent: null }]), printerId: '01P' }));
  assert.match(silent, /unknown/);
  assert.doesNotMatch(silent, /Idle/);
  assert.match(textOf(parts.PrinterCard({ source: stubPrinter(undefined), printerId: '01P' })), /Reading/);
});

test('a brought-up printer folds to a chip named for it, or for its kind when its name is unknown', () => {
  const sources = { controls: stubControls(), home: stubHome([]), attention: stubAttention(null), conversation: () => null };
  assert.equal(parts.chipOf('printer', { ...sources, printer: stubPrinter([RUNNING]) }, '01P'), 'Printer · Workshop P1S');
  assert.equal(parts.chipOf('printer', { ...sources, printer: stubPrinter(null) }, '01P'), 'Printer');
});

function stubPerson(facts: readonly MemoryFact[] | null | undefined, prints: readonly Voiceprint[] | null | undefined): PersonSource {
  return { facts: signal(facts), prints: signal(prints), read: async () => undefined };
}

const both = (source: PersonSource) => [parts.PersonFacts({ source }), parts.PersonPrints({ source })];
const unknownOf = (tree: unknown) => find(tree, (n) => typeof n.props?.what === 'string').map((n) => n.props?.what);

test('a person card that cannot read facts or prints says unknown, and never that she knows nothing', () => {
  const unread = both(stubPerson(null, null));
  assert.deepEqual(unknownOf(unread), ['what she knows', 'your voiceprints']);
  assert.doesNotMatch(textOf(unread), /doesn't know/);
  assert.match(textOf(both(stubPerson(undefined, undefined))), /Reading what she knows.*Reading her voiceprints/);
});

test('a person card with nothing read back says so, apart from unknown', () => {
  const read = both(stubPerson([], []));
  const text = textOf(read);
  assert.deepEqual(unknownOf(read), []);
  assert.match(text, /doesn't know anything about you yet.*doesn't know your voice/);
  });

test('a person card counts the voiceprints and names the device each was taken on', () => {
  const prints = [{ device: 'Kitchen', enrolled_at: '2026-11-01T10:00:00Z' }, { device: 'Den', enrolled_at: '2026-10-01T10:00:00Z' }];
  assert.match(textOf(parts.PersonCard({ source: stubPerson([], prints) })), /2\s+prints/);
  assert.match(textOf(parts.PersonPrints({ source: stubPerson([], prints) })), /Taken on\s+Den.*Taken on\s+Kitchen/);
});

test('the kiosk has no person source, so a person part draws nothing there', () => {
  const sources = { controls: stubControls(), home: stubHome([]), attention: stubAttention(null), printer: stubPrinter([]), conversation: () => 'talk' };
  assert.equal(parts.drawPart('person', sources), null);
});
