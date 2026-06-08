"""
hud.py — Minimal floating HUD.

Design principles:
  - Project names are the only content shown by default
  - Path appears on hover, nothing else
  - Monochrome only — no color coding, no icons, no badges
  - Width: 160px. Height: auto from workspace count.
  - Click → focus the workspace's terminal window, immediately

The HUD never knows about PIDs, tty, or window IDs.
It only knows about Workspace objects.
"""

import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

from detector import Workspace
from logger import WorkspaceLogger

# ── Color palette (monochrome only) ─────────────────────────────────────────
_BG          = "#0f0f0f"   # row/body background
_BG_HANDLE   = "#141414"   # drag handle — distinct chrome zone
_BG_HOV      = "#191919"   # row hover background
_DIVIDER     = "#1d1d1d"   # 1px separator between handle and rows
_FG_HANDLE   = "#252525"   # "waypoint" label in handle
_FG_IDLE     = "#282828"   # "—" dash when no workspaces are active
_FG_NAME     = "#b0b0b0"   # project name, idle
_FG_NAME_HOV = "#f2f2f2"   # project name, hovered
_FG_PATH_HOV = "#484848"   # path text, hovered (only time it's visible)

# ── Dimensions ───────────────────────────────────────────────────────────────
_W         = 160   # fixed width
_ROW_H     = 44    # workspace row height
_HANDLE_H  = 20    # drag handle height (chrome-only zone, not clickable as row)


