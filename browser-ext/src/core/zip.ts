/**
 * Reading files from a zip archive, e.g., an Overleaf project's download,
 * with the browser's own inflater, so no library is needed for it.
 */

/** The text of each file in a zip archive whose path is wanted. */
export async function getZipTexts(
  data: ArrayBuffer,
  wanted: (path: string) => boolean,
): Promise<Map<string, string>> {
  const view = new DataView(data);
  const bytes = new Uint8Array(data);
  // The end of central directory record is in the last 64 KB, after
  // which there's only its comment
  let end = -1;
  for (
    let i = data.byteLength - 22;
    i >= Math.max(0, data.byteLength - 65557);
    i--
  ) {
    if (view.getUint32(i, true) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) {
    throw new Error("Not a zip archive");
  }
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const decoder = new TextDecoder();
  const texts = new Map<string, string>();
  for (let n = 0; n < count; n++) {
    if (view.getUint32(at, true) !== 0x02014b50) {
      throw new Error("Corrupt zip archive");
    }
    const method = view.getUint16(at + 10, true);
    const size = view.getUint32(at + 20, true);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    const local = view.getUint32(at + 42, true);
    const path = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength));
    at += 46 + nameLength + extraLength + commentLength;
    if (path.endsWith("/") || !wanted(path)) {
      continue;
    }
    const start =
      local +
      30 +
      view.getUint16(local + 26, true) +
      view.getUint16(local + 28, true);
    const raw = bytes.subarray(start, start + size);
    if (method === 0) {
      texts.set(path, decoder.decode(raw));
    } else if (method === 8) {
      const stream = new Response(raw).body?.pipeThrough(
        new DecompressionStream("deflate-raw"),
      );
      texts.set(path, await new Response(stream).text());
    }
  }
  return texts;
}
