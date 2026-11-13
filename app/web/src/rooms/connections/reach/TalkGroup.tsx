// The accounts she talks to the person through: Discord (which can be unlinked) and the sign-in account (which is only named).
import { accounts as linked, unlink } from '../accounts';
import { Avatar } from './Avatar';

const SYSTEM: Record<string, string> = { oidc: 'OIDC', home_assistant: 'Home Assistant', discord: 'Discord' };

export function hasTalk(): boolean {
  return linked.value.length > 0;
}

export function TalkGroup() {
  return (
    <section class="rr-group" id="g-talk">
      <h2 class="rr-head">Talking to her</h2>
      {linked.value.map((a) => {
        const name = SYSTEM[a.system] ?? a.system;
        return (
          <article class="rr" key={a.id}>
            <Avatar kind={a.system} title={name} />
            <div class="rr-body">
              <p class="rr-sentence">{a.system === 'discord' ? <>She answers your messages on <b>Discord</b></> : <>You sign in with <b>{name}</b></>}</p>
              {a.handle && <span class="rr-addr">@{a.handle}</span>}
              <div class="rr-meta meta">{a.system === 'discord' ? 'only you see your DMs with her' : (a.handle ?? 'linked by an admin')}</div>
            </div>
            {a.unlinkable && <button class="rr-manage" type="button" onClick={() => void unlink(a.id)}>Unlink</button>}
          </article>
        );
      })}
    </section>
  );
}
