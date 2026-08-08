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
  if (settings.customHub) {
    others.append(
      el("option", { value: "custom", text: settings.customHub.label }),
    );
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
  const message = el("div", { class: "small" });
  const container = el("div", {}, [
    el("label", { text: "Active project" }),
    input,
    results,
    message,
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
    } catch (e) {
      clear(results).append(renderFailure(e, { onSignedIn: options.onChange }));
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
  container.append(el("div", { class: "actions" }, [button]), message);
  return container;
}
