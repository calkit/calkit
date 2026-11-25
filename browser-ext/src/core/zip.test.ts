import { deflateRawSync } from "node:zlib";
import { describe, expect, test } from "vitest";

import { getZipTexts } from "./zip";

// A zip archive of some files, each stored or deflated
function makeZip(files: [string, string, boolean][]): ArrayBuffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [path, text, deflate] of files) {
    const name = Buffer.from(path);
    const raw = Buffer.from(text);
    const data = deflate ? deflateRawSync(raw) : raw;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(deflate ? 8 : 0, 8);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(name.length, 26);
    locals.push(local, name, data);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(deflate ? 8 : 0, 10);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(raw.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += 30 + name.length + data.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  const all = Buffer.concat([...locals, directory, end]);
  return all.buffer.slice(all.byteOffset, all.byteOffset + all.length);
}

describe("getZipTexts", () => {
  test("reads the wanted files, stored or deflated", async () => {
    const zip = makeZip([
      ["main.tex", "\\section{Intro}\nText.\n".repeat(20), true],
      ["sec/a.tex", "Stored.", false],
      ["fig.png", "not text", false],
      ["sec/", "", false],
    ]);
    const texts = await getZipTexts(zip, (p) => p.endsWith(".tex"));
    expect([...texts.keys()]).toEqual(["main.tex", "sec/a.tex"]);
    expect(texts.get("main.tex")).toBe("\\section{Intro}\nText.\n".repeat(20));
    expect(texts.get("sec/a.tex")).toBe("Stored.");
    await expect(getZipTexts(new ArrayBuffer(40), () => true)).rejects.toThrow(
      "Not a zip archive",
    );
  });
});
