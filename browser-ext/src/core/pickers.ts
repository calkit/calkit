import { RequestFailed, send } from "./messages";
import { clear, el, errorMessage, loading, textInput } from "./ui";

/**
 * The hub every panel talks to, changeable without leaving the page.
 *
 * Switching hubs used to mean opening the options page, which is a long
 * way to go while looking at a paper or a repo. Changing it here changes
 * it extension-wide, since one hub at a time is the model everywhere.
 *
 * A self-hosted hub can only be *added* from the options page: Chrome
 * only prompts for access to a new host from an extension page, never
 * from a script running in someone's tab. One already configured there
 * shows up as an option here.
 */
export async function renderHubPicker(
  onChange: () => void,
): Promise<HTMLElement> {
  const select = el("select");
  const message = el("div", { class: "small" });
  const container = el("div", {}, [
    el("label", { text: "Hub" }),
    select,
    message,
  ]);
  let hubs;
  let settings;
  try {
    [hubs, settings] = await Promise.all([
      send({ type: "hubs.get" }),
      send({ type: "settings.get" }),
    ]);
  } catch (e) {
    clear(container).append(
      el("label", { text: "Hub" }),
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
    return container;
  }
  // calkit.io is where projects live unless someone has gone out of
  // their way, so it leads and the rest are grouped away from it
  const primary = hubs.hubs.find((hub) => hub.name === "production");
  if (primary) {
    select.append(
      el("option", { value: primary.name, text: `${primary.label} (default)` }),
    );
  }
  const others = el("optgroup", { attrs: { label: "Other instances" } });
  for (const hub of hubs.hubs) {
    if (hub.name === "production") {
      continue;
    }
    others.append(el("option", { value: hub.name, text: hub.label }));
  }
  if (others.childElementCount) {
    select.append(others);
  }
  select.value = settings.hubName;
  select.addEventListener("change", async () => {
    clear(message).append(loading("Switching hub"));
    try {
      await send({
        type: "settings.set",
        update: { hubName: select.value },
      });
      onChange();
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  return container;
}

/**
 * The active project, chosen by typing rather than scrolling a list.
 *
 * The hub matches on name, title, and description, so typing part of
 * either finds the project. Picking one sets the extension-wide active
 * project, since that is what every surface here works against.
 */
export async function renderProjectPicker(options: {
  activeProject: string | null;
  onChange: () => void;
}): Promise<HTMLElement> {
  const input = textInput({
    value: options.activeProject ?? "",
    placeholder: "Type to search your projects",
  });
  const results = el("div", {
    class: "stack",
    style: { display: "none", marginTop: "4px" },
  });
  // Focusable, so clicking a row's text doesn't count as leaving the list
  results.tabIndex = -1;
  results.style.outline = "none";
  const message = el("div", { class: "small" });
  const container = el("div", {}, [
    el("label", { text: "Active project" }),
    input,
    results,
    message,
  ]);
  // Leaving the list without picking keeps the active project as it was
  const close = () => {
    clearTimeout(timer);
    results.style.display = "none";
    input.value = options.activeProject ?? "";
  };
  const cancelRow = () =>
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text: "Cancel",
        onClick: close,
      }),
    ]);
  const choose = async (spec: string) => {
    input.value = spec;
    results.style.display = "none";
    clear(message).append(loading("Switching project"));
    try {
      await send({ type: "settings.set", update: { activeProject: spec } });
      options.onChange();
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  const search = async () => {
    const query = input.value.trim();
    results.style.display = "";
    clear(results).append(loading());
    try {
      const projects = await send({
        type: "projects.list",
        // A project already chosen fills the input, and would otherwise
        // match only itself the moment the list opens
        searchFor: query && query !== options.activeProject ? query : undefined,
        limit: 10,
      });
      clear(results);
      if (!projects.data.length) {
        results.append(
          el("div", { class: "dim small", text: "No matching projects" }),
          cancelRow(),
        );
        return;
      }
      for (const project of projects.data) {
        const spec = `${project.owner_account_name}/${project.name}`;
        results.append(
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [
              el("div", { class: "small", text: spec }),
              el("div", { class: "dim small", text: project.title }),
            ]),
            el("button", {
              class: "action secondary",
              text: spec === options.activeProject ? "Active" : "Use",
              disabled: spec === options.activeProject,
              onClick: () => void choose(spec),
            }),
          ]),
        );
      }
      results.append(cancelRow());
    } catch (e) {
      clear(results).append(
        renderFailure(e, { onSignedIn: options.onChange }),
        cancelRow(),
      );
    }
  };
  let timer: ReturnType<typeof setTimeout> | undefined;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => void search(), 250);
  });
  input.addEventListener("focus", () => {
    if (results.style.display === "none") {
      void search();
    }
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      close();
      input.blur();
    }
  });
  // Clicking anywhere outside the picker closes it too
  container.addEventListener("focusout", (e) => {
    const next = e.relatedTarget;
    if (
      results.style.display !== "none" &&
      !(next instanceof Node && container.contains(next))
    ) {
      close();
    }
  });
  return container;
}

