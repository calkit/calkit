/**
 * Boxes around what's wrong with what a LaTeX document shows from its
 * project, drawn on the pages of a pdf.js viewer.
 */
import { el } from "./ui";

/** Where a problem lands in the PDF, in points from the page's top left. */
export interface PdfBox {
  page: number;
  h: number;
  v: number;
  width: number;
  height: number;
  message: string;
  line: number;
  column: number;
  /** A figure's graphics options, since SyncTeX gives its unscaled size. */
  options?: string;
  /** Where the text block starts, for a figure sized by its width. */
  textLeft?: number;
  /** A value as shown, to box it rather than its whole line. */
  text?: string;
}

/**
 * A figure's width on the page, in points, from its graphics options,
 * since SyncTeX gives the image's own size. A width relative to the text
 * assumes margins as wide on both sides.
 */
function getFigureWidth(box: PdfBox, pageWidth: number): number {
  const options = box.options ?? "";
  const pt: Record<string, number> = {
    pt: 72 / 72.27,
    bp: 1,
    in: 72,
    cm: 72 / 2.54,
    mm: 72 / 25.4,
  };
  const textWidth =
    box.textLeft !== undefined && box.textLeft <= box.h
      ? pageWidth - 2 * box.textLeft
      : box.width;
  const relative =
    /width\s*=\s*([\d.]*)\s*\\(?:textwidth|linewidth|columnwidth|hsize)/.exec(
      options,
    );
  const absolute =
    /(?:^|[,\s])(width|height)\s*=\s*([\d.]+)\s*(pt|bp|in|cm|mm)/.exec(options);
  const scale = /scale\s*=\s*([\d.]+)/.exec(options);
  let width = box.width;
  if (relative) {
    width = (relative[1] ? Number(relative[1]) : 1) * textWidth;
  } else if (absolute) {
    const length = Number(absolute[2]) * pt[absolute[3]];
    width =
      absolute[1] === "width" ? length : (box.width * length) / box.height;
  } else if (scale) {
    width = Number(scale[1]) * box.width;
  }
  // Never off the page, whatever the options say
  return Math.max(Math.min(width, pageWidth - box.h), 1);
}

/**
 * Where a value's text is in its line on a page, in points, from the text
 * layer, which can split it, e.g., at a decimal point.
 */
function findValueRect(
  page: HTMLElement,
  box: PdfBox,
  scale: number,
): { h: number; v: number; width: number; height: number } | null {
  const text = box.text;
  if (!text) {
    return null;
  }
  const origin = page.getBoundingClientRect();
  const left = origin.left + page.clientLeft;
  const top = origin.top + page.clientTop;
  // The page's text in order, and where each character came from
  let joined = "";
  const at: { node: Text; offset: number }[] = [];
  for (const span of page.querySelectorAll<HTMLElement>(".textLayer span")) {
    const node = span.firstChild;
    if (!(node instanceof Text)) {
      continue;
    }
    for (let offset = 0; offset < node.data.length; offset++) {
      joined += node.data[offset];
      at.push({ node, offset });
    }
  }
  for (let i = joined.indexOf(text); i >= 0; i = joined.indexOf(text, i + 1)) {
    const first = at[i];
    const last = at[i + text.length - 1];
    const range = document.createRange();
    range.setStart(first.node, first.offset);
    range.setEnd(last.node, last.offset + 1);
    const rect = range.getBoundingClientRect();
    const v = (rect.bottom - top) / scale;
    const height = rect.height / scale;
    // On the line the value's command is on
    if (v - height > box.v + 2 || v < box.v - box.height - 2) {
      continue;
    }
    return {
      h: (rect.left - left) / scale,
      v,
      width: rect.width / scale,
      height,
    };
  }
  return null;
}

/**
 * Put a red box around each error on the PDF's pages, with a dot beside
 * it in the margin that says what's wrong on hover and goes to it in the
 * editor on a click.
 *
 * pdf.js clears a page it redraws, e.g., on zooming, so this runs whenever
 * the viewer changes, and leaves a page alone that already has its boxes.
 * A box's ``v`` is its bottom, e.g., a figure's baseline, and its height
 * goes up from there; for a scaled figure, it's the unscaled height.
 * Works in any pdf.js viewer, e.g., Overleaf's or the one with comments.
 */
