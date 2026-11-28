// The parts a shell arranges, by kind: a Type Object table, the kind's data rather than a class per kind. A shell keeps
// its own grid and arrangement and draws each placed kind through `drawPart`; a part brought up beside her words is
// drawn the same way, with the `ref` her turn named it by (`BroughtUp`).
import type { ComponentChildren } from 'preact';
import { Attention } from './Attention';
import { Clock } from './Clock';
import { Controls } from './Controls';
import { Home } from './Home';
import type { PartKind } from './kinds';
import { Printer } from './Printer';
import { printerView } from './printerView';
import type { AttentionSource, ControlsSource, HomeSource, PrinterSource } from './sources';

/** What a shell hands the parts it draws. The conversation is each shell's own surface, so it supplies it. */
export interface PartSources {
  controls: ControlsSource;
  home: HomeSource;
  attention: AttentionSource;
  printer: PrinterSource;
  conversation: () => ComponentChildren;
}

interface PartType {
  draw(sources: PartSources, ref?: string): ComponentChildren;
  /** The words of the chip a brought-up part folds to; a part that is never brought up has none. */
  chip?(sources: PartSources, ref: string): string;
}

export const PARTS: Record<PartKind, PartType> = {
  clock: { draw: () => <Clock /> },
  home: { draw: (s) => <Home source={s.home} /> },
  controls: { draw: (s) => <Controls source={s.controls} /> },
  attention: { draw: (s) => <Attention source={s.attention} /> },
  printer: {
    draw: (s, ref) => <Printer source={s.printer} printerId={ref ?? ''} />,
    chip: (s, ref) => {
      const name = printerView(s.printer.printers.value, ref).name;
      return name ? `Printer · ${name}` : 'Printer';
    },
  },
  conversation: { draw: (s) => s.conversation() },
};

function typeOf(kind: string): PartType {
  return (PARTS as Record<string, PartType | undefined>)[kind] ?? PARTS.conversation;
}

/** The part of `kind`, showing `ref` when it names one; a kind with no part draws the conversation. */
export function drawPart(kind: string, sources: PartSources, ref?: string): ComponentChildren {
  return typeOf(kind).draw(sources, ref);
}

/** The chip a brought-up part of `kind` folds to; its kind alone when the part names no chip. */
export function chipOf(kind: string, sources: PartSources, ref: string): string {
  return typeOf(kind).chip?.(sources, ref) ?? kind;
}
