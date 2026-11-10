// What a person pasted with a message, folded under it: closed it says what it is and how long; open it shows the text
// as pasted, in a block that scrolls. Native <details>, so it opens from the keyboard.
import type { ChatAttachment } from '../../api/types';
import { charCount } from './limit';

export function Paste({ attachment }: { attachment: ChatAttachment }) {
  const label = attachment.title ?? 'Pasted text';
  return (
    <details class="paste">
      <summary>
        <span class="paste-name">{label}</span>
        <span class="paste-size">{charCount(attachment.text).toLocaleString('en-US')} characters</span>
      </summary>
      <pre class="paste-pre" tabIndex={0}>{attachment.text}</pre>
    </details>
  );
}
