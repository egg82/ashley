// An image or file piece: the bytes are kept by the server and reached through a short-lived link (`piece.file.url`,
// read again before it ends, `model/bench.ts`). An image shows in place and opens full size in a tab; any file, an image
// too, is saved from its link under its own name.
import type { BenchPiece } from '../../../api/types';
import { bytesText, typeText } from '../model/size';

export function FileView({ piece }: { piece: BenchPiece }) {
  const file = piece.file;
  if (!file) return <div class="pbody"><span class="unk">not a file this page can show</span></div>;
  const facts = `${bytesText(file.size_bytes)} · ${typeText(file.media_type)}`;
  if (!file.url) {
    return <div class="pbody pfile"><span class="pfile-name">{file.name}</span><span class="meta">{facts} · can't be reached right now</span></div>;
  }
  return (
    <div class={`pbody pfile${file.image ? ' pimage' : ''}`}>
      {file.image && (
        <a class="pimage-link" href={file.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${file.name} full size`}>
          <img src={file.url} alt={file.name} loading="lazy" decoding="async" />
        </a>
      )}
      <div class="pfile-row">
        <span class="pfile-text">
          <span class="pfile-name">{file.name}</span>
          <span class="meta">{facts}</span>
        </span>
        <a class="btn sm" href={file.url} download={file.name}>Download</a>
      </div>
    </div>
  );
}