export function placePdfBoxes(
  boxes: PdfBox[],
  onClick: (box: PdfBox) => void,
): void {
  if (!document.getElementById("calkit-pdf-box-style")) {
    const style = document.createElement("style");
    style.id = "calkit-pdf-box-style";
    style.textContent = `
      .calkit-pdf-box { position: absolute; border: 2px solid #e5484d;
        border-radius: 2px; box-sizing: border-box; pointer-events: none;
        z-index: 5; }
      .calkit-pdf-tag { position: absolute; display: flex; align-items: center; gap: 4px;
        height: 16px; min-width: 16px; padding: 0 5px; box-sizing: border-box;
        border: none; border-radius: 8px; background: #e5484d; color: #fff;
        font: 700 11px/16px -apple-system, BlinkMacSystemFont, sans-serif;
        cursor: pointer; pointer-events: auto; white-space: nowrap;
        z-index: 6; }
      .calkit-pdf-tag .calkit-pdf-message { display: none; font-weight: 600; }
      .calkit-pdf-tag:hover .calkit-pdf-message { display: inline; }
    `;
    document.head.append(style);
  }
  for (const page of document.querySelectorAll<HTMLElement>(
    ".pdfViewer .page[data-page-number]",
  )) {
    const number = Number(page.dataset.pageNumber);
    const scale = parseFloat(
      getComputedStyle(page).getPropertyValue("--scale-factor"),
    );
    const wanted = Number.isFinite(scale)
      ? boxes.filter((box) => box.page === number)
      : [];
    // Values are found in the text layer, which comes after the page
    const texts = page.querySelector(".textLayer span") ? "t" : "";
    const signature = `${scale}|${texts}|${wanted
      .map((box) => [box.h, box.v, box.width, box.height].join(","))
      .join(";")}`;
    const existing = page.querySelectorAll(":scope > .calkit-pdf-box");
    if (
      existing.length === wanted.length &&
      page.dataset.calkitBoxes === signature
    ) {
      continue;
    }
    existing.forEach((node) => node.remove());
    page
      .querySelectorAll(":scope > .calkit-pdf-tag")
      .forEach((node) => node.remove());
    page.dataset.calkitBoxes = signature;
    const pageWidth = page.clientWidth / scale;
    // Dots already in the margin, by height, so ones on a line go in a row
    const dots = new Map<number, number>();
    for (const box of wanted) {
      let placed = { h: box.h, v: box.v, width: box.width, height: box.height };
      if (box.options !== undefined) {
        const width = getFigureWidth(box, pageWidth);
        placed = { ...placed, width, height: (box.height * width) / box.width };
      } else if (box.text) {
        placed = findValueRect(page, box, scale) ?? placed;
      }
      const pad = box.text ? 2 : 0;
      const tag = el(
        "button",
        {
          class: "calkit-pdf-tag",
          title: `${box.message}. Click to show it in the editor.`,
          onClick: () => onClick(box),
        },
        [
          el("span", { text: "!" }),
          el("span", { class: "calkit-pdf-message", text: box.message }),
        ],
      );
      const outline = el("div", { class: "calkit-pdf-box" });
      const top = (placed.v - placed.height - pad) * scale;
      Object.assign(outline.style, {
        left: `${(placed.h - pad) * scale}px`,
        top: `${top}px`,
        width: `${(placed.width + 2 * pad) * scale}px`,
        height: `${(placed.height + 2 * pad) * scale}px`,
      });
      // In the margin beside the line, off the text, expanding leftward
      const row = Math.round(top / 8);
      const n = dots.get(row) ?? 0;
      dots.set(row, n + 1);
      const margin = Math.min(box.textLeft ?? placed.h, placed.h) * scale;
      Object.assign(tag.style, {
        right: `calc(100% - ${margin - 6 - n * 20}px)`,
        top: `${top + Math.min(placed.height * scale, 16) / 2 - 8}px`,
      });
      // Its message opens leftward, which can go past what's shown of the
      // page, e.g., behind Overleaf's editor, so it's moved back in
      tag.addEventListener("mouseenter", () => {
        const scroller = page.closest(".pdfViewer")?.parentElement;
        const shown = Math.max(scroller?.getBoundingClientRect().left ?? 0, 0);
        const over = shown + 4 - tag.getBoundingClientRect().left;
        if (over > 0) {
          tag.style.transform = `translateX(${over}px)`;
        }
      });
      tag.addEventListener("mouseleave", () => {
        tag.style.transform = "";
      });
      page.append(outline, tag);
    }
  }
}
