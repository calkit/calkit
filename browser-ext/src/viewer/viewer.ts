import { send } from "../core/messages";
import { clear, el, errorMessage, loading } from "../core/ui";

const app = document.getElementById("app") as HTMLElement;

/**
 * A page for looking at a DVC-tracked artifact.
 *
 * This exists because the panel can't do it. A panel lives in the host
 * page's DOM, so that page's content security policy decides what it may
 * embed, and GitHub's forbids the frames and objects a PDF or a notebook
 * needs. An extension page carries its own policy, so the artifact can
 * simply be rendered.
 */
type Kind = "image" | "pdf" | "html" | "text" | "plotly" | "other";

function kindFor(path: string): Kind {
  if (/\.(png|jpe?g|gif|webp|svg)$/i.test(path)) {
    return "image";
  }
  if (/\.pdf$/i.test(path)) {
    return "pdf";
  }
  if (/\.html?$/i.test(path)) {
    return "html";
  }
  if (/\.json$/i.test(path)) {
    return "plotly";
  }
  if (/\.(txt|md|csv|tsv|ya?ml|log)$/i.test(path)) {
    return "text";
  }
  return "other";
}

async function render(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  const url = params.get("url");
  const path = params.get("path") ?? "artifact";
  const hubFileUrl = params.get("hubUrl");
  const name = path.split("/").pop() ?? path;
  document.title = `${name} · Calkit`;
  clear(app).append(
    el("header", {}, [
      el("span", { text: name }),
      el("span", { class: "spacer" }),
      hubFileUrl
        ? el("a", {
            class: "small",
            text: "Open in Calkit",
            href: hubFileUrl,
            style: { color: "#ffffff" },
          })
        : null,
    ]),
  );
  const main = el("main", { class: "stack" });
  app.append(main);
  main.append(el("div", { class: "dim small", text: path }));
  if (!url) {
    main.append(
      errorMessage("No artifact URL was given. Open this from the panel."),
    );
    return;
  }
  const kind = kindFor(path);
  if (kind === "plotly") {
    // Rendering a Plotly figure means shipping Plotly, which is larger
    // than this whole extension. The hub already renders them.
    main.append(
      el("div", {
        class: "dim small",
        text:
          "Plotly figures are rendered on the hub, which already has the " +
          "library for it.",
      }),
      el("div", { class: "actions" }, [
        hubFileUrl
          ? el("a", {
              class: "small",
              text: "View on Calkit",
              href: hubFileUrl,
            })
          : null,
        el("a", { class: "small", text: "Download", href: url }),
      ]),
    );
    return;
  }
  const status = el("div", { class: "small" });
  main.append(status);
  clear(status).append(loading("Fetching the artifact"));
  let dataUrl: string;
  try {
    // Fetched through the service worker, which holds the storage host
    // permission; this page has no business fetching object storage itself
    dataUrl = await send({ type: "content.dataUrl", url });
  } catch (e) {
    clear(status).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
      el("div", { class: "actions" }, [
        el("a", { class: "small", text: "Download instead", href: url }),
      ]),
    );
    return;
  }
  status.remove();
  if (kind === "image") {
    const image = el("img", { style: { maxWidth: "100%" } });
    image.src = dataUrl;
    main.append(image);
    return;
  }
  if (kind === "text") {
    const text = atob(dataUrl.slice(dataUrl.indexOf(",") + 1));
    main.append(
      el("pre", {
        text,
        style: {
          whiteSpace: "pre-wrap",
          overflowX: "auto",
          fontSize: "12px",
        },
      }),
    );
    return;
  }
  // A PDF gets Chrome's own viewer; notebook HTML is sandboxed, so
  // whatever it contains can't reach this page or the extension
  const frame = el("iframe", {
    style: {
      width: "100%",
      height: "80vh",
      border: "1px solid var(--ck-border)",
      borderRadius: "6px",
    },
  });
  if (kind === "html") {
    frame.setAttribute("sandbox", "");
  }
  frame.src = dataUrl;
  main.append(frame);
}

void render();
