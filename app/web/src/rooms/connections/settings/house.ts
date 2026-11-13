// What the house has, as the settings page lists it: the things and actions it offers, by id, with the names a person knows
// them by. Pure over the catalogue, so the rows and the search are tested without the page.
import type { CatalogueActionInfo, CatalogueEntityInfo, ConnectionCatalogue } from '../../../api/types';
import { handledAnyway } from './careful.ts';
import { choiceOf, type Choice, type Stored } from './lookups.ts';

const SHOWN = 8;
const LOOK_UP_DOMAINS: readonly string[] = ['script', 'weather'];

/** One line of the page: a thing or action by `name`, its small secondary text, and whether the house lacks it now. */
export interface Line {
  id: string;
  name: string;
  sub: string;
  missing: boolean;
}

export interface ListLine extends Line {
  only: boolean;
}

export interface LookupLine extends Line {
  choice: Choice;
  fixed: boolean;
}

export interface NeedLine extends Line {
  already: boolean;
}

/** `catalogue` is null until the house has answered (or when it will not). */
export type House = ConnectionCatalogue | null;

function humanised(id: string): string {
  const text = id.slice(id.indexOf('.') + 1).replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function byName<T extends Line>(lines: T[]): T[] {
  return lines.sort((a, b) => a.name.localeCompare(b.name));
}

function entityIn(house: House, id: string): CatalogueEntityInfo | undefined {
  return house?.entities.find((e) => e.entity_id === id);
}

/** The name of a thing or action: the house's own name for it (a script is also a thing of the same id), else its id made readable. */
export function nameOf(house: House, id: string): string {
  return entityIn(house, id)?.name ?? humanised(id);
}

/** One line per to-do list the house has, plus any stored list it no longer has. */
export function listLines(house: House, stored: readonly string[]): ListLine[] {
  const have = (house?.entities ?? []).filter((e) => e.domain === 'todo').map((e) => e.entity_id);
  const ids = [...have, ...stored.filter((id) => !have.includes(id))];
  return byName(ids.map((id) => ({ id, name: nameOf(house, id), sub: id, missing: house !== null && !have.includes(id), only: stored.includes(id) })));
}

/** One line per calendar the house has, plus any stored one it no longer has; `only` is true for one the hallway screen shows. */
export function calendarLines(house: House, stored: readonly string[]): ListLine[] {
  const have = (house?.entities ?? []).filter((e) => e.domain === 'calendar').map((e) => e.entity_id);
  const ids = [...have, ...stored.filter((id) => !have.includes(id))];
  return byName(ids.map((id) => ({ id, name: nameOf(house, id), sub: id, missing: house !== null && !have.includes(id), only: stored.includes(id) })));
}

function actionsOf(house: House): CatalogueActionInfo[] {
  return (house?.actions ?? []).filter((a) => LOOK_UP_DOMAINS.includes(a.domain));
}

function lookupLine(house: House, stored: Stored, id: string): LookupLine {
  const action = house?.actions.find((a) => a.name === id);
  const fixed = action?.looks_up_only ?? false;
  return { id, name: nameOf(house, id), sub: id, missing: house !== null && !action, choice: choiceOf(id, stored, fixed), fixed };
}

/** Every script and look-up action the house offers or the settings name, one line each. */
export function lookupLines(house: House, stored: Stored): LookupLine[] {
  const ids = new Set([...actionsOf(house).map((a) => a.name), ...stored.reads, ...stored.service]);
  return byName([...ids].map((id) => lookupLine(house, stored, id)));
}

/** The things listed as needing her word, each marked when she handles it that way anyway. */
export function needLines(house: House, ids: readonly string[]): NeedLine[] {
  return ids.map((id) => {
    const thing = entityIn(house, id);
    return { id, name: nameOf(house, id), sub: thing ? kindOf(thing) : id, missing: house !== null && !thing, already: thing ? handledAnyway(thing) : false };
  });
}

function kindOf(thing: CatalogueEntityInfo): string {
  return thing.device_class ?? '';
}

/** Things matching `query` (by name or id) that are not listed yet, at most a few; empty for an empty query. */
export function found(house: House, query: string, listed: readonly string[]): { shown: NeedLine[]; more: number } {
  const words = query.trim().toLowerCase();
  if (!words || !house) return { shown: [], more: 0 };
  const hits = house.entities.filter((e) => !listed.includes(e.entity_id) && `${e.name} ${e.entity_id}`.toLowerCase().includes(words));
  const shown = hits.slice(0, SHOWN).map((e) => ({ id: e.entity_id, name: e.name, sub: kindOf(e), missing: false, already: handledAnyway(e) }));
  return { shown, more: hits.length - shown.length };
}
