/** The Calkit card on a pull request, with its diffs. */
import { send } from "../core/messages";
import { isDiffableDocument, latexDiffPath } from "../core/latex";
import { renderFailure } from "../core/pickers";
import {
  type DvcOutput,
  type ProjectPublic,
  type PullRequestRefs,
} from "../core/types";
import { clear, el, STYLES, loading } from "../core/ui";
import { LATEX_DIFF_DIR, openOverlay, describeOutput } from "./index";

const PR_CARD_ID = "calkit-pr-card";
/**
 * What a pull request does to the project's DVC-tracked outputs.
 *
 * A diff on GitHub shows the `.dvc` pointer changing, which says an
 * output changed but nothing about how. Reading the project at both refs
 * gives the actual files, so a new or regenerated figure can be looked at
 * next to the one it replaces.
 */
interface PullRequestChanges {
  refs: PullRequestRefs;
  changed: {
    item: DvcOutput;
    before: DvcOutput | undefined;
    /** What the project's own latexdiff stage built, when it has one. */
    latexDiff: DvcOutput | undefined;
  }[];
}

// The last pull request read, so opening the panel shows what the card in
// the conversation already fetched instead of asking again
let pullChanges: { key: string; promise: Promise<PullRequestChanges> } | null =
  null;

export function readPullRequest(
  project: ProjectPublic,
  hubUrl: string,
  number: number,
): Promise<PullRequestChanges> {
  const key = `${project.owner_account_name}/${project.name}#${number}`;
  if (pullChanges?.key !== key) {
    pullChanges = { key, promise: fetchPullRequest(project, hubUrl, number) };
  }
  return pullChanges.promise;
}

async function fetchPullRequest(
  project: ProjectPublic,
  hubUrl: string,
  number: number,
): Promise<PullRequestChanges> {
  const refs = await send({
    type: "github.pullRequest",
    owner: project.owner_account_name,
    project: project.name,
    number,
    hubUrl,
  });
  // Every output at a ref in one call, each carrying that version's own
  // presigned URL. Listing the tree a directory at a time would miss
  // anything nested, which is where outputs usually live, and would have
  // no URL to view the artifact with.
  const read = async (ref: string) => {
    const outputs = await send({
      type: "project.dvcOutputs",
      owner: project.owner_account_name,
      project: project.name,
      ref,
      hubUrl,
    });
    return new Map(outputs.map((item) => [item.path, item]));
  };
  const [head, base] = await Promise.all([
    read(refs.head_sha),
    read(refs.base_sha),
  ]);
  const latexDiffFor = (item: DvcOutput): DvcOutput | undefined => {
    if (!isDiffableDocument(item.path)) {
      return undefined;
    }
    // A `latex` stage with the base branch in its `diffs` builds this and
    // pushes it like any other output, so it's already in the list
    const diff = head.get(latexDiffPath(refs.base_ref, item.path));
    return diff?.url ? diff : undefined;
  };
  const changed = [...head.values()]
    .filter((item) => !item.path.startsWith(LATEX_DIFF_DIR))
    .filter((item) => {
      const before = base.get(item.path);
      if (!before) {
        return true;
      }
      // Equal content hashes mean the same file, whatever the pointer
      // commit says. Size only stands in where a hash is missing, and it
      // can't tell a same-size edit from no edit at all.
      return before.md5 && item.md5
        ? before.md5 !== item.md5
        : before.size !== item.size;
    })
    .map((item) => ({
      item,
      before: base.get(item.path),
      latexDiff: latexDiffFor(item),
    }));
  return { refs, changed };
}

/**
 * What a pull request does to the project's DVC-tracked outputs.
 *
 * A diff on GitHub shows the `.dvc` pointer changing, which says an
 * output changed but nothing about how. Reading the project at both refs
 * gives the actual files, so a new or regenerated figure can be looked at
 * next to the one it replaces.
 */
