import { getGithubRepo, getOverleafProjectId } from "../core/detect";
import { projectUrl } from "../core/hub-url";
import { RequestFailed, send } from "../core/messages";
import { clear, el, errorMessage, loading } from "../core/ui";

const app = document.getElementById("app") as HTMLElement;

/**
 * What the active tab is, as far as this extension cares.
 *
 * The reference case runs in the page rather than being read from the URL,
 * so the popup can work on any site, not only the ones the reference content
 * script is registered for.
 */
type PageContext =
  | { kind: "github"; repo: string }
  | { kind: "overleaf"; overleafProjectId: string }
  | { kind: "reference"; title: string | null; doi: string | null }
  | { kind: "other" };

async function getPageContext(): Promise<PageContext> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !tab.id) {
    return { kind: "other" };
  }
  const repo = getGithubRepo(tab.url);
  if (repo) {
    return { kind: "github", repo };
  }
  const overleafProjectId = getOverleafProjectId(tab.url);
  if (overleafProjectId) {
    return { kind: "overleaf", overleafProjectId };
  }
  // activeTab lets this read citation metadata from whatever page the user
  // is on, without the extension holding a content script for every site
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const meta = (name: string) =>
          document
            .querySelector<HTMLMetaElement>(
              `meta[name="${name}"], meta[property="${name}"]`,
            )
            ?.content?.trim() ?? null;
        return {
          title: meta("citation_title") ?? meta("dc.title"),
          doi: meta("citation_doi") ?? meta("dc.identifier"),
        };
      },
    });
    const detected = result?.result as {
      title: string | null;
      doi: string | null;
    };
    if (detected?.title || detected?.doi) {
      return { kind: "reference", title: detected.title, doi: detected.doi };
    }
  } catch {
    // Chrome refuses to inject into its own pages and the web store; those
    // simply have no context
  }
  return { kind: "other" };
}

function contextSection(context: PageContext, hubWebUrl: string): HTMLElement {
  switch (context.kind) {
    case "github":
      return el("div", { class: "muted-box stack" }, [
        el("div", { class: "small", text: "This page" }),
        el("div", { class: "name", text: context.repo }),
        el("div", {
          class: "dim small",
          text: "Open the Calkit button on the page to browse DVC artifacts.",
        }),
      ]);
    case "overleaf":
      return el("div", { class: "muted-box stack" }, [
        el("div", { class: "small", text: "This page" }),
        el("div", {
          class: "name",
          text: `Overleaf project ${context.overleafProjectId}`,
        }),
        el("div", {
          class: "dim small",
          text: "The Calkit panel on the page shows what needs syncing.",
        }),
      ]);
    case "reference":
      return el("div", { class: "muted-box stack" }, [
        el("div", { class: "small", text: "Reference on this page" }),
        el("div", { text: context.title ?? "Untitled" }),
        context.doi
          ? el("div", { class: "dim small", text: context.doi })
          : null,
      ]);
    case "other":
      return el("div", { class: "muted-box" }, [
        el("div", {
          class: "dim small",
          text:
            "Open a GitHub repo, an Overleaf project, or a paper to work " +
            "with it here.",
        }),
        el("a", { class: "small", text: "Open Calkit", href: hubWebUrl }),
      ]);
  }
}

async function renderSignedIn(
  email: string,
  hubLabel: string,
  hubWebUrl: string,
): Promise<void> {
  const context = await getPageContext();
  clear(app);
  app.append(
    el("header", {}, [
      el("span", { text: "Calkit" }),
      el("span", { class: "spacer" }),
      el("span", { class: "small", text: hubLabel }),
    ]),
  );
  const main = el("main", { class: "stack" });
  app.append(main);
  main.append(
    contextSection(context, hubWebUrl),
    el("div", {
      class: "small",
      style: { fontWeight: "600" },
      text: "Projects",
    }),
  );
  const list = el("div");
  main.append(list, loading());
  try {
    const projects = await send({ type: "projects.list", limit: 10 });
    const settings = await send({ type: "settings.get" });
    main.lastElementChild?.remove();
    clear(list);
    if (!projects.data.length) {
      list.append(el("div", { class: "dim small", text: "No projects yet." }));
    }
    for (const project of projects.data.slice(0, 8)) {
      const spec = `${project.owner_account_name}/${project.name}`;
      const isActive = spec === settings.activeProject;
      list.append(
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("a", {
              text: spec,
              href: projectUrl(
                hubWebUrl,
                project.owner_account_name,
                project.name,
              ),
            }),
            el("div", { class: "dim small", text: project.title }),
          ]),
          isActive
            ? el("span", {
                class: "badge info",
                text: "active",
                title:
                  "References are looked up and imported into this project",
              })
            : el("button", {
                class: "action secondary",
                text: "Make active",
                onClick: async () => {
                  await send({
                    type: "settings.set",
                    update: { activeProject: spec },
                  });
                  void render();
                },
              }),
        ]),
      );
    }
  } catch (e) {
    main.lastElementChild?.remove();
    clear(list).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
  main.append(
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text: "Options",
        onClick: () => void chrome.runtime.openOptionsPage(),
      }),
      el("button", {
        class: "action secondary",
        text: "Sign out",
        onClick: async () => {
          await send({ type: "auth.signOut" });
          void render();
        },
      }),
    ]),
    el("div", { class: "dim small", text: email }),
  );
}

function renderSignedOut(hubLabel: string): void {
  clear(app);
  app.append(
    el("header", {}, [
      el("span", { text: "Calkit" }),
      el("span", { class: "spacer" }),
      el("span", { class: "small", text: hubLabel }),
    ]),
  );
  const main = el("main", { class: "stack" });
  const message = el("div", { class: "small" });
  const signInButton = el("button", { class: "action", text: "Sign in" });
  signInButton.addEventListener("click", async () => {
    signInButton.disabled = true;
    clear(message).append(
      loading("Approve the request in the tab that just opened"),
    );
    try {
      await send({ type: "auth.signIn" });
      void render();
    } catch (e) {
      signInButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  main.append(
    el("div", {
      class: "dim small",
      text: "Sign in to work with your Calkit projects from this browser.",
    }),
    el("div", { class: "actions" }, [
      signInButton,
      el("button", {
        class: "action secondary",
        text: "Options",
        onClick: () => void chrome.runtime.openOptionsPage(),
      }),
    ]),
    message,
  );
  app.append(main);
}

async function render(): Promise<void> {
  clear(app).append(el("main", {}, [loading()]));
  try {
    const state = await send({ type: "auth.state" });
    if (state.signedIn && state.user) {
      await renderSignedIn(state.user.email, state.hubLabel, state.hubWebUrl);
    } else {
      renderSignedOut(state.hubLabel);
    }
  } catch (e) {
    clear(app).append(
      el("main", {}, [
        errorMessage(
          e instanceof RequestFailed || e instanceof Error
            ? e.message
            : String(e),
        ),
      ]),
    );
  }
}

void render();

// The popup closes while the sign-in tab is open, so pick up the result the
// next time it opens rather than trying to hold state across that
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    void render();
  }
});
