// Her short Markdown as a tree: paragraphs, bullet and numbered lists, fenced code, and inline bold, italic, code and
// links. Raw HTML is plain text; a link keeps its target only for http, https and mailto, or for one of the rooms' own
// paths (`app`, opened in place), else it is its label.
import { isRoomPath } from '../../shell/rooms.ts';

export type Inline =
  | { kind: 'text'; value: string }
  | { kind: 'br' }
  | { kind: 'code'; value: string }
  | { kind: 'strong' | 'em'; children: Inline[] }
  | { kind: 'link'; href: string; app: boolean; children: Inline[] };

export type Block =
  | { kind: 'p'; children: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] }
  | { kind: 'code'; value: string; language: string | null };

const SAFE = new Set(['http:', 'https:', 'mailto:']);
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBER = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;
const FENCE = /^\s{0,3}(```|~~~)\s*([^\s`]*)/;

function safeHref(target: string): string | null {
  if (isRoomPath(target)) return target;
  try {
    const url = new URL(target);
    return SAFE.has(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function closer(s: string, from: number, mark: string): number {
  const at = s.indexOf(mark, from);
  return at > from ? at : -1;
}

function emphasis(s: string, i: number): { node: Inline; end: number } | null {
  const c = s[i]!;
  const double = s.startsWith(c + c, i);
  const mark = double ? c + c : c;
  const start = i + mark.length;
  if (start >= s.length || /\s/.test(s[start]!)) return null;
  if (c === '_' && i > 0 && /\w/.test(s[i - 1]!)) return null;
  const at = closer(s, start, mark);
  if (at < 0 || /\s/.test(s[at - 1]!)) return null;
  if (c === '_' && /\w/.test(s[at + mark.length] ?? '')) return null;
  return { node: { kind: double ? 'strong' : 'em', children: inline(s.slice(start, at)) }, end: at + mark.length };
}

function closingParen(s: string, from: number): number {
  for (let depth = 0, i = from; i < s.length; i++) {
    if (s[i] === '(') depth++;
    else if (s[i] === ')' && depth-- === 0) return i;
  }
  return -1;
}

function link(s: string, i: number): { node: Inline[]; end: number } | null {
  const mid = s.indexOf('](', i);
  const end = mid < 0 ? -1 : closingParen(s, mid + 2);
  if (mid < 0 || end < 0 || s.slice(i + 1, mid).includes('[')) return null;
  const label = inline(s.slice(i + 1, mid));
  const href = safeHref(s.slice(mid + 2, end).trim());
  return { node: href ? [{ kind: 'link', href, app: isRoomPath(href), children: label }] : label, end: end + 1 };
}

function inline(s: string): Inline[] {
  const out: Inline[] = [];
  let text = '';
  const flush = () => { if (text) out.push({ kind: 'text', value: text }), (text = ''); };
  let i = 0;
  while (i < s.length) {
    const c = s[i]!;
    let hit: { nodes: Inline[]; end: number } | null = null;
    if (c === '`') {
      const at = closer(s, i + 1, '`');
      if (at > 0) hit = { nodes: [{ kind: 'code', value: s.slice(i + 1, at) }], end: at + 1 };
    } else if (c === '*' || c === '_') {
      const e = emphasis(s, i);
      if (e) hit = { nodes: [e.node], end: e.end };
    } else if (c === '[') {
      const l = link(s, i);
      if (l) hit = { nodes: l.node, end: l.end };
    }
    if (hit) { flush(); out.push(...hit.nodes); i = hit.end; } else { text += c; i++; }
  }
  flush();
  return out;
}

function joined(lines: string[], literal: boolean): Inline[] {
  return lines.flatMap((l, i): Inline[] => {
    const body: Inline[] = literal ? [{ kind: 'text', value: l }] : inline(l);
    return i ? [{ kind: 'br' }, ...body] : body;
  });
}

function fenced(lines: string[], from: number, mark: string, language: string): { block: Block; end: number } {
  let end = from + 1;
  while (end < lines.length && !lines[end]!.trimStart().startsWith(mark)) end++;
  return { block: { kind: 'code', value: lines.slice(from + 1, end).join('\n'), language: language || null }, end };
}

export function parse(source: string): Block[] {
  const blocks: Block[] = [];
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  let para: string[] = [];
  let table = false;
  let list: { ordered: boolean; items: Inline[][] } | null = null;
  const endPara = () => {
    if (para.length) blocks.push({ kind: 'p', children: joined(para, table) });
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const fence = FENCE.exec(line);
    const item = BULLET.exec(line) ?? NUMBER.exec(line);
    const heading = HEADING.exec(line);
    const row = line.trimStart().startsWith('|');
    if (!item && !(list && /^\s+\S/.test(line))) list = null;
    if (!line.trim() || fence || item || heading || table !== row) endPara();
    if (fence) {
      const { block, end } = fenced(lines, i, fence[1]!, fence[2]!);
      blocks.push(block);
      i = end;
    } else if (item) {
      const ordered = NUMBER.test(line);
      if (!list || list.ordered !== ordered) {
        list = { ordered, items: [] };
        blocks.push({ kind: 'list', ...list });
      }
      list.items.push(inline(item[1]!));
    } else if (list) {
      list.items[list.items.length - 1]!.push({ kind: 'br' }, ...inline(line.trim()));
    } else if (heading) {
      blocks.push({ kind: 'p', children: [{ kind: 'strong', children: inline(heading[1]!) }] });
    } else if (line.trim()) {
      table = row;
      para.push(line);
    }
  }
  endPara();
  return blocks;
}

/** Only her lines are Markdown; a person's typed text is one literal paragraph. */
export function lineBlocks(hers: boolean, text: string): Block[] {
  return hers ? parse(text) : [{ kind: 'p', children: [{ kind: 'text', value: text }] }];
}