/**
 * Render a failure as something the user can act on.
 *
 * A request that failed only because this hub has no credentials is not
 * an error to report, it's a sign-in that hasn't happened yet. Panels
 * span several hubs now, so the prompt names the one it means and signs
 * in to that one without changing the default.
 */
export function renderFailure(
  error: unknown,
  options: { hubUrl?: string; onSignedIn: () => void },
): HTMLElement {
  const notSignedIn = error instanceof RequestFailed && error.notSignedIn;
  if (!notSignedIn) {
    return errorMessage(error instanceof Error ? error.message : String(error));
  }
  const label = options.hubUrl
    ? options.hubUrl.replace(/^https?:\/\//, "").replace(/\/+$/, "")
    : undefined;
  const message = el("div", { class: "small" });
  const container = el("div", { class: "stack" }, [
    el("div", {
      class: "dim small",
      text: label ? `Not signed in to ${label}.` : "Not signed in to this hub.",
    }),
  ]);
  const button = el("button", {
    class: "action",
    text: label ? `Sign in to ${label}` : "Sign in",
  });
  button.addEventListener("click", async () => {
    button.disabled = true;
    clear(message).append(
      loading("Approve the request in the tab that just opened"),
    );
    try {
      await send({ type: "auth.signIn", hubUrl: options.hubUrl });
      options.onSignedIn();
    } catch (e) {
      button.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("div", { class: "actions" }, [button]),
    // The approval page is also where an account gets made, which nothing
    // here said, so someone new had no reason to click
    el("div", { class: "dim small" }, [
      document.createTextNode(
        "New to Calkit? Sign in with GitHub to create an account. ",
      ),
      el("a", {
        text: "Need a GitHub account?",
        href: "https://github.com/signup",
      }),
    ]),
    message,
  );
  // Signing in is per hub, so a signed-out panel is also a panel with no
  // way back: picking the wrong hub used to mean opening the options
  // page to get out of it. Appended once it loads, so nothing waits.
  void renderHubPicker(options.onSignedIn).then((picker) =>
    container.append(picker),
  );
  return container;
}

/**
 * How well a path matches what was typed, higher being better, or null if
 * the characters don't all appear in order.
 *
 * Mirrors the hub's PathPicker: runs of consecutive characters, matches
 * early on, and matches in the file name rather than its folder count most.
 */
export function pathScore(query: string, path: string): number | null {
  const q = query.toLowerCase().replace(/\s+/g, "");
  const t = path.toLowerCase();
  const nameStart = t.lastIndexOf("/") + 1;
  let qi = 0;
  let score = 0;
  let prev = -1;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] !== q[qi]) {
      continue;
    }
    score += 10 + (ti === prev + 1 ? 8 : 0) + (ti >= nameStart ? 4 : 0);
    score -= ti * 0.05;
    prev = ti;
    qi++;
  }
  return qi === q.length ? score : null;
}

