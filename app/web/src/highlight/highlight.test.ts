import assert from 'node:assert/strict';
import { test } from 'node:test';
import { highlightCode, MIN_RELEVANCE } from './highlight.ts';
import { GRAMMARS, languageNamed } from './languages.ts';

const SAMPLES: Record<string, { tag: string; code: string; token: string }> = {
  python: { tag: 'py', code: 'def f(n):\n    return n + 1\n', token: '<span class="hljs-keyword">def</span>' },
  typescript: { tag: 'ts', code: 'const x: number = 3;\n', token: '<span class="hljs-keyword">const</span>' },
  javascript: { tag: 'js', code: 'const x = 3;\n', token: '<span class="hljs-keyword">const</span>' },
  yaml: { tag: 'yml', code: 'alias: Porch\nmode: single\n', token: '<span class="hljs-attr">alias:</span>' },
  json: { tag: 'json', code: '{"a": 1}', token: '<span class="hljs-attr">&quot;a&quot;</span>' },
  bash: { tag: 'sh', code: 'for f in *; do echo "$f"; done\n', token: '<span class="hljs-keyword">for</span>' },
  sql: { tag: 'sql', code: 'SELECT id FROM people;', token: '<span class="hljs-keyword">SELECT</span>' },
  c: { tag: 'c', code: 'int main(void) { return 0; }', token: '<span class="hljs-keyword">return</span>' },
  cpp: { tag: 'arduino', code: 'void setup() { pinMode(13, OUTPUT); }', token: '<span class="hljs-built_in">pinMode</span>' },
  markdown: { tag: 'md', code: '# Title\n\n**bold**\n', token: '<span class="hljs-section"># Title</span>' },
};

test('every grammar has a sample, and each sample colours through its fence tag', async () => {
  assert.deepEqual(Object.keys(SAMPLES).sort(), Object.keys(GRAMMARS).sort());
  for (const [name, s] of Object.entries(SAMPLES)) {
    assert.equal(languageNamed(s.tag), name, s.tag);
    const html = await highlightCode(s.code, s.tag);
    assert.ok(html?.includes(s.token), `${name}: ${html}`);
  }
});

test('a language we do not colour, or a blank body, stays plain, and never falls back to guessing', async () => {
  assert.equal(languageNamed('rust'), null);
  assert.equal(languageNamed('text'), null);
  assert.equal(await highlightCode('fn main() { let x = 1; }', 'rust'), null);
  assert.equal(await highlightCode('   \n', 'python'), null);
  assert.equal(await highlightCode('   \n', null), null);
});

test('the code is escaped, so markup in it is text', async () => {
  const html = await highlightCode('x = "<script>alert(1)</script>" # <b>', 'python');
  assert.ok(html && !html.includes('<script>') && !html.includes('<b>'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('with no language, code that fits one is coloured and prose, listings and logs stay plain', async () => {
  const code = await highlightCode('#!/bin/bash\nset -e\nfor f in *.txt; do echo "$f"; done\n', null);
  assert.ok(code?.includes('hljs-keyword'));
  const yaml = await highlightCode('alias: Porch\ntriggers:\n  - trigger: sun\n    event: sunset\n', null);
  assert.ok(yaml?.includes('hljs-attr'));
  const plain = [
    'The strip draws about three amps at full white, so the supply has headroom. If the fan runs for ten minutes, check the temperature: it should stay under 40 degrees (104 F).',
    'app/\n  web/\n    src/\n      main.tsx\n  tests/\n',
    '2026-10-31 12:00:01 INFO started worker=3 count=12\n2026-10-31 12:00:02 INFO done in 1.2s\n',
  ];
  for (const text of plain) assert.equal(await highlightCode(text, null), null, text);
  assert.ok(MIN_RELEVANCE > 0);
});
