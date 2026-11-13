// Who lives here and who of them is an admin; admins only. An admin grants and revokes here while the app decides.
import { useEffect } from 'preact/hooks';
import { person as me } from '../../session/session';
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
      const onlyAdmin = people.value.filter((p) => p.admin).length === 1;
      return (
        <>
          {people.value.map((p) => (
            <div key={p.id} class="hh-person">
              <span class={p.id === me.value?.id ? 'who you' : 'who'} aria-hidden="true">{p.name.slice(0, 1).toUpperCase()}</span>
              <span class="hh-pname"><b>{p.name}</b>{p.id === me.value?.id && <span class="meta"> you</span>}</span>
              {p.admin && <span class="pill">Admin</span>}
              {grants && !(p.admin && onlyAdmin) && (
                <button class="btn sm ghost" type="button" onClick={() => void setAdmin(p.id, !p.admin)}>
                  {p.admin ? 'Remove admin' : 'Make admin'}
                </button>
              )}
              {grants && p.admin && onlyAdmin && <span class="meta hh-last">Someone has to stay an admin</span>}
            </div>
          ))}
        </>
      );
    }
  }
}

export function PeoplePanel() {
  useEffect(() => {
    void loadPeople();
    return () => void (peopleSaid.value = null);
  }, []);
  return (
    <section class="panel hh-people" aria-labelledby="hh-people-h">
      <div class="ph"><h3 id="hh-people-h">Who lives here</h3><span class="meta hh-lex-count">admins only</span></div>
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
    </section>
  );
}
