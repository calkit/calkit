"""
Conceptual flowchart model and command reference for calkit version control.
Generates a fixed 4-row x 3-column grid with minimal-overlap floating-layout arrows via Graphviz neato.
Then overlays dashed rectangles and row/column title font with raw SVG XML.
Node positions are calculated from row/column indices.
Edit CONNECTIONS to change arrows.

Install:
    pip install graphviz

Also install the Graphviz system application (i.e. via conda) and ensure `neato` is on PATH.

Run:
    python generate_version_control_diagram.py

"""

import xml.etree.ElementTree as ET

from graphviz import Digraph

# ------------------------- Grid configuration -------------------------

ROWS = 4
COLS = 3

ROW_LABELS = ["REMOTE", "CACHE", "STAGED", "WORKSPACE"]
ROW_COLORS = ["red", "orange", "green", "blue"]
COL_LABELS = ["GIT", "DVC", "DOCKER"]
COLUMN_NAMES = ["A", "B", "C"]

# Distances between node centers, in Graphviz points (72 points = 1 inch).
COLUMN_SPACING = 250
ROW_SPACING = 150

# Rectangle dimensions, in inches.
BOX_WIDTH = 1.5
BOX_HEIGHT = 0.6

DPI = 72
COLUMN_GAP = COLUMN_SPACING - DPI * BOX_WIDTH
ROW_GAP = ROW_SPACING - DPI * BOX_HEIGHT

# Outline rectangle dimensions, in points
X_RECT_MARGIN = 0.1 * COLUMN_GAP
Y_RECT_MARGIN = 0.2 * ROW_GAP
OUTLINE_WIDTH = (
    COLS * BOX_WIDTH * DPI + (COLS - 1) * COLUMN_GAP + 2 * X_RECT_MARGIN
)
OUTLINE_HEIGHT = BOX_HEIGHT * DPI + 2 * Y_RECT_MARGIN


# Each connection is (source node, target node, label).
CONNECTIONS = [
    # GIT
    ("GIT.REMOTE", "GIT.CACHE", "git fetch"),
    ("GIT.CACHE", "GIT.REMOTE", "git push / calkit push --no-dvc --no-docker"),
    ("GIT.REMOTE", "GIT.WORKSPACE", "git pull / calkit pull --no-dvc"),
    ("GIT.CACHE", "GIT.WORKSPACE", "git checkout"),
    ("GIT.WORKSPACE", "GIT.STAGED", "git add"),
    ("GIT.STAGED", "GIT.CACHE", "git commit"),
    # DVC
    ("DVC.REMOTE", "DVC.CACHE", "calkit dvc fetch"),
    (
        "DVC.CACHE",
        "DVC.REMOTE",
        "calkit dvc push / calkit push --no-git --no-docker",
    ),
    ("DVC.REMOTE", "DVC.WORKSPACE", "calkit dvc pull / calkit pull --no-git"),
    ("DVC.CACHE", "DVC.WORKSPACE", "calkit dvc checkout"),
    ("DVC.WORKSPACE", "DVC.STAGED", "calkit dvc add --no-commit"),
    (
        "DVC.WORKSPACE",
        "DVC.STAGED",
        "Automatic: dvc repro --no-commit / run --no-commit",
    ),
    (
        "DVC.WORKSPACE",
        "DVC.STAGED",
        "calkit dvc add / automatic pipeline caching",
    ),
    ("DVC.STAGED", "DVC.CACHE", "calkit dvc commit"),
    # DOCKER
    ("DOCKER.CACHE", "DOCKER.REMOTE", "calkit push --no-git --no-dvc"),
    (
        "DOCKER.REMOTE",
        "DOCKER.WORKSPACE",
        "calkit update docker-env --lock / calkit check envs",
    ),
    ("DOCKER.WORKSPACE", "DOCKER.STAGED", "calkit check envs"),
]

OUTPUT_NAME = "docs/img/version_control_command_flowchart"
OUTPUT_FORMAT = "svg"