export async function renderPullRequest(
  body: HTMLElement,
  project: ProjectPublic,
  hubUrl: string,
  number: number,
): Promise<void> {
  clear(body).append(loading("Comparing DVC outputs"));
  let refs: PullRequestRefs;
  let changed: PullRequestChanges["changed"];
  try {
    ({ refs, changed } = await readPullRequest(project, hubUrl, number));
  } catch (e) {
    clear(body).append(renderFailure(e, { onSignedIn: () => undefined }));
    return;
  }
  clear(body).append(
    el("div", { class: "dim small" }, [
      document.createTextNode(
        `Comparing DVC outputs in #${number}: ` +
          `${refs.head_ref} against ${refs.base_ref}.`,
      ),
    ]),
  );
  if (!changed.length) {
    body.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "8px" },
        text: "No DVC-tracked outputs changed on this branch.",
      }),
    );
    return;
  }
  // The card in the conversation is where these belong; the panel keeps
  // the same list so there's still a way in when GitHub's markup defeats
  // us
  if (document.getElementById(PR_CARD_ID)) {
    body.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "4px" },
        text: "Also shown at the bottom of the conversation.",
      }),
    );
  }
  const diffRefs = { base: refs.base_sha, head: refs.head_sha };
  for (const { item, before, latexDiff } of changed) {
    const versions = [
      { label: refs.head_ref, item },
      ...(before ? [{ label: refs.base_ref, item: before }] : []),
    ];
    body.append(
      el("div", { class: "row" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "name", text: item.path }),
          el("div", {
            class: "dim small",
            text:
              (before
                ? `changed \u00b7 ${describeOutput(item)}`
                : `new \u00b7 ${describeOutput(item)}`) +
              (latexDiff ? " \u00b7 LaTeX diff" : ""),
          }),
        ]),
        el("button", {
          class: "action secondary",
          text: diffButtonLabel(before, latexDiff),
          disabled: !item.url,
          title: item.url
            ? undefined
            : "This version hasn't been pushed to storage yet",
          onClick: () =>
            openOverlay(project, hubUrl, versions, {
              refs: diffRefs,
              latexDiff,
            }),
        }),
      ]),
    );
  }
}

/**
 * What the one button on a row says, which is what the overlay will open
 * on: the project's own LaTeX diff if it built one, the two versions side
 * by side if there's something to compare against, else just the file.
 */
function diffButtonLabel(
  before: DvcOutput | undefined,
  latexDiff: DvcOutput | undefined,
): string {
  if (latexDiff) {
    return "View changes";
  }
  return before ? "Compare" : "View";
}

/**
 * Show an artifact over the page it was opened from.
 *
 * A pull request is read on GitHub, so the figure or paper it changes is
 * worth seeing without leaving it. The versions are the same artifact at
 * each ref, so switching between them is switching branches.
 */
/**
 * Put the changed outputs into the pull request itself.
 *
 * A pull request is read in the middle of the page, so a panel in the
 * corner is the wrong place for the one thing reviewers can't see from
 * the diff: the figures and papers a `.dvc` pointer stands in for. This
 * card goes at the end of the conversation, where the diff would have
 * shown them.
 */
export function injectPullRequestCard(
  project: ProjectPublic,
  hubUrl: string,
  refs: PullRequestRefs,
  changed: PullRequestChanges["changed"],
): boolean {
  document.getElementById(PR_CARD_ID)?.remove();
  if (!changed.length) {
    return false;
  }
  // GitHub rewrites this page's markup often, so this tries the hooks that
  // have lasted longest and gives up rather than guessing. Losing the card
  // is no worse than not having one -- the panel still lists everything.
  const comments = document.querySelectorAll<HTMLElement>(
    '[id^="issuecomment-"]',
  );
  const anchor =
    document.querySelector<HTMLElement>(".js-discussion") ??
    document.querySelector<HTMLElement>("#discussion_bucket") ??
    comments[comments.length - 1]?.parentElement ??
    null;
  if (!anchor) {
    return false;
  }
  const diffRefs = { base: refs.base_sha, head: refs.head_sha };
  const host = el("div", { attrs: { id: PR_CARD_ID } });
  host.style.margin = "16px 0";
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = STYLES;
  const body = el("div", { class: "body" });
  for (const { item, before, latexDiff } of changed) {
    const versions = [
      { label: refs.head_ref, item },
      ...(before ? [{ label: refs.base_ref, item: before }] : []),
    ];
    body.append(
      el("div", { class: "row" }, [
        el("div", { class: "grow" }, [
          el("div", { class: "name", text: item.path }),
          el("div", {
            class: "dim small",
            text:
              `${before ? "changed" : "new"} \u00b7 ${describeOutput(item)}` +
              (latexDiff ? " \u00b7 LaTeX diff" : ""),
          }),
        ]),
        el("button", {
          class: "action secondary",
          text: diffButtonLabel(before, latexDiff),
          disabled: !item.url,
          title: item.url
            ? undefined
            : "This version hasn't been pushed to storage yet",
          onClick: () =>
            openOverlay(project, hubUrl, versions, {
              refs: diffRefs,
              latexDiff,
            }),
        }),
      ]),
    );
  }
  root.append(
    style,
    el("div", { class: "panel" }, [
      el("div", { class: "header" }, [
        el("span", {
          text: `Calkit \u00b7 ${changed.length} DVC-tracked output${
            changed.length === 1 ? "" : "s"
          } changed`,
        }),
      ]),
      body,
    ]),
  );
  anchor.append(host);
  return true;
}

/** Remove the PR card, and forget the PR's changes, e.g., once stale. */
export function removePullRequestCard(): void {
  document.getElementById(PR_CARD_ID)?.remove();
  pullChanges = null;
}
