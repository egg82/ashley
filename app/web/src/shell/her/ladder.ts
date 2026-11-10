// What her mark shows, from the facts `state.ts` gathers: the first rule that holds wins.
import type { MarkState } from '../../components/AshleyMark.tsx';

export interface Facts {
  unreachable: boolean;
  checking: boolean;
  hearing: 'listening' | 'transcribing' | null;
  speaking: boolean;
  liveSpeaking: boolean;
  asked: number;
  remembering: number;
  /** The shown conversation has a turn she is still working on (`ChatConversationTurn.working`). */
  working: boolean;
  liveThinking: boolean;
  liveListening: boolean;
}

export function markState(f: Facts): MarkState {
  if (f.unreachable) return 'unreachable';
  if (f.checking) return 'thinking';
  if (f.hearing === 'listening') return 'listening';
  if (f.speaking || f.liveSpeaking) return 'speaking';
  if (f.asked > 0 || f.remembering > 0 || f.hearing || f.working || f.liveThinking) return 'thinking';
  if (f.liveListening) return 'listening';
  return 'idle';
}
