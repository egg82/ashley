// Highlights code with highlight.js (core plus the grammars in `languages.ts`), loaded on first use so the first paint
// never waits on it. The result is highlight.js's own HTML, whose text is escaped, or null when the code is to show plain.
import hljs from 'highlight.js/lib/core';
import { GRAMMARS, languageNamed, type Language } from './languages.ts';

/** The least relevance an auto-detected language needs for its colours to show; below it the code stays plain. */
export const MIN_RELEVANCE = 4;

/** The longest text auto-detection reads, since it runs every grammar over it. */
export const AUTO_MAX_CHARS = 20000;

async function register(language: Language): Promise<void> {
  if (hljs.getLanguage(language)) return;
  hljs.registerLanguage(language, (await GRAMMARS[language]()).default);
}

/**
 * `code` as highlight.js HTML. `language` names the language (a fence tag, or a kind's `language`): a name that is none
 * of ours gives null, since she named a language we cannot colour. With no name, the grammars are tried over the text
 * and the best fit is used when it is relevant enough.
 */
export async function highlightCode(code: string, language: string | null): Promise<string | null> {
  if (!code.trim()) return null;
  const named = languageNamed(language);
  if (named) {
    await register(named);
    return hljs.highlight(code, { language: named, ignoreIllegals: true }).value;
  }
  if (language?.trim() || code.length > AUTO_MAX_CHARS) return null;
  const all = Object.keys(GRAMMARS) as Language[];
  await Promise.all(all.map(register));
  const found = hljs.highlightAuto(code, all);
  return found.relevance >= MIN_RELEVANCE ? found.value : null;
}
