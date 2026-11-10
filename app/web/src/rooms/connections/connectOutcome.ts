// Where a consent screen's callback sent the browser back to, as `?connect=<outcome>` names it.
export type ConnectOutcome = 'connected' | 'cancelled' | 'wrong_person' | 'refused' | 'label_taken' | 'too_many' | 'unavailable' | 'failed';
const OUTCOMES: readonly ConnectOutcome[] = ['connected', 'cancelled', 'wrong_person', 'refused', 'label_taken', 'too_many', 'unavailable', 'failed'];

export function connectOutcomeOf(raw: string | undefined): ConnectOutcome | null {
  return OUTCOMES.find((o) => o === raw) ?? null;
}