def get_edges():
    source_types, target_types, labels = zip(*CONNECTIONS)

    def split_fcn(x):
        return x.split(".")

    source_col_types, source_row_types = map(
        list, zip(*tuple(map(split_fcn, source_types)))
    )
    target_col_types, target_row_types = map(
        list, zip(*tuple(map(split_fcn, target_types)))
    )

    source_rows = [str(ROW_LABELS.index(t) + 1) for t in source_row_types]
    target_rows = [str(ROW_LABELS.index(t) + 1) for t in target_row_types]
    source_cols = [
        COLUMN_NAMES[idx]
        for idx in [COL_LABELS.index(t) for t in source_col_types]
    ]
    target_cols = [
        COLUMN_NAMES[idx]
        for idx in [COL_LABELS.index(t) for t in target_col_types]
    ]
    sources = [c + r for r, c in zip(source_rows, source_cols)]
    targets = [c + r for r, c in zip(target_rows, target_cols)]

    ports = [get_port(int(s[1]), int(t[1])) for s, t in zip(sources, targets)]
    source_ports, target_ports = zip(*ports)
    edges = zip(sources, source_ports, targets, target_ports, labels)
    return edges


def get_port(source_node, target_node):
    if source_node < target_node:
        dir = "down"
    elif source_node > target_node:
        dir = "up"
    else:
        raise ValueError("nodes cannot be at the same level")

    if abs(source_node - target_node) == 1:
        direct = True
    else:
        direct = False

    if dir == "down" and direct:
        source_port = "s"
        target_port = "n"
    elif dir == "up" and direct:
        source_port = "n"
        target_port = "s"
    elif dir == "down" and not direct:
        source_port = "se"
        target_port = "ne"
    elif dir == "up" and not direct:
        source_port = "nw"
        target_port = "sw"
    else:
        raise ValueError("invalid combination of direction and directness")

    return source_port, target_port


def node_name(column: int, row: int) -> str:
    """Return a node name such as A1 or D3 (zero-based indices)."""
    return f"{COLUMN_NAMES[column]}{row + 1}"


def node_label(column: int, row: int) -> str:
    """Return a node label string (zero-based indices)."""
    match column:
        case 0:  # git
            match row:
                case 0:
                    str = "GitHub"  # A1
                case 1:
                    str = "Git index"  # A2
                case 2:
                    str = "Staging area"  # A3
                case 3:
                    str = "Local files"  # A4
                case _:
                    str = ""
        case 1:  # dvc
            match row:
                case 0:
                    str = "ck remote"  # B1
                case 1:
                    str = "Cache in .dvc/cache"  # B2
                case 2:
                    str = "dvc.lock, <data>.dvc"  # B3
                case 3:
                    str = "data files"  # B4
                case _:
                    str = ""
        case 2:  # docker
            match row:
                case 0:
                    str = "ghcr.io registry"  # C1
                case 1:
                    str = "Docker images"  # C2
                case 2:
                    str = "Docker build cache"  # C3
                case 3:
                    str = ".calkit/env-locks/"  # C4
                case _:
                    str = ""
        case _:
            str = ""
    return str


def make_diagram() -> Digraph:
    graph = Digraph("fixed_grid", engine="neato", format=OUTPUT_FORMAT)

    # -n2 tells neato to retain the supplied node positions and calculate
    # routes for edges that do not already have explicit edge positions.
    graph.graph_attr.update(
        splines="true",
        overlap="true",
        notranslate="true",
        outputorder="edgesfirst",
        margin=".05",
        pad="1",
    )

    graph.node_attr.update(
        shape="box",
        fixedsize="true",
        width=str(BOX_WIDTH),
        height=str(BOX_HEIGHT),
        pin="true",
        fontsize="11",
        fontname="Arial",
    )

    graph.edge_attr.update(
        color="black",
        penwidth="1",
        arrowsize="0.7",
        arrowhead="normal",
        fontsize="11",
        fontname="Courier",  # monospace font for code commands
    )

    # Coordinates are the centers of the rectangles, in points, because
    # neato's -n/-n2 mode expects point coordinates.
    for col in range(COLS):
        for row in range(ROWS):
            name = node_name(col, row)
            label = node_label(col, row)
            x = col * COLUMN_SPACING
            y = (ROWS - 1 - row) * ROW_SPACING
            graph.node(name, label=label, pos=f"{x},{y}!")

    # Connect named compass ports. neato computes the spline routing.
    for source, source_port, target, target_port, label in get_edges():
        graph.edge(
            f"{source}:{source_port}",
            f"{target}:{target_port}",
            label=label,
        )

    return graph


