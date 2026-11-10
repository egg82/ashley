// The signed-in person, and their way out. A native disclosure, so keyboard and phone behave as the platform does.
import { useState } from 'preact/hooks';
import type { Person } from '../../api/types';
import { signOut } from '../../session/session';

export function Account({ person }: { person: Person }) {
  const [failed, setFailed] = useState(false);
  const leave = () => signOut().then(() => setFailed(false), () => setFailed(true));
  return (
    <details class="me">
      <summary>
        <span class="who you sm" aria-hidden="true">{person.name.slice(0, 1).toUpperCase()}</span>
        <span class="name">{person.name}</span>
      </summary>
      <div class="panel me-menu">
        <button class="btn sm" type="button" onClick={() => void leave()}>Sign out</button>
        {failed && <span class="meta">Sign-out failed. Try again.</span>}
      </div>
    </details>
  );
}
