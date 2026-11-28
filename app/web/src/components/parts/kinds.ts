/** The kinds a kiosk's layout may place; a layout naming any other is refused (`kiosk/layout.ts`). */
export const LAYOUT_KINDS = ['clock', 'home', 'conversation', 'controls', 'attention', 'printer'] as const;
/** The kinds only a signed-in person's screens draw: they read what the kiosk's cookie cannot. */
export const PERSON_KINDS = ['person'] as const;
/** Every kind of part. Each has an entry in the registry (`registry.tsx`); the type fails to compile without one. */
export const PART_KINDS = [...LAYOUT_KINDS, ...PERSON_KINDS] as const;
export type PartKind = (typeof PART_KINDS)[number];
