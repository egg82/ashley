// Whether a conversation still owes the person an answer. Her line that went out while the answer was still to come
// (`follows`, a held "let me check") does not answer; any other line of hers does.

interface Said {
  author: 'person' | 'ashley' | 'household';
  text: string;
  follows?: boolean;
  /** Set on the person's line while her work on it is in flight (`ChatConversationTurn.working`). */
  working?: boolean;
}

/** The index of the person's line still owed an answer: the last line, or the one before her trailing held lines, when
 * it is theirs; -1 when none is owed. */
export function owedAt(lines: readonly Said[]): number {
  let i = lines.length - 1;
  while (i >= 0 && lines[i]!.author === 'ashley' && lines[i]!.follows) i--;
  return i >= 0 && lines[i]!.author === 'person' ? i : -1;
}

/** Whether the lines end with her answer to a line of the person's saying `text`, her held lines between them. */
export function answered(lines: readonly Said[], text: string): boolean {
  const last = lines.at(-1);
  if (last?.author !== 'ashley' || last.follows) return false;
  let i = lines.length - 1;
  while (i >= 0 && lines[i]!.author === 'ashley') i--;
  return i >= 0 && lines[i]!.text === text;
}

/** Whether she is still working on the turn she is answering: the server has its work in flight, so it is pending and
 * not missed, whoever sent it, the household's turn a bench change started included. */
export function stillOn(lines: readonly Said[]): boolean {
  let i = lines.length - 1;
  while (i >= 0 && lines[i]!.author === 'ashley' && lines[i]!.follows) i--;
  return i >= 0 && lines[i]!.author !== 'ashley' && lines[i]!.working === true;
}
