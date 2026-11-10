// A highlighted passage cut out of its paragraph. The server counts characters in code points, so a paragraph is cut by
// code point too, never by UTF-16 unit, or a highlight after an emoji lands two characters early.

export interface Cut {
  before: string;
  hit: string;
  after: string;
}

/** `text` cut at code points `start` and `end` (the server's range, `start < end`). */
export function cut(text: string, start: number, end: number): Cut {
  const chars = Array.from(text);
  return { before: chars.slice(0, start).join(''), hit: chars.slice(start, end).join(''), after: chars.slice(end).join('') };
}
