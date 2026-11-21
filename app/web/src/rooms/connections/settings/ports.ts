// A connection's port switches as the page edits them: one line per port the kind declares, on unless the draft lists it
// in `ports_off`. Pure, so the lines and the toggle are tested without the page.
import type { SettingInfo } from '../../../api/types';
import { LIST, idsOf, toggled, withIds, type Draft } from './draft.ts';
import names from './portNames.json' with { type: 'json' };

export const KEY = 'ports_off';

const NAMES: Record<string, { name: string; sub: string }> = names;

export interface PortLine {
  port: string;
  name: string;
  sub: string;
  on: boolean;
}

/** The ports the kind declares (none when it has no switches), in the order the server gives them. */
export function portsOf(settings: readonly SettingInfo[]): string[] {
  const found = settings.find((s) => s.key === KEY);
  return found && found.field.type === 'port_switches' ? [...found.field.ports] : [];
}

function humanised(port: string): string {
  const text = port.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function portLines(settings: readonly SettingInfo[], draft: Draft): PortLine[] {
  const off = idsOf(draft, KEY);
  return portsOf(settings).map((port) => ({
    port,
    name: NAMES[port]?.name ?? humanised(port),
    sub: NAMES[port]?.sub ?? '',
    on: !off.includes(port),
  }));
}

/** The draft with `port` flipped. */
export function flipped(draft: Draft, port: string): Draft {
  return withIds(draft, KEY, LIST, toggled(idsOf(draft, KEY), port));
}
