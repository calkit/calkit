/** Rows for DVC-tracked artifacts in a repo's file listings. */
import { type ContentsItemBase, type ProjectPublic } from "../core/types";
import { el, fileIcon } from "../core/ui";
import { formatSize, filesUrl, openArtifact } from "./index";

export const ARTIFACT_ROW_ATTR = "data-calkit-artifact";

/**
 * Add rows for DVC-tracked files to GitHub's own file listing.
 *
 * GitHub can only show the `.dvc` pointer files, since the artifacts
 * themselves were never committed to Git. These rows put the real files
 * back where they belong, so a figure is something you can open from the
 * repo you're already looking at.
 */
export function injectArtifactRows(
  project: ProjectPublic,
  items: ContentsItemBase[],
  hubUrl: string,
): number {
  const table =
    document.querySelector('table[aria-labelledby="folders-and-files"]') ??
    document.querySelector('[role="grid"]');
  const body = table?.querySelector("tbody") ?? table;
  if (!body) {
    return 0;
  }
  for (const stale of body.querySelectorAll(`[${ARTIFACT_ROW_ATTR}]`)) {
    stale.remove();
  }
  // Cloning one of GitHub's own rows inherits whatever classes and layout
  // it currently uses, which survives their markup changing far better
  // than rebuilding their row here would.
  const template = body.querySelector("tr");
  if (!template) {
    return 0;
  }
  const shown = new Set(
    Array.from(body.querySelectorAll("tr a[href]")).map(
      (link) => link.textContent?.trim() ?? "",
    ),
  );
  let added = 0;
  for (const item of items) {
    if (item.storage !== "dvc" && item.storage !== "dvc-zip") {
      continue;
    }
    if (shown.has(item.name)) {
      continue;
    }
    const row = template.cloneNode(true) as HTMLElement;
    row.setAttribute(ARTIFACT_ROW_ATTR, item.path);
    row.removeAttribute("id");
    // Cloning a row brings GitHub's own behaviour with it. Their hovercard
    // attributes are the visible one: left in place they pop up the
    // profile card of whoever last touched the row this was copied from.
    for (const node of [row, ...Array.from(row.querySelectorAll("*"))]) {
      for (const name of node.getAttributeNames()) {
        if (
          name.startsWith("data-hovercard") ||
          name.startsWith("data-turbo") ||
          name === "data-testid" ||
          name === "aria-describedby"
        ) {
          node.removeAttribute(name);
        }
      }
    }
    const links = Array.from(row.querySelectorAll("a"));
    if (!links.length) {
      continue;
    }
    // The first link is the filename; the rest are the latest commit and
    // other chrome that means nothing for a file Git never saw
    const nameLink = links[0];
    nameLink.textContent = item.name;
    // The cloned row's icon belongs to whatever it was cloned from, which
    // is a directory as often as not. Replacing it keeps this row's text
    // on the same line as every other row's.
    const nameCell = nameLink.closest("td") ?? nameLink.parentElement;
    for (const icon of nameCell?.querySelectorAll("svg") ?? []) {
      icon.remove();
    }
    nameLink.before(fileIcon());
    // A real href means middle-click and copy-link do something sensible,
    // and it goes where the file actually lives
    nameLink.href = filesUrl(project, item.path, hubUrl);
    nameLink.title = `${item.path} (tracked by DVC)`;
    nameLink.addEventListener("click", (event) => {
      // Let a modified click through, so opening in a new tab still works
      if (event.metaKey || event.ctrlKey || event.shiftKey) {
        return;
      }
      event.preventDefault();
      openArtifact(project, item, hubUrl);
    });
    for (const other of links.slice(1)) {
      other.remove();
    }
    for (const cell of Array.from(row.querySelectorAll("td")).slice(1)) {
      cell.textContent = "";
    }
    const badge = el("span", {
      text: formatSize(item.size) ? `DVC · ${formatSize(item.size)}` : "DVC",
    });
    Object.assign(badge.style, {
      marginLeft: "8px",
      padding: "0 6px",
      borderRadius: "999px",
      fontSize: "11px",
      fontWeight: "600",
      color: "#009688",
      border: "1px solid #009688",
      whiteSpace: "nowrap",
    });
    nameLink.after(badge);
    body.append(row);
    added += 1;
  }
  return added;
}