class HUD:
    def __init__(self, root: tk.Tk, config: dict, detector) -> None:
        self.root = root
        self.config = config
        self.detector = detector
        self.poll_ms = int(config.get("poll_interval", 2) * 1000)
        self.opacity  = float(config.get("opacity", 0.88))
        self.position = config.get("position", "bottom-right")

        self._drag_x = 0
        self._drag_y = 0
        self._row_widgets: list[tk.Widget] = []
        self._logger = WorkspaceLogger()

        self._setup_window()
        self._build_header()
        self._poll()

    # ── Window ───────────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-alpha", self.opacity)
        self.root.configure(bg=_BG)
        self._set_geometry(n=1)

    def _set_geometry(self, n: int) -> None:
        """Resize to fit n workspace rows and preserve current position."""
        h = _HANDLE_H + 1 + max(n, 1) * _ROW_H  # handle + divider + rows
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            if x == 0 and y == 0:
                raise ValueError
        except Exception:
            x, y = self._initial_position(h)
        self.root.geometry(f"{_W}x{h}+{x}+{y}")

    def _initial_position(self, h: int) -> tuple[int, int]:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        m = 16
        return {
            "top-left":     (m,          40),
            "top-right":    (sw - _W - m, 40),
            "bottom-left":  (m,          sh - h - 40),
            "bottom-right": (sw - _W - m, sh - h - 40),
        }.get(self.position, (sw - _W - m, sh - h - 40))

    # ── Chrome (handle + divider) ─────────────────────────────────────────────

    def _build_header(self) -> None:
        handle_font = tkfont.Font(family="SF Pro Text", size=9, weight="normal")

        # Drag handle — the only draggable surface. cursor="fleur" signals
        # that this area moves the window; workspace rows are never in here.
        self.handle = tk.Frame(
            self.root, bg=_BG_HANDLE, height=_HANDLE_H, cursor="fleur",
        )
        self.handle.pack(fill="x")
        self.handle.pack_propagate(False)

        self._handle_lbl = tk.Label(
            self.handle, text="waypoint",
            font=handle_font, fg=_FG_HANDLE, bg=_BG_HANDLE, anchor="w",
        )
        self._handle_lbl.pack(side="left", padx=10, pady=0)

        # 1px visual separator — reinforces the chrome / content boundary
        tk.Frame(self.root, bg=_DIVIDER, height=1).pack(fill="x")

        # Container where workspace rows live
        self.body = tk.Frame(self.root, bg=_BG)
        self.body.pack(fill="both", expand=True)

        # Drag bindings live only on the handle — never on rows or root
        for w in (self.handle, self._handle_lbl):
            w.bind("<Button-1>",  self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<Button-2>",  self._menu)
            w.bind("<Button-3>",  self._menu)

        # Context menu reachable from body and root as well
        for w in (self.root, self.body):
            w.bind("<Button-2>", self._menu)
            w.bind("<Button-3>", self._menu)

    # ── Drag ─────────────────────────────────────────────────────────────────

    def _drag_start(self, e: tk.Event) -> None:
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e: tk.Event) -> None:
        self.root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── Context menu ─────────────────────────────────────────────────────────

    def _menu(self, e: tk.Event) -> None:
        m = tk.Menu(
            self.root, tearoff=0,
            bg="#1a1a1a", fg="#c0c0c0",
            activebackground="#2a2a2a", activeforeground="#f0f0f0",
            font=("SF Pro Text", 11), bd=0,
        )
        sub = tk.Menu(m, tearoff=0, bg="#1a1a1a", fg="#c0c0c0",
                      activebackground="#2a2a2a", activeforeground="#f0f0f0")
        for pct in [100, 90, 75, 50]:
            sub.add_command(
                label=f"{pct}%",
                command=lambda p=pct: self.root.wm_attributes("-alpha", p / 100),
            )
        m.add_cascade(label="Opacity", menu=sub)
        m.add_separator()
        m.add_command(label="Quit", command=self._quit)
        m.tk_popup(e.x_root, e.y_root)

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        workspaces = self.detector.detect()
        self._logger.update(workspaces)
        self._refresh(workspaces)
        self.root.after(self.poll_ms, self._poll)

    def _quit(self) -> None:
        self._logger.shutdown()
        self.root.destroy()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh(self, workspaces: list[Workspace]) -> None:
        for w in self._row_widgets:
            w.destroy()
        self._row_widgets.clear()

        if workspaces:
            for ws in workspaces:
                row = self._workspace_row(ws)
                row.pack(fill="x")
                self._row_widgets.append(row)
        else:
            idle = self._idle_row()
            idle.pack(fill="x")
            self._row_widgets.append(idle)

        self._set_geometry(n=max(len(workspaces), 1))

    # ── Row builders ──────────────────────────────────────────────────────────

    def _workspace_row(self, ws: Workspace) -> tk.Frame:
        name_font = tkfont.Font(family="SF Pro Display", size=13, weight="normal")
        path_font = tkfont.Font(family="SF Pro Mono",    size=10, weight="normal")

        row = tk.Frame(self.body, bg=_BG, height=_ROW_H, cursor="hand2")
        row.pack_propagate(False)

        name_lbl = tk.Label(
            row, text=ws.name,
            font=name_font, fg=_FG_NAME, bg=_BG,
            anchor="w",
        )
        name_lbl.place(x=14, y=8)

        # Path label — rendered invisible (fg = bg) until hover
        path_lbl = tk.Label(
            row, text=ws.display_path,
            font=path_font, fg=_BG, bg=_BG,   # invisible by default
            anchor="w",
        )
        path_lbl.place(x=14, y=26)

        # ── Hover + click ────────────────────────────────────────────────────
        all_w = [row, name_lbl, path_lbl]

        def enter(_e):
            row.config(bg=_BG_HOV)
            name_lbl.config(fg=_FG_NAME_HOV, bg=_BG_HOV)
            path_lbl.config(fg=_FG_PATH_HOV, bg=_BG_HOV)

        def leave(_e):
            row.config(bg=_BG)
            name_lbl.config(fg=_FG_NAME, bg=_BG)
            path_lbl.config(fg=_BG, bg=_BG)

        def click(_e):
            self.detector.focus(ws)

        for w in all_w:
            w.bind("<Enter>",    enter)
            w.bind("<Leave>",    leave)
            w.bind("<Button-1>", click)
            w.bind("<Button-2>", self._menu)
            w.bind("<Button-3>", self._menu)

        return row

    def _idle_row(self) -> tk.Frame:
        font = tkfont.Font(family="SF Pro Text", size=11, weight="normal")
        row = tk.Frame(self.body, bg=_BG, height=_ROW_H)
        row.pack_propagate(False)

        tk.Label(
            row, text="—",
            font=font, fg=_FG_IDLE, bg=_BG, anchor="w",
        ).place(x=14, y=13)

        row.bind("<Button-2>", self._menu)
        row.bind("<Button-3>", self._menu)

        return row
