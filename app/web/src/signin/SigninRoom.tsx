// The sign-in face, which is also the loading screen: her mark in the reticle, then a sign-in button, the loading
// lines, or why she could not be reached.
import { useLocation } from 'preact-iso';
import { signinHref } from '../api/client';
import { herWord } from '../shell/her/state';
import { load, person, status } from '../session/session';
import { LoadingLines } from './LoadingLines';
import { Reticle } from './Reticle';

/** Why the last sign-in came back refused, from the `signin` query the callback redirects with. */
function Refused({ outcome }: { outcome: string | undefined }) {
  if (outcome === 'unmapped') {
    return (
      <div class="si-note" role="status">
        <b>This account isn't linked to anyone here yet.</b>
        <span class="meta">An admin links it. Sign in again once they have.</span>
      </div>
    );
  }
  if (outcome === 'failed') {
    return (
      <div class="si-note" role="status">
        <b>Sign-in didn't work.</b>
        <span class="meta">Try again.</span>
      </div>
    );
  }
  return null;
}

function SignIn({ next, outcome }: { next: string; outcome: string | undefined }) {
  return (
    <div class="si-act">
      <Refused outcome={outcome} />
      <a class="btn primary si-btn" href={signinHref(next)}>Sign in</a>
      <div class="meta">The household sign-in. You'll come straight back.</div>
    </div>
  );
}

function Unreachable() {
  return (
    <div class="si-err" role="alert">
      <b>Can't reach Ashley.</b>
      <span class="meta">{person.value ? "Sign-in worked; she didn't answer." : "The server didn't answer."}</span>
      <button class="btn" type="button" onClick={() => void load()}>Try again</button>
    </div>
  );
}

export function SigninRoom() {
  const { path, query } = useLocation();
  const s = status.value;
  return (
    <div class="si">
      <Reticle />
      <h1 class="si-name">Ashley</h1>
      <div class={`si-word her-word${s === 'unreachable' ? ' unreachable' : ''}`}>{herWord.value}</div>
      {s === 'signed-out' && <SignIn next={path} outcome={query.signin} />}
      {s === 'signed-in' && <LoadingLines />}
      {s === 'unreachable' && <Unreachable />}
    </div>
  );
}
