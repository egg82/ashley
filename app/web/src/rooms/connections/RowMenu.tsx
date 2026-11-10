// The ⋯ on a row: a few actions in a small menu that closes on a pick, Escape or a press elsewhere.
import { useEffect, useRef, useState } from 'preact/hooks';

export interface RowAction {
  label: string;
  onPick: () => void;
}

export function RowMenu({ label, actions }: { label: string; actions: readonly RowAction[] }) {
  const [open, setOpen] = useState(false);
  const here = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => {
      if (!here.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  return (
    <div class="cn-menu" ref={here}>
      <button class="btn sm ghost cn-more" type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen(!open)}>⋯</button>
      {open && (
        <div class="cn-pop" role="menu">
          {actions.map((a) => (
            <button key={a.label} type="button" role="menuitem"
              onClick={() => { setOpen(false); a.onPick(); }}>{a.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}