/** The folders and files directly in a folder, from every path there is. */
export function listDir(
  paths: string[],
  dir: string,
): { dirs: string[]; files: string[] } {
  const prefix = dir ? `${dir}/` : "";
  const dirs = new Set<string>();
  const files: string[] = [];
  for (const path of paths) {
    if (!path.startsWith(prefix)) {
      continue;
    }
    const rest = path.slice(prefix.length);
    const slash = rest.indexOf("/");
    if (slash === -1) {
      files.push(path);
    } else {
      dirs.add(prefix + rest.slice(0, slash));
    }
  }
  return { dirs: [...dirs].sort(), files: files.sort() };
}

/**
 * A file in a project, found by typing part of its name or by browsing
 * its folders, as on the hub. Anything else typed is kept as written,
 * e.g., where an uploaded file should go.
 */
export function renderPathPicker(options: {
  owner: string;
  project: string;
  placeholder?: string;
  /** Which files can be picked; folders without any are left out. */
  accept?: (path: string) => boolean;
}): { element: HTMLElement; input: HTMLInputElement } {
  const input = textInput({ placeholder: options.placeholder });
  const results = el("div", {
    class: "stack picks",
    style: { display: "none", marginTop: "4px" },
  });
  results.tabIndex = -1;
  results.style.outline = "none";
  const container = el("div", {}, [input, results]);
  let all: Promise<string[]> | null = null;
  let dir = "";
  // Whether what's in the input was typed, so it's searched, rather than
  // picked, so its folder is browsed
  let typed = false;
  const accept = options.accept ?? (() => true);
  const pick = (text: string, onClick: () => void, title?: string) =>
    el("button", { class: "pick name", text, title, onClick });
  const render = async () => {
    results.style.display = "";
    clear(results).append(loading());
    all ??= send({
      type: "project.contentPaths",
      owner: options.owner,
      project: options.project,
    });
    let paths: string[];
    try {
      paths = (await all).filter(accept);
    } catch (e) {
      all = null;
      clear(results).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      return;
    }
    clear(results);
    const query = input.value.trim();
    if (typed && query) {
      const matches = paths
        .map((path) => ({ path, score: pathScore(query, path) }))
        .filter((m): m is { path: string; score: number } => m.score !== null)
        .sort((a, b) => b.score - a.score)
        .slice(0, 20);
      results.append(
        ...(matches.length
          ? matches.map(({ path }) => pick(path, () => choose(path)))
          : [el("div", { class: "dim small", text: "No matching files" })]),
      );
      return;
    }
    const { dirs, files } = listDir(paths, dir);
    if (dir) {
      const up = dir.includes("/") ? dir.slice(0, dir.lastIndexOf("/")) : "";
      results.append(pick(`← ${dir}/`, () => browse(up), "Up a folder"));
    }
    const shown = [...dirs, ...files];
    results.append(
      ...shown.slice(0, 50).map((path) => {
        const name = path.slice(dir ? dir.length + 1 : 0);
        return dirs.includes(path)
          ? pick(`${name}/`, () => browse(path))
          : pick(name, () => choose(path), path);
      }),
    );
    if (shown.length > 50) {
      results.append(
        el("div", {
          class: "dim small",
          text: `And ${shown.length - 50} more; type to search`,
        }),
      );
    }
    if (!shown.length) {
      results.append(el("div", { class: "dim small", text: "Nothing here" }));
    }
  };
  const browse = (to: string) => {
    dir = to;
    typed = false;
    void render();
  };
  const choose = (path: string) => {
    input.value = path;
    typed = false;
    results.style.display = "none";
    input.dispatchEvent(new Event("change"));
  };
  let timer: ReturnType<typeof setTimeout> | undefined;
  input.addEventListener("input", () => {
    typed = true;
    clearTimeout(timer);
    timer = setTimeout(() => void render(), 100);
  });
  input.addEventListener("focus", () => {
    if (results.style.display === "none") {
      const value = input.value.trim();
      dir = value.includes("/") ? value.slice(0, value.lastIndexOf("/")) : "";
      void render();
    }
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      results.style.display = "none";
      input.blur();
    }
  });
  container.addEventListener("focusout", (e) => {
    const next = e.relatedTarget;
    if (!(next instanceof Node && container.contains(next))) {
      results.style.display = "none";
    }
  });
  return { element: container, input };
}
