// Agree, in the held receipt beside her answer: one tap carries out what was held, with no model asked. What became of
// each call shows beside the person's "Agreed." line once the conversation is read back; a refusal is said here, where
// the button was.
import { useState } from 'preact/hooks';
import { agreeTo } from '../../api/agree';
import { ApiError } from '../../api/client';
import { load as reloadSession } from '../../session/session';
import { whyNotAgreed } from './agreeWhy';
import { refresh } from './chat';

export function AgreeButton({ proposal }: { proposal: number }) {
  const [state, setState] = useState<{ working: boolean; why: string | null }>({ working: false, why: null });
  const agree = async () => {
    setState({ working: true, why: null });
    try {
      await agreeTo({ proposal_id: proposal });
      await refresh();
    } catch (error) {
      const status = error instanceof ApiError ? error.status : undefined;
      if (status === 401) void reloadSession();
      setState({ working: false, why: whyNotAgreed(status, error instanceof ApiError ? error.code : undefined) });
      if (status === 409) void refresh();
    }
  };
  return (
    <div class="agree">
      <button class="agree-btn" type="button" disabled={state.working} onClick={() => void agree()}>
        {state.working ? 'Agreeing…' : 'Agree'}
      </button>
      {state.why && <span class="m-err" role="alert">{state.why}</span>}
    </div>
  );
}
