// Written by Calkit; changes are overwritten when the pipeline compiles.
(() => {
  const base = document.currentScript
    ? document.currentScript.src.replace(/[^/]*$/, "")
    : "";
  let loading = null;
  // Mermaid, loaded the first time a view with a graph opens, unless the
  // page already has it
  function loadMermaid() {
    if (window.mermaid) {
      return Promise.resolve(window.mermaid);
    }
    if (!loading) {
      loading = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = base + "mermaid.min.js";
        script.onload = () => {
          window.mermaid.initialize({ startOnLoad: false });
          resolve(window.mermaid);
        };
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }
    return loading;
  }
  async function draw(root) {
    const pres = root.querySelectorAll("pre.ck-mermaid:not([data-drawn])");
    if (pres.length === 0) {
      return;
    }
    let mermaid;
    try {
      mermaid = await loadMermaid();
    } catch {
      // Left as its source, e.g., in a page with everything embedded
      return;
    }
    for (const pre of pres) {
      pre.dataset.drawn = "true";
      const id = "ck-mermaid-" + Math.random().toString(36).slice(2);
      const { svg } = await mermaid.render(id, pre.textContent);
      pre.innerHTML = svg;
    }
  }
  document.addEventListener("toggle", (event) => {
    const el = event.target;
    if (el.open || event.newState === "open") {
      draw(el);
    }
  }, true);
  function addButtons() {
    const spans = document.querySelectorAll("span.ck-value[data-ck-popover]");
    for (const span of spans) {
      if (span.closest("a, h1, h2, h3, h4, h5, h6, nav, .title, summary")) {
        continue;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = span.className;
      button.title = span.title;
      button.setAttribute("popovertarget", span.dataset.ckPopover);
      button.setAttribute("aria-label", span.dataset.ckLabel);
      button.append(...span.childNodes);
      span.replaceWith(button);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", addButtons);
  } else {
    addButtons();
  }
})();