def make_rect(topleft_x, topleft_y, color) -> ET.Element:
    rect = ET.Element(
        "{" + ns + "}" + "rect",
        {
            "x": str(topleft_x),
            "y": str(topleft_y),
            "width": str(OUTLINE_WIDTH),
            "height": str(OUTLINE_HEIGHT),
            "fill": "none",
            "stroke": color,
            "stroke-width": "2",
            "stroke-dasharray": "6,3",
        },
    )
    return rect


def make_text(
    center_x: float, center_y: float, label: str, color
) -> ET.Element:
    text = ET.Element(
        "{" + ns + "}" + "text",
        {
            "x": str(center_x),
            "y": str(center_y),
            "text-anchor": "middle",
            "dominant-baseline": "middle",
            "font-family": "Arial",
            "font-weight": "bold",
            "font-size": "14",
            "fill": color,
        },
    )
    text.text = label
    return text


if __name__ == "__main__":
    diagram = make_diagram()

    # neato_no_op=2 invokes neato -n2:
    # preserve the given node positions and route edges automatically.
    svg_data = diagram.pipe(
        format=OUTPUT_FORMAT,
        neato_no_op=2,
    )

    # Parse SVG
    root = ET.fromstring(svg_data)

    # SVG namespace
    ns = "http://www.w3.org/2000/svg"
    ns_dict = {"svg": ns}

    # Get coords of A1 top left, since svg origin doesn't line up with graph nodes.
    # X increases to the right, Y increases down (not up).
    graph = root.find(".//svg:g[@class='graph']", ns_dict)
    transform = graph.get("transform")
    translate_str = transform.split("translate(", 1)[1].split(")", 1)[0]
    translate = tuple(map(float, translate_str.split(" ")))

    for node in root.findall(".//svg:g[@class='node']", ns_dict):
        title = node.find("svg:title", ns_dict)

        if title is not None and title.text == node_name(0, 0):
            polygon = node.find("svg:polygon", ns_dict)
            points = polygon.get("points")

            coords = [tuple(map(float, p.split(","))) for p in points.split()]

            xs = [p[0] + translate[0] for p in coords]
            ys = [p[1] + translate[1] for p in coords]

            A1_topleft_x = min(xs)
            A1_topleft_y = min(ys)

    # Calculate coordinates for rectangle outline
    rect_topleft_xs = [A1_topleft_x - X_RECT_MARGIN for _ in range(ROWS)]
    rect_topleft_ys = [
        A1_topleft_y - Y_RECT_MARGIN + row * ROW_SPACING for row in range(ROWS)
    ]

    # Create rectangles
    rects = [
        make_rect(rect_x, rect_y, row_color)
        for rect_x, rect_y, row_color in zip(
            rect_topleft_xs, rect_topleft_ys, ROW_COLORS
        )
    ]

    # Calculate coordinates for row and col header text
    col_text_xs = [
        A1_topleft_x + BOX_WIDTH * DPI / 2 + col * COLUMN_SPACING
        for col in range(COLS)
    ]
    col_text_ys = [A1_topleft_y - 2 * Y_RECT_MARGIN for _ in range(COLS)]
    row_text_xs = [A1_topleft_x - 5 * X_RECT_MARGIN for _ in range(ROWS)]
    row_text_ys = [
        A1_topleft_y + BOX_HEIGHT * DPI / 2 + row * ROW_SPACING
        for row in range(ROWS)
    ]

    row_texts = [
        make_text(row_x, row_y, txt, row_color)
        for row_x, row_y, txt, row_color in zip(
            row_text_xs, row_text_ys, ROW_LABELS, ROW_COLORS
        )
    ]
    col_texts = [
        make_text(col_x, col_y, txt, "black")
        for col_x, col_y, txt in zip(col_text_xs, col_text_ys, COL_LABELS)
    ]

    # Insert as last SVG elements (foreground)
    root.extend(rects + row_texts + col_texts)

    # Save
    output_path = f"{OUTPUT_NAME}.{OUTPUT_FORMAT}"
    ET.ElementTree(root).write(
        output_path,
        encoding="unicode",
        xml_declaration=True,
    )

    print(f"Wrote {output_path}")
