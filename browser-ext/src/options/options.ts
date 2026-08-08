import { apiUrlFromHubUrl, customHubFromUrl } from "../core/hubs";
import { send } from "../core/messages";
import type { ProjectPublic } from "../core/types";
import { clear, el, errorMessage, loading, textInput } from "../core/ui";

const app = document.getElementById("app") as HTMLElement;

/**
 * Ask Chrome for access to a self-hosted hub's API host.
 *
 * The built-in hubs are in the manifest's host permissions, but a
 * self-hosted one can't be, so it's requested here. Clicking Use this hub is
 * the user gesture Chrome requires before it will show the prompt.
 */
async function requestApiAccess(apiUrl: string): Promise<boolean> {
  const origin = `${new URL(apiUrl).origin}/*`;
  if (await chrome.permissions.contains({ origins: [origin] })) {
    return true;
  }
  return chrome.permissions.request({ origins: [origin] });
}

/**
 * The signed-in state of the selected hub, with the action that changes it.
 *
 * Credentials are per hub, so switching hubs generally means signing in
 * again. Showing that here means the switch doesn't silently leave every
 * surface signed out with no explanation.
 */
async function renderAuth(container: HTMLElement): Promise<void> {
  clear(container).append(loading("Checking sign-in"));
  let state: Awaited<ReturnType<typeof send<"auth.state">>>;
  try {
    state = await send({ type: "auth.state" });
  } catch (e) {
    clear(container).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
    return;
  }
  clear(container);
  if (state.signedIn && state.user) {
    container.append(
      el("div", { class: "row" }, [
        el("div", { class: "grow" }, [
          el("div", { text: `Signed in to ${state.hubLabel}` }),
          el("div", { class: "dim small", text: state.user.email }),
        ]),
        el("button", {
          class: "action secondary",
          text: "Sign out",
          onClick: async () => {
            await send({ type: "auth.signOut" });
            void render();
          },
        }),
      ]),
    );
    return;
  }
  const message = el("div", { class: "small" });
  const signIn = el("button", { class: "action", text: "Sign in" });
  signIn.addEventListener("click", async () => {
    signIn.disabled = true;
    clear(message).append(
      loading("Approve the request in the tab that just opened"),
    );
    try {
      await send({ type: "auth.signIn" });
      void render();
    } catch (e) {
      signIn.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("div", { text: `Not signed in to ${state.hubLabel}` }),
        el("div", {
          class: "dim small",
          text: "Each hub has its own credentials.",
        }),
      ]),
      signIn,
    ]),
    message,
  );
}

