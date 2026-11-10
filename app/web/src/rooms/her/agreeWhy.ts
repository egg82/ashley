// What a refused Agree tells the person, by the refusal's code; anything else is a failure to reach her.
const REFUSED: Record<string, string> = {
  gone: 'Nothing is waiting for your OK any more.',
  expired: 'That was held too long ago to agree to now.',
  not_yours: 'That was not held for you.',
};

export function whyNotAgreed(status: number | undefined, code: string | undefined): string {
  if (status === 409 && code !== undefined && code in REFUSED) return REFUSED[code]!;
  return "That didn't go through. Try again.";
}
