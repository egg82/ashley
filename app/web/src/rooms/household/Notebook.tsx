// What she always knows about the household, as a ruled page with a pen line that fills toward the most it holds.
import { locale } from '../../household/format';
import { household } from '../../household/household';
import { penOf } from './pen';
import { draft, edit } from './state';

export function Notebook() {
  const d = draft.value;
  const h = household.value;
  if (!d || !h) return null;
  const pen = penOf(d.profile.length, h.profile_limit);
  const count = (n: number) => n.toLocaleString(locale());
  return (
    <div class="panel hh-notebook">
      <div class="ph"><h3>What she knows about the household</h3></div>
      <div class="dc-body">
        <textarea class="hh-page" aria-label="What she always knows about the household" value={d.profile} maxLength={h.profile_limit}
          rows={10} placeholder="Who lives here, their pronouns, the pets, what the calendars and lists are called"
          onInput={(e) => edit({ profile: e.currentTarget.value })} />
        <div class="hh-pen">
          <div class={pen.near ? 'hh-track near' : 'hh-track'}>
            <i style={{ width: `${pen.fraction * 100}%` }} />
          </div>
          <span class={pen.near ? 'meta near' : 'meta'}>{count(d.profile.length)} of {count(h.profile_limit)}</span>
        </div>
      </div>
    </div>
  );
}