async function renderHubSection(
  container: HTMLElement,
  hubName: string,
  customHubUrl: string,
  hubs: { name: string; label: string; apiUrl: string }[],
): Promise<void> {
  clear(container);
  const hubSelect = el("select");
  for (const hub of hubs) {
    hubSelect.append(
      el("option", { value: hub.name, text: `${hub.label} (${hub.apiUrl})` }),
    );
  }
  hubSelect.append(el("option", { value: "custom", text: "Self-hosted" }));
  hubSelect.value = hubName;
  const message = el("div", { class: "small" });
  // Selecting a hub applies it straight away. A Save button below a long
  // project list is easy to miss, and a hub that looks switched but isn't
  // is worse than no setting at all.
  hubSelect.addEventListener("change", async () => {
    if (hubSelect.value === "custom") {
      syncVisibility();
      return;
    }
    clear(message).append(loading("Switching hub"));
    try {
      await send({
        type: "settings.set",
        update: { hubName: hubSelect.value },
      });
      void render();
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  const customUrl = textInput({
    placeholder: "https://calkit.example.edu",
    value: customHubUrl,
  });
  const derived = el("div", { class: "dim small" });
  const showDerived = () => {
    const value = customUrl.value.trim();
    if (!value) {
      derived.textContent = "";
      return;
    }
    try {
      derived.textContent = `API: ${apiUrlFromHubUrl(value)}`;
      derived.classList.remove("error");
    } catch {
      derived.textContent = "That doesn't look like a hub URL.";
      derived.classList.add("error");
    }
  };
  customUrl.addEventListener("input", showDerived);
  showDerived();
  // The custom hub needs an explicit commit, since it also has to ask
  // Chrome for access to a host the manifest can't know about
  const useCustom = el("button", { class: "action", text: "Use this hub" });
  useCustom.addEventListener("click", async () => {
    useCustom.disabled = true;
    clear(message).append(loading("Switching hub"));
    try {
      const url = customUrl.value.trim();
      if (!url) {
        throw new Error("A hub URL is required");
      }
      const customHub = customHubFromUrl(url);
      if (!(await requestApiAccess(customHub.apiUrl))) {
        throw new Error(
          `Calkit needs access to ${customHub.apiUrl} to use that hub`,
        );
      }
      await send({
        type: "settings.set",
        update: { hubName: "custom", customHub },
      });
      void render();
    } catch (e) {
      useCustom.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  const customFields = el("div", { class: "stack" }, [
    el("label", { text: "Hub URL" }),
    customUrl,
    derived,
    el("div", {
      class: "dim small",
      text:
        "A hub serves its API from the api subdomain of its own host, so " +
        "its URL is all that's needed. Chrome will ask for access to that " +
        "host.",
    }),
    el("div", { class: "actions" }, [useCustom]),
  ]);
  function syncVisibility() {
    customFields.style.display = hubSelect.value === "custom" ? "" : "none";
  }
  syncVisibility();
  const authContainer = el("div");
  container.append(
    el("div", { class: "small", style: { fontWeight: "600" }, text: "Hub" }),
    el("div", {
      class: "dim small",
      text: "Every surface uses this hub. Changing it takes effect right away.",
    }),
    hubSelect,
    customFields,
    message,
    el("div", { class: "muted-box", style: { marginTop: "8px" } }, [
      authContainer,
    ]),
  );
  await renderAuth(authContainer);
}

async function renderActiveProjectSection(
  container: HTMLElement,
  selected: string | null,
): Promise<void> {
  clear(container).append(loading("Loading your projects"));
  let projects: ProjectPublic[];
  try {
    projects = (await send({ type: "projects.list", limit: 100 })).data;
  } catch (e) {
    clear(container).append(
      el("div", { class: "dim small" }, [
        document.createTextNode(
          "Sign in above to choose a project on this hub. ",
        ),
        el("span", { text: e instanceof Error ? e.message : "" }),
      ]),
    );
    return;
  }
  clear(container);
  const message = el("div", { class: "small" });
  const search = textInput({
    placeholder: "Search projects",
  });
  const list = el("div");
  const setActive = async (spec: string | null) => {
    clear(message).append(loading("Saving"));
    try {
      const updated = await send({
        type: "settings.set",
        update: { activeProject: spec },
      });
      selected = updated.activeProject;
      clear(message).append(
        el("span", {
          class: "dim",
          text: selected ? `Active project: ${selected}` : "No active project",
        }),
      );
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
    renderList();
  };
  const renderList = () => {
    const query = search.value.trim().toLowerCase();
    const matching = projects.filter((project) => {
      const spec = `${project.owner_account_name}/${project.name}`;
      return (
        !query ||
        spec.toLowerCase().includes(query) ||
        project.title.toLowerCase().includes(query)
      );
    });
    clear(list);
    if (!matching.length) {
      list.append(el("div", { class: "dim small", text: "No projects" }));
      return;
    }
    for (const project of matching) {
      const spec = `${project.owner_account_name}/${project.name}`;
      const radio = el("input", { type: "radio" });
      radio.name = "active-project";
      radio.checked = spec === selected;
      radio.style.width = "auto";
      radio.addEventListener("change", () => void setActive(spec));
      list.append(
        el("label", { class: "row", style: { fontWeight: "400" } }, [
          radio,
          el("div", { class: "grow" }, [
            el("div", { text: spec }),
            el("div", { class: "dim small", text: project.title }),
          ]),
        ]),
      );
    }
  };
  search.addEventListener("input", renderList);
  container.append(
    search,
    list,
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text: "Clear",
        onClick: () => void setActive(null),
      }),
    ]),
    message,
  );
  renderList();
}

async function render(): Promise<void> {
  clear(app).append(
    el("header", {}, [el("span", { text: "Calkit options" })]),
    el("main", {}, [loading()]),
  );
  const settings = await send({ type: "settings.get" });
  const { hubs } = await send({ type: "hubs.get" });
  clear(app).append(el("header", {}, [el("span", { text: "Calkit options" })]));
  const main = el("main", { class: "stack" });
  app.append(main);
  const hubContainer = el("div", { class: "stack" });
  const projectContainer = el("div");
  main.append(
    hubContainer,
    el("div", {
      class: "small",
      style: { fontWeight: "600", marginTop: "12px" },
      text: "Active project",
    }),
    el("div", {
      class: "dim small",
      text:
        "The project you're working on now, remembered per hub. Reference " +
        "lookups check its collections, and importing a reference defaults " +
        "to it. One at a time on purpose: a thesis-scale project stays " +
        "easier to keep reproducible when everything lands in the same " +
        "place.",
    }),
    projectContainer,
  );
  await renderHubSection(
    hubContainer,
    settings.hubName,
    settings.customHub?.webUrl ?? "",
    hubs,
  );
  await renderActiveProjectSection(projectContainer, settings.activeProject);
}

void render();
