// Whether Ashley already handles a thing with care without it being listed: its kind of thing is not one she changes freely.
// The data is `careful.json`, held equal to `ashley/tools/tiers.json` by a test there.
import careful from './careful.json' with { type: 'json' };

/** `device_class` as Home Assistant gives it (null when it gives none). */
export interface Kind {
  domain: string;
  device_class: string | null;
}

const FREE = new Set<string>(careful.domains);
const CAREFUL_CLASSES: Record<string, readonly string[] | undefined> = careful.careful_classes;

export function handledAnyway(thing: Kind): boolean {
  if (!FREE.has(thing.domain)) return true;
  return thing.device_class !== null && (CAREFUL_CLASSES[thing.domain] ?? []).includes(thing.device_class);
}
