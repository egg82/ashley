// Beside the history on wide screens: what we're working on, and who hears what is said here.
import { Vis } from '../../components/FactParts';
import { WorkPanel } from './WorkList';

export function ConvoRail() {
  return (
    <div class="her-rail">
      <WorkPanel />
      <aside class="panel convo">
        <div class="ph"><h3>On the web</h3></div>
        <dl>
          <dt>Who hears it</dt>
          <dd><Vis v="private" /></dd>
        </dl>
      </aside>
    </div>
  );
}
