// Who is home, from the glance. Unknown renders as unknown: no names when presence cannot tell.
import { glance } from './state';

/** The names, or "unknown" when presence cannot say, or "Nobody home". */
export function HomeNames({ names }: { names: readonly string[] | null | undefined }) {
  if (names == null) return <span class="unk">unknown</span>;
  if (!names.length) return <span class="k-none">Nobody home</span>;
  return (
    <span class="k-people">
      {names.map((n) => (
        <span key={n} class="pill k-person"><span class="who sm" aria-hidden="true">{n.slice(0, 1)}</span>{n}</span>
      ))}
    </span>
  );
}

/** The home piece of a laid-out screen. */
export function Home() {
  return (
    <section class="k-home" aria-label="Who is home">
      <h2 class="label">Home</h2>
      <HomeNames names={glance.value?.home} />
    </section>
  );
}
