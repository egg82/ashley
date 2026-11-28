// The parts are .tsx, which node cannot import, so the test bundles them with esbuild (already the build's tool) and
// imports the result. Controls and Home hold no hooks, so they are called as functions and their vnode text read.
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import { signal } from '@preact/signals';
import { build } from 'esbuild';
import { KINDS } from '../../kiosk/layout.ts';
import { PART_KINDS } from './kinds.ts';
import type { AttentionSource, ControlsSource, HomeSource } from './sources.ts';

const dir = mkdtempSync(join(tmpdir(), 'parts-'));
const outfile = join(dir, 'parts.mjs');
await build({
  stdin: {
    contents: "export * from './registry.tsx'; export * from './Controls.tsx'; export * from './Home.tsx'; export * from './Attention.tsx';",
    resolveDir: import.meta.dirname,
    loader: 'ts',
  },
  bundle: true,
  format: 'esm',
  outfile,
  jsx: 'automatic',
  jsxImportSource: 'preact',
  logLevel: 'silent',
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

test('every kind the layout accepts has a part, and nothing else does', () => {
  assert.deepEqual([...KINDS].sort(), [...PART_KINDS].sort());
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
