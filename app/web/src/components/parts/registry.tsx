// The parts a shell arranges, by kind: a Type Object table, the kind's data rather than a class per kind. A shell keeps
// its own grid and arrangement and draws each placed kind through `drawPart`.
import type { ComponentChildren } from 'preact';
import { Clock } from './Clock';
import { Controls } from './Controls';
import { Home } from './Home';
import type { PartKind } from './kinds';
import type { ControlsSource, HomeSource } from './sources';

/** What a shell hands the parts it draws. The conversation is each shell's own surface, so it supplies it. */
export interface PartSources {
  controls: ControlsSource;
  home: HomeSource;
  conversation: () => ComponentChildren;
}

interface PartType {
  draw(sources: PartSources): ComponentChildren;
}

export const PARTS: Record<PartKind, PartType> = {
  clock: { draw: () => <Clock /> },
  home: { draw: (s) => <Home source={s.home} /> },
  controls: { draw: (s) => <Controls source={s.controls} /> },
  conversation: { draw: (s) => s.conversation() },
};

/** The part of `kind`; a kind with no part draws the conversation. */
export function drawPart(kind: string, sources: PartSources): ComponentChildren {
  const type = (PARTS as Record<string, PartType | undefined>)[kind] ?? PARTS.conversation;
  return type.draw(sources);
}
