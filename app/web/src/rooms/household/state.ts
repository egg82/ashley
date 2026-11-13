// The household as a person is editing it: one draft for the sentence, the position and the notebook, saved together.
import { effect, signal } from '@preact/signals';
import { household, householdSaid } from '../../household/household';
import { type Draft, draftOf } from './draft';

export const draft = signal<Draft | null>(null);

// Whenever the household is read or saved, the draft starts again from it; a refused save leaves the draft as typed.
effect(() => {
  const h = household.value;
  if (h) draft.value = draftOf(h);
});

export function edit(patch: Partial<Draft>): void {
  if (draft.value) draft.value = { ...draft.value, ...patch };
}

export function undo(): void {
  const h = household.value;
  if (h) draft.value = draftOf(h);
  householdSaid.value = null;
}
