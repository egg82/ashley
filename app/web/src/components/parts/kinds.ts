/** The kinds of part a shell can arrange. Each has an entry in the registry (`registry.tsx`); the type fails to compile without one. */
export const PART_KINDS = ['clock', 'home', 'conversation', 'controls', 'attention', 'printer'] as const;
export type PartKind = (typeof PART_KINDS)[number];
