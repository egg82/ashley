// "What she uses this for": one switch per port the connection's kind declares, on unless you switch it off.
import { Row } from './Row';
import { flipped, portLines } from './ports';
import { draft, edit, settings } from './state';
import { Switch } from './Switch';

export function PortsSection() {
  const lines = portLines(settings.value?.settings ?? [], draft.value);
  if (lines.length === 0) return null;
  return (
    <section class="panel cn-set">
      <div class="cn-set-head"><h2>What she uses this for</h2></div>
      <p class="cn-blurb">Switch off what you don’t want her to use this connection for. She then treats it as if it didn’t offer that.</p>
      <ul class="set-rows">
        {lines.map((l) => (
          <Row key={l.port} name={l.name} sub={l.sub}>
            <Switch label="She uses it for this" checked={l.on} onChange={() => edit(flipped(draft.value, l.port))} />
          </Row>
        ))}
      </ul>
    </section>
  );
}
