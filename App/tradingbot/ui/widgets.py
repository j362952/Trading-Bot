"""Gemeinsame GUI-Bausteine der vier Seiten."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pandas as pd


def make_tree(parent, columns: list[tuple[str, str, int]],
              height: int | None = None, stretch_col: str | None = None) -> ttk.Treeview:
    """Treeview mit Scrollbar; columns = [(key, Überschrift, Breite), …]."""
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                        **({"height": height} if height else {}))
    for key, head, width in columns:
        tree.heading(key, text=head)
        tree.column(key, width=width, anchor="w",
                    stretch=(key == stretch_col))
    ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ys.set)
    tree.pack(side="left", fill="both", expand=True)
    ys.pack(side="right", fill="y")
    return tree


def fill_tree(tree: ttk.Treeview, rows: list[tuple]) -> None:
    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=row)


def fill_tree_df(tree: ttk.Treeview, df: pd.DataFrame, columns: list[str]) -> None:
    tree.delete(*tree.get_children())
    for _, r in df.iterrows():
        tree.insert("", "end", values=tuple("" if pd.isna(r[c]) else r[c] for c in columns))


class EquityCanvas(tk.Canvas):
    """Schlichte Equity-Kurve ohne Zusatz-Abhängigkeiten (kein matplotlib)."""

    def __init__(self, parent, height: int = 120, **kw):
        super().__init__(parent, height=height, bg="white",
                         highlightthickness=1, highlightbackground="#ccc", **kw)
        self._series: pd.Series | None = None
        self.bind("<Configure>", lambda e: self._redraw())

    def plot(self, series: pd.Series) -> None:
        self._series = series.dropna() if series is not None else None
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        s = self._series
        w, h = self.winfo_width(), self.winfo_height()
        if s is None or len(s) < 2 or w < 20:
            self.create_text(w // 2, h // 2, text="(noch keine Equity-Historie)",
                             fill="#999")
            return
        lo, hi = float(s.min()), float(s.max())
        span = (hi - lo) or 1.0
        pad = 6
        pts = []
        for i, v in enumerate(s):
            x = pad + i * (w - 2 * pad) / (len(s) - 1)
            y = h - pad - (float(v) - lo) * (h - 2 * pad) / span
            pts += [x, y]
        color = "#2e7d32" if s.iloc[-1] >= s.iloc[0] else "#c62828"
        self.create_line(*pts, fill=color, width=2)
        self.create_text(pad + 2, pad + 2, anchor="nw", fill="#666",
                         text=f"{s.iloc[0]:,.0f} → {s.iloc[-1]:,.0f}")


class SparkCanvas(tk.Canvas):
    """Mini-Chart für Makro-Reihen (Daten-Seite)."""

    def __init__(self, parent, width: int = 160, height: int = 36, **kw):
        super().__init__(parent, width=width, height=height, bg="white",
                         highlightthickness=1, highlightbackground="#ddd", **kw)

    def plot(self, series: pd.Series) -> None:
        self.delete("all")
        s = series.dropna().iloc[-260:]  # ~1 Jahr
        w, h = int(self["width"]), int(self["height"])
        if len(s) < 2:
            self.create_text(w // 2, h // 2, text="–", fill="#999")
            return
        lo, hi = float(s.min()), float(s.max())
        span = (hi - lo) or 1.0
        pts = []
        for i, v in enumerate(s):
            x = 2 + i * (w - 4) / (len(s) - 1)
            y = h - 2 - (float(v) - lo) * (h - 4) / span
            pts += [x, y]
        self.create_line(*pts, fill="#1565c0")


def labeled_entry(parent, label: str, value: str, width: int = 10,
                  label_width: int = 28) -> tk.StringVar:
    row = ttk.Frame(parent)
    row.pack(anchor="w", pady=2)
    ttk.Label(row, text=label, width=label_width).pack(side="left")
    var = tk.StringVar(value=value)
    ttk.Entry(row, textvariable=var, width=width).pack(side="left")
    return var
