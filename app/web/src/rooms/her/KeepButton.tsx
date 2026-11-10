/** Asks her to remember the line; shown while it may be asked. Dragging the line to Memory does the same. */
export function KeepButton({ remember }: { remember: () => void }) {
  return (
    <button class="keep" type="button" title="Or drag the line to Memory" onClick={remember}>
      Remember
    </button>
  );
}
