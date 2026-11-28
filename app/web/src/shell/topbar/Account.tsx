// The signed-in person, their card of what she knows about them, and their way out. A native disclosure, so keyboard and
// phone behave as the platform does.
import { useState } from 'preact/hooks';
import type { Person } from '../../api/types';
import { drawPart } from '../../components/parts/registry';
import { PERSON_SOURCES } from '../../session/parts';
import { signOut } from '../../session/session';

export function Account({ person }: { person: Person }) {
  const [failed, setFailed] = useState(false);
  const [card, setCard] = useState(false);
  const leave = () => signOut().then(() => setFailed(false), () => setFailed(true));
  return (
    <details class="me" onToggle={(e) => !(e.currentTarget as HTMLDetailsElement).open && setCard(false)}>
      <summary>
        <span class="who you sm" aria-hidden="true">{person.name.slice(0, 1).toUpperCase()}</span>
        <span class="name">{person.name}</span>
      </summary>
      <div class={`panel me-menu${card ? ' with-card' : ''}`}>
        <button class="btn sm" type="button" aria-expanded={card} onClick={() => setCard(!card)}>What she knows about you</button>
        {card && drawPart('person', PERSON_SOURCES, String(person.id))}
        <button class="btn sm" type="button" onClick={() => void leave()}>Sign out</button>
        {failed && <span class="meta">Sign-out failed. Try again.</span>}
      </div>
    </details>
  );
}
