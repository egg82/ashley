// The parts of the fact shape every room draws the same way: the kind notch's box and who may hear it, one ring
// closed by how few may hear. The tab itself is the `.fact` class in tokens.css.
import type { FactKind, Visibility } from '../api/types';

export const KIND_LABEL: Record<FactKind, string> = {
  preference: 'Preference', routine: 'Routine', plan: 'Plan', person: 'Person',
  health: 'Health', finance: 'Finance', diet: 'Diet', home: 'Home', other: 'Other',
};

/** The glyph in a fact's notch box, from the design's kind table. */
export const KIND_GLYPH: Record<FactKind, string> = {
  preference: 'P', routine: 'R', plan: 'L', person: 'W', health: 'H', finance: '$', diet: 'D', home: '⌂', other: 'O',
};

const RING: Record<Visibility, { label: string; marks: preact.JSX.Element }> = {
  shared: {
    label: 'Anyone',
    marks: <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.4 2" />,
  },
  discreet: {
    label: 'If asked',
    marks: (
      <>
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4" />
        <path d="M7 1.5a5.5 5.5 0 0 1 0 11z" fill="currentColor" />
      </>
    ),
  },
  members: {
    label: 'Household, in private',
    marks: (
      <>
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4" />
        <circle cx="4.9" cy="7" r="1.5" fill="currentColor" />
        <circle cx="9.1" cy="7" r="1.5" fill="currentColor" />
      </>
    ),
  },
  private: {
    label: 'Only you',
    marks: (
      <>
        <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6" />
        <circle cx="7" cy="7" r="2.4" fill="currentColor" />
      </>
    ),
  },
};

export function Vis({ v }: { v: Visibility }) {
  const ring = RING[v];
  return (
    <span class="vis" title="Who can hear it">
      <svg viewBox="0 0 14 14" aria-hidden="true">{ring.marks}</svg>
      {ring.label}
    </span>
  );
}

/** The kind's glyph box; `named` adds the kind's word beside it, as cards show it. */
export function Kind({ kind, named }: { kind: FactKind; named: boolean }) {
  return (
    <span class="kind" aria-label={named ? undefined : KIND_LABEL[kind]}>
      <i aria-hidden={named}>{KIND_GLYPH[kind]}</i>
      {named && KIND_LABEL[kind]}
    </span>
  );
}
