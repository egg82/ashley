// The household's people and who of them is an admin; an admin grants and revokes here while the app decides.
import { adminsFrom, loadPeople, mayGrant, people, peopleSaid, peopleState, setAdmin } from './people';

const SAID: Record<NonNullable<typeof peopleSaid.value>, string> = {
  admin_only: 'Only an admin can change that.',
  last_admin: 'Someone has to stay an admin. Make another person one first.',
  admins_from_provider: 'Admins are set by the sign-in provider here.',
  not_found: 'That person is not in this household any more.',
  failed: "That didn't go through. Nothing changed.",
};

function Said() {
  const s = peopleSaid.value;
  if (!s) return null;
  return (
    <div class="dc-note bad" role="alert">
      <span>{SAID[s]}</span>
      <button class="btn sm ghost" type="button" onClick={() => (peopleSaid.value = null)}>Dismiss</button>
    </div>
  );
}

function List() {
  switch (peopleState.value) {
    case 'loading':
      return <div class="devs-body"><span class="meta">Reading who lives here…</span></div>;
    case 'failed':
      return (
        <div class="devs-body">
          <span class="unk">couldn't read the people</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadPeople()}>Try again</button>
        </div>
      );
    case 'ready': {
      const grants = mayGrant();
      return (
        <>
          {people.value.map((p) => (
            <div key={p.id} class="acct-row">
              <span><b>{p.name}</b> {p.admin && <span class="pill">Admin</span>}</span>
              {grants && (
                <button class="btn sm ghost" type="button" aria-pressed={p.admin}
                  onClick={() => void setAdmin(p.id, !p.admin)}>{p.admin ? 'Remove admin' : 'Make admin'}</button>
              )}
            </div>
          ))}
        </>
      );
    }
  }
}

export function PeoplePanel() {
  return (
    <div class="panel devs">
      <div class="ph"><h3>Who lives here</h3></div>
      <List />
      <div class="dc-body">
        <Said />
        {peopleState.value === 'ready' && (
          <p class="meta">
            {adminsFrom.value === 'provider'
              ? 'Admins come from a group at the sign-in provider, and change when that person next signs in.'
              : 'An admin can change what every household here shares, like the model providers’ keys.'}
          </p>
        )}
      </div>
    </div>
  );
}
