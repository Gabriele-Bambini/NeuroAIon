"""Publication-quality risk-of-bias figures (matplotlib, Agg backend).

Two Cochrane / RevMan-style outputs:

* ``build_rob_traffic_figure``  — the "traffic-light" plot: a grid with one row
  per study and one column per domain (plus an Overall column), each cell a
  coloured circle carrying a symbol (+ low, − some concerns, × high).
* ``build_rob_summary_figure``  — the "weighted bar" plot: one horizontal
  stacked bar per domain showing the percentage of studies at each risk level.

Colours match the journal palette used elsewhere in the project (the values are
copied, not imported, to keep this module decoupled from ``figures.py``). The
aesthetic is restrained: thin spines, small fonts, white circle edges, 150 DPI,
vector PDF.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# Journal palette (kept in sync with figures.ROB_FILL by value, not import).
ROB_FILL = {"low": "#2e7d32", "some concerns": "#f9a825", "high": "#c62828"}
ROB_SYMBOL = {"low": "+", "some concerns": "−", "high": "×"}  # + − ×
ROB_SYMBOL_COLOR = {"low": "white", "some concerns": "#3a2f00", "high": "white"}
_LEVELS = ["low", "some concerns", "high"]
_LABEL = {"low": "Low risk", "some concerns": "Some concerns", "high": "High risk"}


def _norm_level(j: str) -> str:
    j = (j or "").strip().lower()
    if j in ROB_FILL:
        return j
    if j in ("unclear", "moderate", "some concern", "fair"):
        return "some concerns"
    if j in ("serious", "critical", "very high", "poor"):
        return "high"
    if j in ("good",):
        return "low"
    return "some concerns"


def _domain_order(assessments) -> list[str]:
    """Union of domain names, preserving first-seen order across studies."""
    seen: list[str] = []
    for a in assessments:
        for d in a.domains:
            if d.name not in seen:
                seen.append(d.name)
    return seen


def _short(name: str, n: int = 26) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


# ── Traffic-light grid ───────────────────────────────────────────────────────
def build_rob_traffic_figure(assessments: list["object"]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    if not assessments:
        raise ValueError("no assessments")

    domains = _domain_order(assessments)
    codes = [f"D{i + 1}" for i in range(len(domains))]
    cols = codes + ["Overall"]
    n_rows, n_cols = len(assessments), len(cols)
    tool = getattr(assessments[0], "tool", "RoB")

    # Wrapped domain key (D1 = …, D2 = …) for the caption strip.
    key_items = [f"{c} {_short(d, 30)}" for c, d in zip(codes, domains)]
    key_lines, line = [], ""
    for it in key_items:
        trial = (line + "    " + it).strip()
        if len(trial) > 64 and line:
            key_lines.append(line)
            line = it
        else:
            line = trial
    if line:
        key_lines.append(line)
    key_text = "\n".join(key_lines)

    cell = 0.62
    fig_w = max(5.4, 3.0 + cell * n_cols)
    fig_h = max(3.0, 2.0 + cell * n_rows + 0.22 * len(key_lines))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
    ax.set_xlim(0, n_cols)
    ax.set_ylim(0, n_rows)
    ax.set_aspect("equal")
    ax.axis("off")

    # Light grid background.
    for i in range(n_rows + 1):
        ax.plot([0, n_cols], [i, i], color="#e3e3e3", lw=0.5, zorder=0)
    for j in range(n_cols + 1):
        ax.plot([j, j], [0, n_rows], color="#e3e3e3", lw=0.5, zorder=0)

    # Compact column headers (D1…Dn upright; Overall bold).
    for j, col in enumerate(cols):
        bold = col == "Overall"
        ax.text(j + 0.5, n_rows + 0.18, col, rotation=0, ha="center", va="bottom",
                fontsize=7.8, fontweight="bold" if bold else "bold",
                color="#15202b")

    # Rows top-to-bottom = first study at top.
    for r, a in enumerate(assessments):
        y = n_rows - 1 - r + 0.5
        label = getattr(a, "study_label", "") or getattr(a, "uid", "")
        ax.text(-0.18, y, _short(str(label), 30), ha="right", va="center",
                fontsize=7.6, color="#15202b")
        by_name = {d.name: _norm_level(d.judgement) for d in a.domains}
        cells = [by_name.get(dn, "some concerns") for dn in domains]
        cells.append(_norm_level(getattr(a, "overall", "some concerns")))
        for j, lvl in enumerate(cells):
            ax.scatter([j + 0.5], [y], s=210, marker="o",
                       color=ROB_FILL[lvl], edgecolors="white", linewidths=1.1,
                       zorder=3)
            ax.text(j + 0.5, y, ROB_SYMBOL[lvl], ha="center", va="center",
                    fontsize=9, fontweight="bold",
                    color=ROB_SYMBOL_COLOR[lvl], zorder=4)

    # Judgement legend below the grid.
    handles = [
        Line2D([0], [0], marker="o", linestyle="", markersize=9,
               markerfacecolor=ROB_FILL[lv], markeredgecolor="white",
               label=f"{ROB_SYMBOL[lv]}  {_LABEL[lv]}")
        for lv in _LEVELS
    ]
    leg = ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.04),
                    ncol=3, frameon=False, fontsize=7.2, handletextpad=0.4,
                    columnspacing=1.4, title=f"{tool} risk-of-bias judgement",
                    title_fontsize=7.4)
    ax.add_artist(leg)
    # Domain key strip.
    ax.text(0.5, -0.04 - 0.055 * (2 + len(key_lines)), key_text,
            transform=ax.transAxes, ha="center", va="top", fontsize=6.6,
            color="#3a3f47", linespacing=1.45)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.10)
    return fig


# ── Weighted / stacked summary bar ───────────────────────────────────────────
def build_rob_summary_figure(assessments: list["object"]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    if not assessments:
        raise ValueError("no assessments")

    domains = _domain_order(assessments)
    rows = domains + ["Overall"]
    tool = getattr(assessments[0], "tool", "RoB")
    n = len(assessments)

    # Percentage at each level per domain (and overall).
    pct: dict[str, dict[str, float]] = {}
    for dn in domains:
        counts = {lv: 0 for lv in _LEVELS}
        seen = 0
        for a in assessments:
            for d in a.domains:
                if d.name == dn:
                    counts[_norm_level(d.judgement)] += 1
                    seen += 1
                    break
        seen = seen or 1
        pct[dn] = {lv: 100.0 * counts[lv] / seen for lv in _LEVELS}
    ov = {lv: 0 for lv in _LEVELS}
    for a in assessments:
        ov[_norm_level(getattr(a, "overall", "some concerns"))] += 1
    pct["Overall"] = {lv: 100.0 * ov[lv] / n for lv in _LEVELS}

    fig_h = max(2.4, 0.5 * len(rows) + 1.2)
    fig, ax = plt.subplots(figsize=(7.2, fig_h), dpi=150)
    ypos = list(range(len(rows)))[::-1]   # first domain at top

    for y, name in zip(ypos, rows):
        left = 0.0
        for lv in _LEVELS:
            w = pct[name][lv]
            if w <= 0:
                left += w
                continue
            ax.barh(y, w, left=left, height=0.62, color=ROB_FILL[lv],
                    edgecolor="white", linewidth=0.8, zorder=2)
            if w >= 8:
                ax.text(left + w / 2, y, f"{w:.0f}%", ha="center", va="center",
                        fontsize=6.6, color=ROB_SYMBOL_COLOR[lv], zorder=3)
            left += w

    ax.set_yticks(ypos)
    ax.set_yticklabels([_short(r, 34) + ("" if r != "Overall" else "")
                        for r in rows], fontsize=7.6,
                       fontweight="normal")
    # Bold the Overall tick label.
    for lab, r in zip(ax.get_yticklabels(), rows):
        if r == "Overall":
            lab.set_fontweight("bold")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Proportion of studies (%)", fontsize=8)
    ax.tick_params(axis="x", labelsize=7)
    ax.set_title(f"{tool} risk of bias across {n} studies", fontsize=9,
                 fontweight="bold", pad=8)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.7)
    ax.tick_params(axis="y", length=0)

    handles = [Patch(facecolor=ROB_FILL[lv], edgecolor="white", label=_LABEL[lv])
               for lv in _LEVELS]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=3, frameon=False, fontsize=7.2, handlelength=1.2,
              columnspacing=1.6)
    fig.subplots_adjust(left=0.30, right=0.97, top=0.88, bottom=0.22)
    return fig


# ── Save both ────────────────────────────────────────────────────────────────
def save_rob_figures(assessments: list["object"], outdir,
                     formats=("pdf", "png")) -> dict:
    """Render and save both figures into *outdir*. Tolerates empty input."""
    import matplotlib.pyplot as plt

    if not assessments:
        return {}
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    res: dict[str, list] = {"traffic": [], "summary": []}

    fig = build_rob_traffic_figure(assessments)
    for fmt in formats:
        p = out / f"rob_traffic.{fmt}"
        fig.savefig(p, bbox_inches="tight", facecolor="white", dpi=200)
        res["traffic"].append(p)
    plt.close(fig)

    fig = build_rob_summary_figure(assessments)
    for fmt in formats:
        p = out / f"rob_summary.{fmt}"
        fig.savefig(p, bbox_inches="tight", facecolor="white", dpi=200)
        res["summary"].append(p)
    plt.close(fig)
    return res
