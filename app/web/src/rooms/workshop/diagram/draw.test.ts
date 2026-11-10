import assert from 'node:assert/strict';
import { test } from 'node:test';
import { configFor, draw, messageOf, themeVariables, type MermaidApi } from './draw.ts';

globalThis.document ??= { getElementById: () => null } as unknown as Document;

const TOKENS: Record<string, string> = { '--text': ' #dce7f4', '--ink-3': '#112031', '--blue': '#4da3ff', '--f-body': '"IBM Plex Sans"' };
const vars = themeVariables((t) => TOKENS[t] ?? '');

function fake(render: (id: string, source: string) => Promise<{ svg: string }>): MermaidApi & { configs: Record<string, unknown>[] } {
  const configs: Record<string, unknown>[] = [];
  return { configs, initialize: (c) => { configs.push(c); }, render };
}

test('the theme comes from the page tokens, and a token the page lacks is left out', () => {
  assert.equal(vars.textColor, '#dce7f4');
  assert.equal(vars.primaryColor, '#112031');
  assert.equal(vars.pie1, '#4da3ff');
  assert.equal(vars.pie2, undefined);
  assert.equal(vars.lineColor, undefined);
  assert.equal(vars.fontFamily, '"IBM Plex Sans"');
});

test('the config is the strict level, with no HTML labels and no error diagram drawn into the page', () => {
  const c = configFor(vars);
  assert.equal(c.securityLevel, 'strict');
  assert.equal(c.htmlLabels, false);
  assert.deepEqual(c.flowchart, { htmlLabels: false });
  assert.equal(c.suppressErrorRendering, true);
  assert.equal(c.startOnLoad, false);
});

test('a source that draws gives its svg, and Mermaid was configured first', async () => {
  const m = fake(async (id, source) => ({ svg: `<svg id="${id}">${source}</svg>` }));
  const got = await draw(m, 'pie\n"a": 1', vars);
  assert.equal(got.is, 'svg');
  assert.match(got.is === 'svg' ? got.svg : '', /^<svg id="diagram-\d+">pie/);
  assert.equal(m.configs.length, 1);
});

test('a source Mermaid refuses gives its message, markup left out', async () => {
  const m = fake(async () => { throw new Error('Parse error on line 2:\n<b>A--></b>\nExpecting AMP'); });
  const got = await draw(m, 'flowchart TD\nA-->', vars);
  assert.deepEqual(got, { is: 'error', message: 'Parse error on line 2:\nA-->\nExpecting AMP' });
});

test('an error with no text still says something', () => {
  assert.equal(messageOf(new Error('')), 'Mermaid could not read this diagram.');
  assert.equal(messageOf('plain'), 'plain');
});

test('draws run one at a time, in the order asked', async () => {
  const seen: string[] = [];
  let open = 0;
  let overlapped = false;
  const m = fake(async (_id, source) => {
    open += 1;
    overlapped ||= open > 1;
    await new Promise((r) => setTimeout(r, source === 'slow' ? 20 : 1));
    seen.push(source);
    open -= 1;
    return { svg: source };
  });
  await Promise.all([draw(m, 'slow', vars), draw(m, 'fast', vars)]);
  assert.deepEqual(seen, ['slow', 'fast']);
  assert.equal(overlapped, false);
});

test('a refused draw does not stop the next one', async () => {
  let n = 0;
  const m = fake(async () => { if (n++ === 0) throw new Error('bad'); return { svg: '<svg/>' }; });
  const [a, b] = await Promise.all([draw(m, 'x', vars), draw(m, 'y', vars)]);
  assert.equal(a.is, 'error');
  assert.equal(b.is, 'svg');
});
