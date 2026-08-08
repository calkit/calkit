import { send } from "../core/messages";
import { clear, el, errorMessage, loading } from "../core/ui";

const app = document.getElementById("app") as HTMLElement;

async function render(): Promise<void> {
  clear(app).append(
    el("header", {}, [el("span", { text: "Calkit options" })]),
    el("main", {}, [loading()]),
  );
  const settings = await send({ type: "settings.get" });
  const { hubs, current } = await send({ type: "hubs.get" });
  clear(app).append(el("header", {}, [el("span", { text: "Calkit options" })]));
  const main = el("main", { class: "stack" });
  app.append(main);
  const message = el("div", { class: "small" });
  // Hub selection
  const hubSelect = el("select");
  for (const hub of hubs) {
    hubSelect.append(el("option", { value: hub.name, text: hub.label }));
  }
  hubSelect.append(el("option", { value: "custom", text: "Self-hosted" }));
  hubSelect.value = settings.hubName;
  const customWebUrl = el("input", {
    type: "text",
    placeholder: "https://calkit.example.org",
    value: settings.customHub?.webUrl ?? "",
    attrs: { autocomplete: "off", "data-lpignore": "true" },
  });
  const customApiUrl = el("input", {
    type: "text",
    placeholder: "https://api.calkit.example.org",
    value: settings.customHub?.apiUrl ?? "",
    attrs: { autocomplete: "off", "data-lpignore": "true" },
  });
  const customFields = el("div", { class: "stack" }, [
    el("label", { text: "Web app URL" }),
    customWebUrl,
    el("label", { text: "API URL" }),
    customApiUrl,
    el("div", {
      class: "dim small",
      text:
        "A self-hosted hub also needs its API host added to the extension's " +
        "site access, which Chrome will prompt for on the first request.",
    }),
  ]);
  const syncCustomVisibility = () => {
    customFields.style.display = hubSelect.value === "custom" ? "" : "none";
  };
  hubSelect.addEventListener("change", syncCustomVisibility);
  syncCustomVisibility();
  main.append(
    el("div", { class: "small", style: { fontWeight: "600" }, text: "Hub" }),
    el("div", {
      class: "dim small",
      text: `Currently signed in against ${current.apiUrl}.`,
    }),
    hubSelect,
    customFields,
  );
  // Watched projects
  const watched = new Set(settings.watchedProjects);
  const projectList = el("div");
  main.append(
    el("div", {
      class: "small",
      style: { fontWeight: "600", marginTop: "12px" },
      text: "Projects to check for references",
    }),
    el("div", {
      class: "dim small",
      text:
        "When you open a paper, these projects are checked to see whether " +
        "it's already in one of their collections. Each one is read on the " +
        "server, so keep the list to the projects you're actively citing in.",
    }),
    projectList,
  );
  clear(projectList).append(loading());
  try {
    const projects = await send({ type: "projects.list", limit: 100 });
    clear(projectList);
    if (!projects.data.length) {
      projectList.append(
        el("div", { class: "dim small", text: "No projects yet." }),
      );
    }
    for (const project of projects.data) {
      const spec = `${project.owner_account_name}/${project.name}`;
      const checkbox = el("input", { type: "checkbox" });
      checkbox.checked = watched.has(spec);
      checkbox.style.width = "auto";
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          watched.add(spec);
        } else {
          watched.delete(spec);
        }
      });
      projectList.append(
        el("label", { class: "row", style: { fontWeight: "400" } }, [
          checkbox,
          el("div", { class: "grow" }, [
            el("div", { text: spec }),
            el("div", { class: "dim small", text: project.title }),
          ]),
        ]),
      );
    }
  } catch (e) {
    clear(projectList).append(
      el("div", { class: "dim small" }, [
        document.createTextNode(
          "Sign in from the extension popup to choose projects. ",
        ),
        el("span", { class: "dim", text: e instanceof Error ? e.message : "" }),
      ]),
    );
  }
  const save = el("button", { class: "action", text: "Save" });
  save.addEventListener("click", async () => {
    save.disabled = true;
    clear(message).append(loading("Saving"));
    try {
      await send({
        type: "settings.set",
        update: {
          hubName: hubSelect.value,
          customHub:
            hubSelect.value === "custom"
              ? {
                  name: "custom",
                  label: new URL(customWebUrl.value.trim()).host,
                  webUrl: customWebUrl.value.trim().replace(/\/$/, ""),
                  apiUrl: customApiUrl.value.trim().replace(/\/$/, ""),
                }
              : settings.customHub,
          watchedProjects: [...watched].sort(),
        },
      });
      clear(message).append(el("span", { class: "dim", text: "Saved." }));
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    } finally {
      save.disabled = false;
    }
  });
  main.append(el("div", { class: "actions" }, [save]), message);
}

void render();
