"""Static figures for the report (matplotlib, no CARLA needed).

Colour: three validated categorical slots (blue, orange, aqua) plus neutral
gray. Four actions can't all be told apart when every pair can sit next to
each other (checked with the dataviz validator), so brake is gray with a
hatch, and every mark also carries a text label.
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Patch, Rectangle  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from .. import ACTIONS  # noqa: E402
from ..scenarios.spec import person_positions  # noqa: E402
from ..text import describe_people  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#8d8c86"
GRID = "#e4e3df"
ROAD = "#efeeea"

SLOTS = ("#2a78d6", "#eb6834", "#1baf7a")
ACTION_COLOR = {"maintain": SLOTS[0], "swerve_left": SLOTS[1], "swerve_right": SLOTS[2],
                "brake": INK_2}
ACTION_HATCH = {"brake": "////"}
CONDITION_COLOR = {"stated-abstract": SLOTS[0], "stated-detailed": SLOTS[1], "enacted": SLOTS[2]}
BEST_MARK = "★"  # star

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.edgecolor": GRID, "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
})


def _road(ax, scenario, x_max):
    w = scenario.lane_width_m
    ax.add_patch(Rectangle((-6, -1.5 * w), x_max + 6, 3 * w, color=ROAD, zorder=0, lw=0))
    for k, style in ((-1.5, "-"), (-0.5, "--"), (0.5, "--"), (1.5, "-")):
        ax.plot([-6, x_max], [k * w, k * w], color=MUTED, lw=1, ls=style, zorder=1)


def _plot_y(y):
    """Road frame y is metres to the right; drawn facing right, right is down."""
    return -y


def _people(ax, scenario, hit_ids=()):
    for g in scenario.groups:
        for i, (x, y) in enumerate(person_positions(g)):
            hit = (g.id, i) in hit_ids
            ax.add_patch(Circle((x, _plot_y(y)), 0.35, facecolor=INK if hit else SURFACE,
                                edgecolor=INK, lw=1.2, zorder=4))
        label = describe_people(g.count, g.attributes)
        ax.text(g.distance_m + 0.8, _plot_y(g.lateral_m) + 0.9, label, va="bottom", fontsize=8,
                color=INK_2, zorder=5)
    for o in scenario.obstacles:
        ax.add_patch(Rectangle((o.distance_m - 0.3, _plot_y(o.lateral_m) - 1.5), 0.6, 3.0,
                               facecolor=MUTED, edgecolor=INK_2, zorder=4))
        ax.text(o.distance_m + 1.0, _plot_y(o.lateral_m), o.type, va="center", fontsize=8,
                color=INK_2)


def _ego(ax):
    ax.add_patch(Rectangle((-2.35, -0.95), 4.7, 1.9, facecolor=SURFACE, edgecolor=INK, lw=1.2,
                           zorder=4))
    ax.text(0, 0, "ego", ha="center", va="center", fontsize=7, zorder=5)


def _frame(ax, scenario, x_max):
    w = scenario.lane_width_m
    ax.set_xlim(-6, x_max)
    ax.set_ylim(-1.5 * w - 0.5, 1.5 * w + 0.5)
    ax.set_aspect("equal")
    ax.set_yticks([])
    ax.set_xlabel("metres ahead")
    ax.spines["left"].set_visible(False)


def _x_max(scenario, outcomes):
    far = max([g.distance_m for g in scenario.groups] + [o.distance_m for o in scenario.obstacles]
              + [10.0])
    return max(far + 12, max(p[1] for o in outcomes for p in o["trajectory"]) + 3)


def scenario_schematic(scenario, outcomes, path):
    """Top-down layout from the spec with each action's measured path."""
    outcomes = sorted(outcomes, key=lambda o: ACTIONS.index(o["action"]))
    x_max = _x_max(scenario, outcomes)
    fig, ax = plt.subplots(figsize=(9, 3.2))
    _road(ax, scenario, x_max)
    _people(ax, scenario)
    _ego(ax)
    for o in outcomes:
        xs = [p[1] for p in o["trajectory"]]
        ys = [_plot_y(p[2]) for p in o["trajectory"]]
        ax.plot(xs, ys, color=ACTION_COLOR[o["action"]], lw=2, zorder=3,
                ls="--" if o["action"] == "brake" else "-")
        ax.text(xs[-1] + 0.4, ys[-1] + (0.6 if o["action"] == "brake" else 0), o["action"],
                fontsize=7, color=INK_2, va="center", zorder=6)
    _frame(ax, scenario, x_max)
    ax.set_title("{}: {:g} m/s, people {:g} m ahead".format(
        scenario.id, scenario.ego_speed_mps, max(g.distance_m for g in scenario.groups)),
        loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def outcome_text(o):
    if o["pedestrians_hit"]:
        text = "hits {} ({}) at {:.1f} m/s".format(o["pedestrians_hit"], ", ".join(o["groups_hit"]),
                                                   o["first_impact_speed_mps"])
    else:
        text = "no pedestrian hit"
    if o["obstacles_hit"]:
        text += "; crashes into " + ", ".join(o["obstacles_hit"])
    if o["lost_control"]:
        text += "; LOST CONTROL"
    if o["swerve_completed"] is False:
        text += "; swerve not completed"
    return text


def contact_sheet(scenario, outcomes, best, choices, path, images=None, title_suffix=""):
    """One panel per action. ``choices`` is {condition: action}; ``images`` {action: png}."""
    by_action = dict((o["action"], o) for o in outcomes)
    x_max = _x_max(scenario, outcomes)
    fig, axes = plt.subplots(2, 2, figsize=(11, 5.2 if not images else 7.5))
    for ax, action in zip(axes.flat, ACTIONS):
        o = by_action[action]
        if images and images.get(action):
            ax.imshow(plt.imread(images[action]))
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            _road(ax, scenario, x_max)
            hit_ids = set((h["group_id"], h["person"]) for h in o["hits"])
            _people(ax, scenario, hit_ids)
            _ego(ax)
            ax.plot([p[1] for p in o["trajectory"]], [_plot_y(p[2]) for p in o["trajectory"]],
                    color=INK, lw=2, zorder=3)
            _frame(ax, scenario, x_max)
        star = " " + BEST_MARK + " best" if action in best else ""
        chosen_by = [c for c, a in sorted(choices.items()) if a == action]
        chosen = "   chosen under: " + ", ".join(chosen_by) if chosen_by else ""
        ax.set_title("{}{}{}\n{}".format(action, star, chosen, outcome_text(o)), loc="left",
                     fontsize=9)
        for k, c in enumerate(chosen_by):
            pad = 0.012 + 0.012 * k
            ax.add_patch(Rectangle((-pad, -pad), 1 + 2 * pad, 1 + 2 * pad, transform=ax.transAxes,
                                   fill=False, edgecolor=CONDITION_COLOR[c], lw=2.5,
                                   clip_on=False))
    handles = [Patch(facecolor="none", edgecolor=CONDITION_COLOR[c], lw=2.5, label=c)
               for c in ("stated-abstract", "stated-detailed", "enacted")]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False,
               title="outline = action chosen under")
    note = ("Pedestrian attributes are metadata labels; the simulator's walkers look generic."
            if images else "Schematic from the spec with the measured path; filled circle = hit.")
    fig.suptitle("{}{}".format(scenario.id, title_suffix), x=0.01, ha="left", fontweight="bold")
    fig.text(0.01, 0.935, note, fontsize=8, color=INK_2)
    fig.tight_layout(rect=(0, 0.08, 1, 0.92), h_pad=2.0)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def best_action_heatmap(grids, path):
    """Best action per (speed, distance) cell, one panel per group-size layout."""
    n = len(grids)
    fig, axes = plt.subplots(1, n, figsize=(max(4.5, 3.6 * n), 3.4), squeeze=False)
    for ax, (key, cells) in zip(axes[0], grids.items()):
        speeds = sorted(set(v for v, _ in cells))
        dists = sorted(set(d for _, d in cells))
        for i, v in enumerate(speeds):
            for j, d in enumerate(dists):
                best = cells.get((v, d), [])
                label = "\n".join(best) if best else "-"
                if len(best) == 1:
                    color, hatch = ACTION_COLOR[best[0]], ACTION_HATCH.get(best[0])
                else:
                    color, hatch = GRID, None
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor=color, edgecolor=SURFACE, lw=2,
                                       hatch=hatch, alpha=0.35 if len(best) == 1 else 1.0))
                ax.text(j + 0.5, i + 0.5, label, ha="center", va="center", fontsize=8, color=INK)
        ax.set_xlim(0, len(dists))
        ax.set_ylim(0, len(speeds))
        ax.set_xticks([j + 0.5 for j in range(len(dists))])
        ax.set_xticklabels(["%g" % d for d in dists])
        ax.set_yticks([i + 0.5 for i in range(len(speeds))])
        ax.set_yticklabels(["%g" % v for v in speeds])
        ax.set_xlabel("distance to people (m)")
        ax.set_ylabel("speed (m/s)")
        ax.set_title(key, loc="left", fontsize=9)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    fig.suptitle("Best action by measured outcome (ties listed)", x=0.01, ha="left",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def agreement_bars(agreement_rows, path, theory="neutral"):
    rows = [r for r in agreement_rows if r["theory"] == theory]
    models = sorted(set(r["model"] for r in rows))
    pairs = []
    for r in rows:
        if r["pair"] not in pairs:
            pairs.append(r["pair"])
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    width = 0.8 / max(1, len(models))
    for k, model in enumerate(models[:3]):  # three validated slots; facet beyond that
        xs, ys = [], []
        for i, pair in enumerate(pairs):
            match = [r for r in rows if r["model"] == model and r["pair"] == pair]
            if match:
                xs.append(i + (k - (len(models) - 1) / 2.0) * width)
                ys.append(match[0]["agreement"])
        bars = ax.bar(xs, ys, width=width * 0.92, color=SLOTS[k], label=model)
        for b, y in zip(bars, ys):
            ax.text(b.get_x() + b.get_width() / 2, y + 0.02, "{:.0%}".format(y), ha="center",
                    fontsize=8, color=INK)
    ax.set_xticks(range(len(pairs)))
    ax.set_xticklabels(pairs)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("same action chosen")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    if len(models) > 1:
        ax.legend(frameon=False, loc="upper right")
    title = "Agreement between conditions ({} prompt)".format(theory)
    if len(models) == 1:
        title += ", model: " + models[0]
    ax.set_title(title, loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def optimal_rate_bars(regret_rows, path, theory="neutral"):
    rows = [r for r in regret_rows if r["theory"] == theory]
    models = sorted(set(r["model"] for r in rows))
    conds = ("stated-abstract", "stated-detailed", "enacted")
    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    width = 0.8 / max(1, len(models))
    for k, model in enumerate(models[:3]):
        xs, ys = [], []
        for i, c in enumerate(conds):
            match = [r for r in rows if r["model"] == model and r["condition"] == c]
            if match:
                xs.append(i + (k - (len(models) - 1) / 2.0) * width)
                ys.append(match[0]["optimal_rate"])
        bars = ax.bar(xs, ys, width=width * 0.92, color=SLOTS[k], label=model)
        for b, y in zip(bars, ys):
            ax.text(b.get_x() + b.get_width() / 2, y + 0.02, "{:.0%}".format(y), ha="center",
                    fontsize=8)
    ax.set_xticks(range(len(conds)))
    ax.set_xticklabels(conds)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("chose a best action")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    if len(models) > 1:
        ax.legend(frameon=False, loc="upper right")
    ax.set_title("How often the choice was a best action ({} prompt)".format(theory), loc="left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def make_all(analysis, outcomes_by_scenario, out_dir, key_frames=None):
    """Write every figure; returns {name: path} (paths relative to out_dir's parent)."""
    os.makedirs(out_dir, exist_ok=True)
    made = {}
    p = os.path.join(out_dir, "best_action_heatmap.png")
    best_action_heatmap(analysis.best_action_grid(), p)
    made["heatmap"] = p
    agreement = analysis.agreement_table()
    regret = analysis.regret_table()
    theories = sorted(set(r["theory"] for r in analysis.rows))
    for theory in theories:
        if any(r["theory"] == theory for r in agreement):
            p = os.path.join(out_dir, "agreement_{}.png".format(theory))
            agreement_bars(agreement, p, theory)
            made["agreement_" + theory] = p
        p = os.path.join(out_dir, "optimal_rate_{}.png".format(theory))
        optimal_rate_bars(regret, p, theory)
        made["optimal_" + theory] = p
    models = sorted(set(r["model"] for r in analysis.rows))
    for sid, s in analysis.scenarios.items():
        p = os.path.join(out_dir, "schematic_{}.png".format(sid))
        scenario_schematic(s, outcomes_by_scenario[sid], p)
        made["schematic_" + sid] = p
        for model in models or [None]:
            choices = {}
            for r in analysis.rows:
                if r["scenario_id"] == sid and r["model"] == model and r["theory"] == "neutral":
                    choices[r["condition"]] = r["action"]
            p = os.path.join(out_dir, "contact_{}_{}.png".format(sid, model or "none"))
            images = (key_frames or {}).get(sid)
            contact_sheet(s, outcomes_by_scenario[sid], analysis.best[sid], choices, p,
                          images=images,
                          title_suffix="  (model: {}, neutral prompt)".format(model)
                          if model else "")
            made["contact_{}_{}".format(sid, model)] = p
    return made
