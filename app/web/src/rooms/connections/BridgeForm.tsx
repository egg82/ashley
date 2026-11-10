// The login to a kind connected through Bridge (Proton): the name when the kind allows several, then the username and
// password, then the two-factor code and the mailbox password when Proton asks for them; when Proton wants to check it is a person, a link
// to its check (opened in a new tab) and the password again. Each step goes to Bridge once; what
// is typed is cleared whatever the answer and is never shown back, except the username, kept so a wrong password is retyped
// alone. A refusal stays up until the person types or sends again. Logging in again to a signed-out account keeps its name.
import { useEffect, useState } from 'preact/hooks';
import type { ConnectionKindInfo } from '../../api/types';
import {
  asking, logIn, loginSaid, resetLogin, sendCode, sendMailboxPassword, sendVerified, sending, verifyUrl,
} from './proton';
import { SAID, sentOf } from './protonSteps';

/** Typing answers what was said: the refusal goes when the person starts on the next try. */
function typing(set: (value: string) => void, value: string): void {
  loginSaid.value = null;
  set(value);
}

export function BridgeForm({ kind, again, onDone, onBack }: {
  kind: ConnectionKindInfo;
  again?: string;
  onDone: () => void;
  onBack: () => void;
}) {
  const [label, setLabel] = useState(again ?? '');
  const [username, setUsername] = useState('');
  const [secret, setSecret] = useState('');
  useEffect(() => {
    resetLogin();
    return resetLogin;
  }, []);
  const step = asking.value;
  const sent = sentOf(step, secret);
  const submit = async (e: Event) => {
    e.preventDefault();
    const named = label.trim();
    setSecret('');
    const ok = step === 'credentials' ? await logIn(named, username.trim(), sent)
      : step === 'two_factor' ? await sendCode(named, sent)
      : step === 'human_verification' ? await sendVerified(named, sent) : await sendMailboxPassword(named, sent);
    if (ok) onDone();
  };
  return (
    <form class="cn-form" onSubmit={(e) => void submit(e)}>
      {step === 'credentials' && again === undefined && kind.most > 1 && (
        <label>
          <span class="meta">Name</span>
          <input type="text" value={label} maxLength={40} placeholder="personal, work…" autocomplete="off"
            onInput={(e) => typing(setLabel, e.currentTarget.value)} />
        </label>
      )}
      {step === 'credentials' && (
        <label>
          <span class="meta">Proton username or address</span>
          <input type="text" value={username} autocomplete="off" onInput={(e) => typing(setUsername, e.currentTarget.value)} />
        </label>
      )}
      {step === 'human_verification' && verifyUrl.value && (
        <p class="cn-verify">
          Proton wants to check that you are a person. <a href={verifyUrl.value} target="_blank" rel="noopener noreferrer">Open
          Proton's check</a>, finish it there, then enter your password again.
        </p>
      )}
      <label>
        <span class="meta">{step === 'credentials' || step === 'human_verification' ? 'Proton password' : step === 'two_factor' ? 'Two-factor code' : 'Mailbox password'}</span>
        <input type="password" value={secret} autocomplete="off" inputMode={step === 'two_factor' ? 'numeric' : undefined}
          onInput={(e) => typing(setSecret, e.currentTarget.value)} />
      </label>
      {loginSaid.value && <p class="cn-refused" role="alert">{SAID[loginSaid.value]}</p>}
      <div class="dc-act">
        <button class="btn primary" type="submit" disabled={sending.value || !sent || (step === 'credentials' && !username.trim())}>
          {step === 'credentials' ? 'Log in' : 'Continue'}
        </button>
        <button class="btn ghost" type="button" onClick={onBack}>{again === undefined ? 'Back' : 'Cancel'}</button>
        {sending.value && <span class="meta">Asking Proton…</span>}
      </div>
    </form>
  );
}
