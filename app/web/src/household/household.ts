// The signed-in person's household as last read, and what the last save came to. Reading or saving it also sets how
// every page writes dates, times and numbers (`format.ts`).
import { signal } from '@preact/signals';
import { getHousehold, putHousehold } from '../api/household';
import type { Household, HouseholdRefused, HouseholdRequest } from '../api/types';
import { writing } from './format';

export type HouseholdLoad = 'loading' | 'ready' | 'failed';

export const household = signal<Household | null>(null);
export const householdState = signal<HouseholdLoad>('loading');
/** What the last save came to; null when there is nothing to say. */
export const householdSaid = signal<HouseholdRefused['invalid'] | 'saved' | 'failed' | null>(null);
export const householdSaving = signal(false);

function hold(found: Household): void {
  household.value = found;
  writing.value = { locale: found.locale, clock: found.clock };
}

export async function loadHousehold(): Promise<void> {
  householdState.value = 'loading';
  try {
    hold(await getHousehold());
    householdState.value = 'ready';
  } catch {
    householdState.value = 'failed';
  }
}

/** Saves every field; whether it was stored. */
export async function saveHousehold(body: HouseholdRequest): Promise<boolean> {
  householdSaid.value = null;
  householdSaving.value = true;
  try {
    const got = await putHousehold(body);
    if ('invalid' in got) {
      householdSaid.value = got.invalid;
      return false;
    }
    hold(got);
    householdSaid.value = 'saved';
    return true;
  } catch {
    householdSaid.value = 'failed';
    return false;
  } finally {
    householdSaving.value = false;
  }
}
