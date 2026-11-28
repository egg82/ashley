import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lineBlocks, parse, type Block, type Inline } from './markdown.ts';

const first = (s: string): Block => parse(s)[0]!;
const kids = (s: string): Inline[] => {
  const b = first(s);
  assert.equal(b.kind, 'p');
  return b.kind === 'p' ? b.children : [];
};

test('bold, italic and inline code', () => {
  assert.deepEqual(kids('a **b** _c_ `d`'), [
    { kind: 'text', value: 'a ' }, { kind: 'strong', children: [{ kind: 'text', value: 'b' }] },
    { kind: 'text', value: ' ' }, { kind: 'em', children: [{ kind: 'text', value: 'c' }] },
    { kind: 'text', value: ' ' }, { kind: 'code', value: 'd' },
  ]);
});

test('marks that never close, or sit in a word, stay literal', () => {
  assert.deepEqual(kids('2 * 3 and snake_case_name **open'), [{ kind: 'text', value: '2 * 3 and snake_case_name **open' }]);
});

test('an https link keeps its target', () => {
  assert.deepEqual(kids('[x](https://a.test/p)'), [{ kind: 'link', href: 'https://a.test/p', app: false, children: [{ kind: 'text', value: 'x' }] }]);
});

test("a room's own path is a link that stays in the app", () => {
  for (const path of ['/', '/workshop', '/workshop/12', '/memory', '/household', '/devices', '/connections']) {
    assert.deepEqual(kids(`[x](${path})`), [{ kind: 'link', href: path, app: true, children: [{ kind: 'text', value: 'x' }] }]);
  }
});

test('any other path on this site is only its label', () => {
  for (const path of ['/workshop/12/../../api/me', '/workshop/x', '/api/benches', '//evil.test/workshop', '/memory?x=1']) {
    assert.deepEqual(kids(`[x](${path})`), [{ kind: 'text', value: 'x' }]);
  }
});

test('a javascript: link is only its label', () => {
  assert.deepEqual(kids('[click](javascript:alert(1))'), [{ kind: 'text', value: 'click' }]);
});

test('a relative link is only its label', () => {
  assert.deepEqual(kids('[x](/admin)'), [{ kind: 'text', value: 'x' }]);
});

test('raw HTML is text', () => {
  assert.deepEqual(kids('<script>alert(1)</script>'), [{ kind: 'text', value: '<script>alert(1)</script>' }]);
});

test('bullet and numbered lists, each its own list', () => {
  assert.deepEqual(parse('- a\n- b\n\n1. c\n2) d'), [
    { kind: 'list', ordered: false, items: [[{ kind: 'text', value: 'a' }], [{ kind: 'text', value: 'b' }]] },
    { kind: 'list', ordered: true, items: [[{ kind: 'text', value: 'c' }], [{ kind: 'text', value: 'd' }]] },
  ]);
});

test('lines of a paragraph break, a blank line starts a new one', () => {
  const blocks = parse('a\nb\n\nc');
  assert.equal(blocks.length, 2);
  assert.deepEqual(blocks[0], { kind: 'p', children: [{ kind: 'text', value: 'a' }, { kind: 'br' }, { kind: 'text', value: 'b' }] });
});

test('a heading is a bold paragraph', () => {
  assert.deepEqual(first('## Plan'), { kind: 'p', children: [{ kind: 'strong', children: [{ kind: 'text', value: 'Plan' }] }] });
});

const t = (v: string): Inline[] => [{ kind: 'text', value: v }];

test('a table has a header, per-column alignment from its delimiter row, and body rows of inline nodes', () => {
  const b = first('| a | **b** | c |\n|:--|:-:|--:|\n| 1 | `x` \\| y | 3 |\n| 4 |\n| 5 | 6 | 7 | 8 |\nafter');
  assert.deepEqual(b, {
    kind: 'table', align: ['left', 'center', 'right'],
    head: [t('a'), [{ kind: 'strong', children: t('b') }], t('c')],
    rows: [[t('1'), [{ kind: 'code', value: 'x' }, { kind: 'text', value: ' | y' }], t('3')], [t('4'), [], []], [t('5'), t('6'), t('7')]],
  });
  assert.deepEqual(parse('| a |\n|---|\n| 1 |\nafter')[1], { kind: 'p', children: t('after') });
});

test('a column with a bare delimiter has no alignment', () => {
  const b = first('a | b\n--|--\n1 | 2');
  assert.deepEqual(b.kind === 'table' ? b.align : null, [null, null]);
});

test('pipes with no delimiter row, or a delimiter of another width, stay a paragraph of source text', () => {
  assert.deepEqual(kids('| a | **b** |\n| c | d |'), [
    { kind: 'text', value: '| a | **b** |' }, { kind: 'br' }, { kind: 'text', value: '| c | d |' },
  ]);
  assert.equal(first('| a | b |\n|---|').kind, 'p');
});

test('a fenced block is code, marks inside untouched, and an unclosed fence runs to the end', () => {
  assert.deepEqual(parse('before\n```py\nx = **2**\n\ny\n```\nafter'), [
    { kind: 'p', children: [{ kind: 'text', value: 'before' }] },
    { kind: 'code', value: 'x = **2**\n\ny', language: 'py' },
    { kind: 'p', children: [{ kind: 'text', value: 'after' }] },
  ]);
  assert.deepEqual(parse('```\nopen'), [{ kind: 'code', value: 'open', language: null }]);
});

test('a fence names its language by the first word after the marks, or none', () => {
  const lang = (s: string) => { const b = first(s); return b.kind === 'code' ? b.language : 'not code'; };
  assert.equal(lang('```python\nx\n```'), 'python');
  assert.equal(lang('``` yaml title=a\nx\n```'), 'yaml');
  assert.equal(lang('~~~sh\nx\n~~~'), 'sh');
  assert.equal(lang('```\nx\n```'), null);
});

test('a person\'s typed marks stay literal', () => {
  assert.deepEqual(lineBlocks(false, '**x** - y'), [{ kind: 'p', children: [{ kind: 'text', value: '**x** - y' }] }]);
  assert.deepEqual(lineBlocks(true, '**x**'), [{ kind: 'p', children: [{ kind: 'strong', children: [{ kind: 'text', value: 'x' }] }] }]);
});
