import assert from "node:assert/strict";
import test from "node:test";
import {
  getClash,
  getClashMessage,
  getCommitMessageSuggestion,
  getContinueArgs,
  getOverleafRow,
  isSyncedWithOverleaf,
  parseOverleafStatus,
  quoteShellArg,
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

test("getOverleafRow says what a sync would do", () => {
  const status = {
    path: "paper",
    overleaf_url: "https://www.overleaf.com/project/abc",
    commits_from_overleaf: 0,
    files_to_push: [],
    files_to_delete: [],
    in_sync: true,
  };
  const state = { checking: false };
  assert.deepEqual(getOverleafRow(status, state), {
    icon: "cloud",
    description: "in sync",
    tooltip: "https://www.overleaf.com/project/abc",
    needsSync: false,
  });
  // A coauthor's edits on Overleaf come first, since they're pulled first
  const both = {
    ...status,
    commits_from_overleaf: 2,
    files_to_push: [
      {
        path: "figures/a.png",
        project_path: "paper/figures/a.png",
        state: "modified" as const,
      },
    ],
    files_to_delete: [
      {
        path: "old.tex",
        project_path: "paper/old.tex",
        state: "new" as const,
      },
    ],
    in_sync: false,
  };
  const row = getOverleafRow(both, state);
  assert.equal(row.icon, "cloud-download");
  assert.equal(row.description, "2 changes on Overleaf, 2 files to push");
  assert.match(row.tooltip, /paper\/figures\/a\.png \(modified\)/);
  assert.match(row.tooltip, /paper\/old\.tex \(deleted\)/);
  assert.ok(row.needsSync);
  assert.equal(
    getOverleafRow({ ...both, commits_from_overleaf: 0 }, state).icon,
    "cloud-upload",
  );
  assert.equal(getOverleafRow(both, { checking: true }).icon, "sync~spin");
  assert.equal(
    getOverleafRow(status, { checking: false, conflict: "paper" }).description,
    "conflict",
  );
  // Only for the folder whose sync stopped on it
  assert.equal(
    getOverleafRow(status, { checking: false, conflict: "slides" }).description,
    "in sync",
  );
});

test("parseOverleafStatus reads statuses and errors", () => {
  assert.deepEqual(parseOverleafStatus('Pulling\n{"statuses": []}\n'), {
    statuses: [],
    checking: false,
  });
  assert.deepEqual(
    parseOverleafStatus('{"error": "No credentials", "needs_login": true}'),
    { checking: false, error: "No credentials", needsLogin: true },
  );
  assert.equal(
    parseOverleafStatus("Traceback").error,
    "Couldn't check Overleaf",
  );
});

test("getCommitMessageSuggestion names the one file changed", () => {
  assert.equal(
    getCommitMessageSuggestion(" M fit_rates.ipynb\0"),
    "Update fit_rates.ipynb",
  );
  assert.equal(
    getCommitMessageSuggestion("?? scripts/new.py\0 M .gitignore\0"),
    "Add scripts/new.py",
  );
  assert.equal(
    getCommitMessageSuggestion("A  data/raw.csv\0"),
    "Add data/raw.csv",
  );
  assert.equal(getCommitMessageSuggestion("R  b.py\0a.py\0"), "Update b.py");
  assert.equal(getCommitMessageSuggestion(" M a.py\0 M b.py\0"), undefined);
  assert.equal(getCommitMessageSuggestion(""), undefined);
});

test("quoteShellArg keeps an argument whole in common shells", () => {
  assert.equal(quoteShellArg("run"), "run");
  assert.equal(quoteShellArg("/Users/me/my proj"), "'/Users/me/my proj'");
  assert.equal(quoteShellArg("Fit $k$ again"), "'Fit $k$ again'");
  assert.equal(quoteShellArg("Fix Pete's figure"), '"Fix Pete\'s figure"');
  assert.equal(quoteShellArg("Fix 'decay' plot"), "\"Fix 'decay' plot\"");
  assert.equal(quoteShellArg("Fit Pete's $k$"), "'Fit Pete\u2019s $k$'");
  assert.equal(quoteShellArg("C:\\Users\\me"), "'C:\\Users\\me'");
});
