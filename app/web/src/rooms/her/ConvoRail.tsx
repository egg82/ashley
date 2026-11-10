// Beside the history on wide screens: who hears what is said here.
import { Vis } from '../../components/FactParts';

export function ConvoRail() {
  return (
    <aside class="panel convo">
      <div class="ph"><h3>On the web</h3></div>
      <dl>
        <dt>Who hears it</dt>
        <dd><Vis v="private" /></dd>
      </dl>
    </aside>
  );
}
