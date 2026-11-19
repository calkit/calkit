import assert from "node:assert/strict";
import test from "node:test";
import {
  getClash,
  getClashMessage,
  getContinueArgs,
  isSyncedWithOverleaf,
} from "../overleaf/core";

test("isSyncedWithOverleaf reads calkit.yaml and the sync info", () => {
  assert.equal(isSyncedWithOverleaf(undefined, false), false);
  assert.equal(isSyncedWithOverleaf({}, true), true);
  assert.equal(
    isSyncedWithOverleaf(
      { overleaf_sync: { paper: { url: "x" } } } as never,
      false,
    ),
    true,
  );
  assert.equal(
    isSyncedWithOverleaf({ overleaf_sync: {} } as never, false),
    false,
  );
  // The legacy place, on a publication
  assert.equal(
    isSyncedWithOverleaf(
      { publications: [{ path: "paper/main.pdf", overleaf: { id: "x" } }] },
      false,
    ),
    true,
  );
  assert.equal(
    isSyncedWithOverleaf({ publications: [{ path: "a.pdf" }] }, false),
    false,
  );
});

test("getClash and its message say what to combine and how to go on", () => {
  assert.equal(
    getClash({ overleafConflict: false, merging: false, unmerged: [] }),
    null,
  );
  const overleaf = getClash({
    overleafConflict: true,
    merging: false,
    unmerged: ["paper/main.tex"],
  });
  assert.deepEqual(overleaf, { kind: "overleaf", files: ["paper/main.tex"] });
  assert.equal(
    getClashMessage(overleaf!),
    "paper/main.tex changed on Overleaf and on this machine. " +
      "Select what to keep in each marked part, then select Continue.",
  );
  assert.deepEqual(getContinueArgs(overleaf!), [
    "overleaf",
    "sync",
    "--resolve",
  ]);
  const merge = getClash({
    overleafConflict: false,
    merging: true,
    unmerged: ["a.py", "b.py", "c.py", "d.py", "e.py"],
  });
  assert.equal(
    getClashMessage(merge!, "git@github.com:me/project.git"),
    "a.py, b.py, c.py, and 2 more changed on GitHub and on this machine. " +
      "Select what to keep in each marked part, then select Continue.",
  );
  assert.match(
    getClashMessage(merge!, "/srv/project.git"),
    /on the project's remote and/,
  );
  assert.deepEqual(getContinueArgs(merge!), ["merge", "--continue"]);
  // Everything combined, with the merge still to finish
  assert.equal(
    getClashMessage({ kind: "merge", files: [] }, "https://github.com/a/b"),
    "Changes from GitHub are combined. Select Continue to finish.",
  );
});
