"""The three figures in results/."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from plumbline import config
from plumbline.experiments import SAME_MARKETS

INK = "#1f2933"
ACCENT = "#b5482a"
SECOND = "#2a6f97"
GRID = "#d9dde2"


def _style(ax: plt.Axes) -> None:
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def calibration_figure(curve: pd.DataFrame, path: Path) -> None:
    """Win rate against price at the primary horizon, one panel per venue."""
    primary = curve[curve["days_before_close"] == config.PRIMARY_HORIZON_DAYS]
    venues = sorted(primary["venue"].unique())
    fig, axes = plt.subplots(1, len(venues), figsize=(4.6 * len(venues), 4.4), squeeze=False)
    for ax, venue in zip(axes[0], venues, strict=True):
        frame = primary[primary["venue"] == venue]
        x = frame["mean_price"].to_numpy() * 100
        y = frame["win_rate"].to_numpy() * 100
        low = (frame["mean_price"] + frame["gap_low"]).to_numpy() * 100
        high = (frame["mean_price"] + frame["gap_high"]).to_numpy() * 100
        ax.plot(
            [0, 100], [0, 100], color=INK, linewidth=0.8, linestyle="--", label="price = win rate"
        )
        ax.errorbar(
            x,
            y,
            yerr=[np.maximum(y - low, 0), np.maximum(high - y, 0)],
            fmt="o-",
            color=ACCENT,
            markersize=4,
            linewidth=1.2,
            capsize=2.5,
            label="settled markets, 95% interval",
        )
        ax.set_title(f"{venue}: {int(frame['markets'].sum()):,} markets", fontsize=10, color=INK)
        ax.set_xlabel(f"Price {config.PRIMARY_HORIZON_DAYS} days before close (cents)")
        ax.set_ylabel("Share that settled in favour (%)")
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_aspect("equal")
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def edge_figure(edge: pd.DataFrame, path: Path) -> None:
    """Profit per contract after costs, by price bin and side, at the primary horizon."""
    primary = edge[edge["days_before_close"] == config.PRIMARY_HORIZON_DAYS]
    costed = primary[~primary["cost_model"].str.contains("no fee")]
    venues = sorted(costed["venue"].unique())
    fig, axes = plt.subplots(1, len(venues), figsize=(4.6 * len(venues), 4.0), squeeze=False)
    for ax, venue in zip(axes[0], venues, strict=True):
        frame = costed[costed["venue"] == venue]
        model = str(frame["cost_model"].iloc[0])
        for side, colour, shift in (
            ("buy priced side", ACCENT, -1.2),
            ("buy other side", SECOND, 1.2),
        ):
            part = frame[frame["side"] == side]
            x = np.array([float(label.split("-")[0]) * 100 + 5 for label in part["price_bin"]])
            y = part["edge"].to_numpy() * 100
            low = part["edge_low"].to_numpy() * 100
            high = part["edge_high"].to_numpy() * 100
            ax.errorbar(
                x + shift,
                y,
                yerr=[np.maximum(y - low, 0), np.maximum(high - y, 0)],
                fmt="o",
                color=colour,
                markersize=4,
                capsize=2.5,
                linewidth=1.0,
                label=side,
            )
        ax.axhline(0, color=INK, linewidth=0.8)
        ax.set_title(f"{venue}: {model}", fontsize=10, color=INK)
        ax.set_xlabel(f"Price {config.PRIMARY_HORIZON_DAYS} days before close (cents)")
        ax.set_ylabel("Mean profit per contract (cents)")
        ax.set_xlim(0, 100)
        ax.legend(frameon=False, fontsize=8)
        _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def brier_figure(brier: pd.DataFrame, path: Path) -> None:
    """Brier score by horizon on the same markets, against the base-rate forecast."""
    brier = brier[brier["sample"] == SAME_MARKETS]
    venues = sorted(brier["venue"].unique())
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    width = 0.8 / max(len(venues), 1)
    horizons = sorted(brier["days_before_close"].unique())
    for i, venue in enumerate(venues):
        frame = brier[brier["venue"] == venue].set_index("days_before_close")
        position = np.array([horizons.index(day) for day in frame.index], dtype=float)
        offset = (i - (len(venues) - 1) / 2) * width
        score = frame["brier"].to_numpy()
        ax.bar(
            position + offset,
            score,
            width=width * 0.9,
            color=(ACCENT, SECOND)[i % 2],
            yerr=[
                np.maximum(score - frame["brier_low"].to_numpy(), 0),
                np.maximum(frame["brier_high"].to_numpy() - score, 0),
            ],
            capsize=2.5,
            label=f"{venue}: price",
        )
        ax.scatter(
            position + offset,
            frame["brier_base_rate"].to_numpy(),
            marker="_",
            s=260,
            color=INK,
            zorder=3,
            label="base rate of the same markets" if i == 0 else None,
        )
    ax.axhline(0.25, color=INK, linewidth=0.8, linestyle="--")
    ax.text(-0.45, 0.254, "always 50%", fontsize=8, color=INK, ha="left")
    ax.set_ylim(0, 0.33)
    ax.set_xticks(range(len(horizons)))
    ax.set_xticklabels([f"{day} days" if day != 1 else "1 day" for day in horizons])
    ax.set_xlabel("Time before close")
    ax.set_ylabel("Brier score (lower is better)")
    ax.legend(frameon=False, fontsize=8, loc="upper right", ncols=3)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
