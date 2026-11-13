// The glance's calendar: today's and tomorrow's events, title and time. Unknown renders as unknown, and a quiet day says so.
import { ofDay, whenOf, type AgendaEvent } from './agenda.ts';

const DAYS = [['today', 'Today'], ['tomorrow', 'Tomorrow']] as const;

/** `events` is null when the calendars could not be read now. */
export function Agenda({ events }: { events: readonly AgendaEvent[] | null | undefined }) {
  if (events == null) return <span class="unk">unknown</span>;
  if (!events.length) return <span class="k-none">Nothing today or tomorrow</span>;
  return (
    <div class="k-agenda">
      {DAYS.map(([day, name]) => {
        const rows = ofDay(events, day);
        return rows.length > 0 && (
          <section key={day} class="k-day" aria-label={name}>
            <h3 class="label">{name}</h3>
            <ul>
              {rows.map((e, i) => (
                <li key={`${i}-${e.title}`}><time class="k-when">{whenOf(e.time)}</time><span class="k-what">{e.title}</span></li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
