"""Show the LaTeX/Word round trip: the PDF, its Word copy, and the PDF
built again after merging the copy back."""

import matplotlib.pyplot as plt
import pypdfium2 as pdfium
from matplotlib.patches import FancyArrowPatch

IN = "results/latex-word-round-trip"
PANELS = [
    ("original.pdf", "LaTeX (PDF)"),
    ("review.pdf", "Word (.docx)"),
    ("rebuilt.pdf", "LaTeX again (PDF)"),
]
STEPS = ["calkit latex to-docx", "calkit latex merge-docx"]


def page_image(path: str):
    # The first page, so each panel shows the same part of the paper
    return pdfium.PdfDocument(path)[0].render(scale=2).to_pil()


fig, axes = plt.subplots(1, 3, figsize=(13, 6.2))
for ax, (fname, title) in zip(axes, PANELS):
    ax.imshow(page_image(f"{IN}/{fname}"))
    ax.set_title(title, fontsize=13)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("0.6")
fig.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.02, wspace=0.18)
for left, right, label in zip(axes[:-1], axes[1:], STEPS):
    a, b = left.get_position(), right.get_position()
    y = (a.y0 + a.y1) / 2
    fig.patches.append(
        FancyArrowPatch(
            (a.x1 + 0.004, y),
            (b.x0 - 0.004, y),
            transform=fig.transFigure,
            arrowstyle="-|>",
            mutation_scale=22,
            linewidth=2,
            color="C0",
        )
    )
    fig.text(
        (a.x1 + b.x0) / 2,
        y + 0.03,
        label,
        ha="center",
        va="bottom",
        rotation=90,
        fontsize=9,
        family="monospace",
        color="C0",
    )
fig.savefig("docs/img/latex-word-round-trip.png", dpi=150)
