import { render } from 'preact';
import { LocationProvider } from 'preact-iso';
import { Kiosk } from './kiosk/Kiosk';
import { LookPage } from './rooms/workshop/look/LookPage';
import './shell/motion';
import { Shell } from './shell/Shell';
import './styles/fonts';
import './styles/tokens.css';
import './shell/shell.css';
import './signin/signin.css';
import './rooms/rooms.css';
import './rooms/memory/memory.css';
import './rooms/devices/devices.css';
import './rooms/household/household.css';
import './rooms/connections/connections.css';
import './rooms/spend/spend.css';
import './rooms/her/chat.css';
import './rooms/workshop/workshop.css';
import './kiosk/kiosk.css';
import './highlight/highlight.css';

// /look/<token> is the page a browser pod photographs for her (`bench_look`). /kiosk is a shared screen signed in as a device, outside the person shell. Elsewhere, links under /api/ (sign-in) are
// the server's, so the client router leaves them to the browser.
const root = document.getElementById('app')!;
const look = /^\/look\/([^/]+)\/?$/.exec(location.pathname);
if (look) {
  render(<LookPage token={decodeURIComponent(look[1]!)} />, root);
} else if (/^\/kiosk\/?$/.test(location.pathname)) {
  render(<Kiosk />, root);
} else {
  render(
    <LocationProvider scope={/^\/(?!api\/)/}>
      <Shell />
    </LocationProvider>,
    root,
  );
}
