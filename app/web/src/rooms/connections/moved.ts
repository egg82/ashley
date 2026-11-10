// What a refused hand-over or take-back came to, from the code the server answered with: only the person who added a
// connection takes it back (`forbidden`); the new holder may already use that label or hold as many as the kind allows.
export type MovedRefusal = 'not_yours' | 'move_label_taken' | 'move_too_many' | 'failed';

const REFUSALS: Record<string, MovedRefusal> = { forbidden: 'not_yours', label_taken: 'move_label_taken', too_many: 'move_too_many' };

export function movedRefusal(code: string | undefined): MovedRefusal {
  return (code && REFUSALS[code]) || 'failed';
}
