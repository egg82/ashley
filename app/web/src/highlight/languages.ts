// The languages the client highlights, each loaded on first use: its highlight.js name, the fence tags and file-style
// names that mean it, and its grammar. A name not here is not highlighted.
import type { LanguageFn } from 'highlight.js';

export type Language = 'python' | 'typescript' | 'javascript' | 'yaml' | 'json' | 'bash' | 'sql' | 'c' | 'cpp' | 'markdown';

type Grammar = () => Promise<{ default: LanguageFn }>;

export const GRAMMARS: Record<Language, Grammar> = {
  python: () => import('highlight.js/lib/languages/python'),
  typescript: () => import('highlight.js/lib/languages/typescript'),
  javascript: () => import('highlight.js/lib/languages/javascript'),
  yaml: () => import('highlight.js/lib/languages/yaml'),
  json: () => import('highlight.js/lib/languages/json'),
  bash: () => import('highlight.js/lib/languages/bash'),
  sql: () => import('highlight.js/lib/languages/sql'),
  c: () => import('highlight.js/lib/languages/c'),
  cpp: () => import('highlight.js/lib/languages/cpp'),
  markdown: () => import('highlight.js/lib/languages/markdown'),
};

const TAGS: Record<Language, readonly string[]> = {
  python: ['python', 'py', 'python3', 'build123d'],
  typescript: ['typescript', 'ts', 'tsx'],
  javascript: ['javascript', 'js', 'jsx', 'mjs', 'node'],
  yaml: ['yaml', 'yml'],
  json: ['json', 'jsonc'],
  bash: ['bash', 'sh', 'shell', 'zsh', 'console'],
  sql: ['sql', 'postgres', 'postgresql', 'sqlite', 'mysql'],
  c: ['c', 'h'],
  cpp: ['cpp', 'c++', 'cc', 'hpp', 'arduino', 'ino'],
  markdown: ['markdown', 'md'],
};

const BY_TAG = new Map<string, Language>(
  (Object.keys(TAGS) as Language[]).flatMap((l) => TAGS[l].map((t): [string, Language] => [t, l])),
);

/** The language a fence tag or a kind's `language` names, or null when it names none this client highlights. */
export function languageNamed(tag: string | null | undefined): Language | null {
  return BY_TAG.get((tag ?? '').trim().toLowerCase()) ?? null;
}
