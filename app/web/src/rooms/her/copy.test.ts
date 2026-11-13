import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

// The room's words are checked as the code has them (`voice.md`): every string literal, template and piece of JSX text a
// person can read, found by parsing the source rather than by what the model says. A page never names a conversation
// as a thing it holds, never calls her the assistant, and does not apologise or exclaim.
const BANNED: readonly [string, RegExp][] = [
  ['names a conversation container', /\b(conversations?|chats?|threads?)\b/i],
  ['calls her something other than her name', /\b(the (assistant|bot|model)|AI)\b/i],
  ['apologises or exclaims', /\b(please|sorry|oops)\b|!/i],
];

const SHOWN_ATTRIBUTES = new Set(['title', 'aria-label', 'placeholder', 'alt']);

/** The strings a person can read in `source`: JSX text, and literals that are words rather than a name or a path. */
export function shownStrings(source: string): string[] {
  const file = ts.createSourceFile('x.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node) || ts.isTypeNode(node)) return;
    if (ts.isJsxText(node)) found.push(node.text);
    if (ts.isJsxAttribute(node)) {
      if (!SHOWN_ATTRIBUTES.has(node.name.getText(file))) return;
    } else if (ts.isStringLiteralLike(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      if (/\s/.test(node.text.trim()) || /^[A-Z]/.test(node.text)) found.push(node.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found.map((s) => s.replace(/\s+/g, ' ').trim()).filter(Boolean);
}

export function violations(source: string): string[] {
  return shownStrings(source).flatMap((s) => BANNED.filter(([, rule]) => rule.test(s)).map(([why]) => `"${s}" ${why}`));
}

const here = fileURLToPath(new URL('.', import.meta.url));
const sources = readdirSync(here).filter((f) => /\.tsx?$/.test(f) && !/\.test\.ts$/.test(f) && !/Support\.ts$/.test(f));

test('the checker finds a conversation container in text and attributes, and skips names and paths', () => {
  assert.deepEqual(violations('const a = <button>New chat</button>;'), ['"New chat" names a conversation container']);
  assert.deepEqual(violations("const a = 'No conversation open';"), ['"No conversation open" names a conversation container']);
  assert.equal(violations('const a = <input placeholder="Send a message, please!" />;').length, 1);
  assert.deepEqual(violations("import { chat } from './chat'; const c = 'chat-quiet';"), []);
});

test('no string her room shows names a conversation container, her as a thing, or apologises', () => {
  assert.ok(sources.length > 10);
  const bad = sources.flatMap((f) => violations(readFileSync(`${here}${f}`, 'utf8')).map((v) => `${f}: ${v}`));
  assert.deepEqual(bad, []);
});
