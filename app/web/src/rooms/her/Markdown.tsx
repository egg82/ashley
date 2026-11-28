// The text of one line: hers as Markdown elements built from the parsed tree (never as HTML), a person's literal; and
// any other text shown as that Markdown (a bench's pieces).
import type { ComponentChildren } from 'preact';
import { CodeBlock } from '../../highlight/CodeBlock';
import { lineBlocks, parse, type Block, type Inline } from './markdown.ts';

function inlines(nodes: readonly Inline[]): ComponentChildren {
  return nodes.map((n) => {
    switch (n.kind) {
      case 'text': return n.value;
      case 'br': return <br />;
      case 'code': return <code>{n.value}</code>;
      case 'strong': return <strong>{inlines(n.children)}</strong>;
      case 'em': return <em>{inlines(n.children)}</em>;
      // A room's own path stays in this page, where the router takes the click and flies there.
      case 'link': return n.app
        ? <a class="md-link" href={n.href}>{inlines(n.children)}</a>
        : <a class="md-link" href={n.href} target="_blank" rel="noopener noreferrer">{inlines(n.children)}</a>;
    }
  });
}

function Table({ t }: { t: Extract<Block, { kind: 'table' }> }) {
  // A column aligned right or centre holds figures, which never break across lines.
  const style = (i: number) => {
    const align = t.align[i];
    if (!align) return undefined;
    return align === 'left' ? { textAlign: align } : { textAlign: align, whiteSpace: 'nowrap' };
  };
  return (
    <div class="md-scroll">
      <table class="md-table">
        <thead><tr>{t.head.map((c, i) => <th style={style(i)}>{inlines(c)}</th>)}</tr></thead>
        <tbody>{t.rows.map((r) => <tr>{r.map((c, i) => <td style={style(i)}>{inlines(c)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function block(b: Block) {
  switch (b.kind) {
    case 'p': return <p>{inlines(b.children)}</p>;
    case 'code': return <CodeBlock class="md-pre" code={b.value} language={b.language} />;
    case 'table': return <Table t={b} />;
    case 'list': {
      const items = b.items.map((i) => <li>{inlines(i)}</li>);
      return b.ordered ? <ol class="md-list">{items}</ol> : <ul class="md-list">{items}</ul>;
    }
  }
}

export function LineText({ hers, text }: { hers: boolean; text: string }) {
  return <>{lineBlocks(hers, text).map(block)}</>;
}

/** `text` as Markdown elements, whoever wrote it. */
export function MarkdownText({ text }: { text: string }) {
  return <>{parse(text).map(block)}</>;
}
