"""
hud.py — Borderless floating HUD for Waypoint.

Layout (per session detected):
  ╔═══════════════════════╗  ← accent bar (project color)
  ║ WAYPOINT              ║  ← static header
  ╠═══════════════════════╣
  ║▌ Project Alpha        ║  ← clickable session row
  ║  ~/path/to/project    ║
  ╠═══════════════════════╣
  ║▌ Project Beta         ║  ← second session (if any)
  ║  ~/other/path         ║
  ╚═══════════════════════╝

Idle state:
  ╔═══════════════════════╗
  ║ WAYPOINT              ║
  ║  no claude sessions   ║
  ╚═══════════════════════╝
"""

import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

# Fixed window width; height is recalculated after each poll
_WIDTH = 230
_HEADER_H = 34   # pixels for the WAYPOINT label row
_ROW_H = 48      # pixels per session row
_ACCENT_H = 3    # top accent bar height


class HUD:
    def __init__(self, root: tk.Tk, config: dict, detector) -> None:
        self.root = root
        self.config = config
        self.detector = detector

        self.poll_ms = int(config.get("poll_interval", 2) * 1000)
        self.opacity = float(config.get("opacity", 0.92))
        self.position = config.get("position", "bottom-right")

        self._drag_x = 0
        self._drag_y = 0
        # Tracks dynamically-created session rows so they can be cleared
        self._session_widgets: list[tk.Widget] = []

        self._setup_window()
        self._build_chrome()
        self._poll()

    # -----------------------------------------------------------------------
    # Window setup
    # -----------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.overrideredirect(True)           # no title bar
        self.root.wm_attributes("-topmost", True)  # always on top
        self.root.wm_attributes("-alpha", self.opacity)
        self.root.configure(bg="#1e1e2e")
        self._resize_and_position(n_rows=1)        # initial size

    def _resize_and_position(self, n_rows: int) -> None:
        """Recalculate window height and preserve current X/Y (or set initial)."""
        h = _ACCENT_H + _HEADER_H + max(n_rows, 1) * _ROW_H + 6
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            # winfo returns 0,0 before first draw; use configured position then
            if x == 0 and y == 0:
                raise ValueError
        except Exception:
            x, y = self._initial_xy(h)
        self.root.geometry(f"{_WIDTH}x{h}+{x}+{y}")

    def _initial_xy(self, h: int) -> tuple[int, int]:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        m = 16
        table = {
            "top-left":     (m,          40),
            "top-right":    (sw - _WIDTH - m, 40),
            "bottom-left":  (m,          sh - h - 40),
            "bottom-right": (sw - _WIDTH - m, sh - h - 40),
        }
        return table.get(self.position, table["bottom-right"])

    # -----------------------------------------------------------------------
    # Static chrome (accent bar + header)
    # -----------------------------------------------------------------------

    def _build_chrome(self) -> None:
        # Thin colored bar at top
        self.accent_bar = tk.Frame(self.root, height=_ACCENT_H, bg="#4a4a6a")
        self.accent_bar.pack(fill="x", side="top")

        # Header
        header = tk.Frame(self.root, bg="#1e1e2e", padx=12, pady=8)
        header.pack(fill="x")

        lbl_font = tkfont.Font(family="SF Pro Text", size=9, weight="bold")
        self._header_lbl = tk.Label(
            header, text="WAYPOINT",
            font=lbl_font, fg="#4a5568", bg="#1e1e2e",
        )
        self._header_lbl.pack(side="left")

        # Container where session rows are injected
        self.body = tk.Frame(self.root, bg="#1e1e2e")
        self.body.pack(fill="both", expand=True)

        # Bind drag + context menu to chrome widgets
        for w in (self.root, self.accent_bar, header, self._header_lbl):
            w.bind("<Button-1>",  self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<Button-2>",  self._show_menu)
            w.bind("<Button-3>",  self._show_menu)

    # -----------------------------------------------------------------------
    # Drag
    # -----------------------------------------------------------------------

    def _drag_start(self, e: tk.Event) -> None:
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e: tk.Event) -> None:
        self.root.geometry(
            f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}"
        )

    # -----------------------------------------------------------------------
    # Context menu
    # -----------------------------------------------------------------------

    def _show_menu(self, e: tk.Event) -> None:
        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2d2d3f", fg="#e2e8f0",
            activebackground="#3d3d5f", activeforeground="#fff",
            font=("SF Pro Text", 11), bd=0,
        )
        opacity_sub = tk.Menu(
            menu, tearoff=0, bg="#2d2d3f", fg="#e2e8f0",
            activebackground="#3d3d5f", activeforeground="#fff",
        )
        for pct in [100, 90, 75, 50]:
            opacity_sub.add_command(
                label=f"{pct}%",
                command=lambda p=pct: self.root.wm_attributes("-alpha", p / 100),
            )
        menu.add_cascade(label="Opacity", menu=opacity_sub)
        menu.add_separator()
        menu.add_command(label="Quit Waypoint", command=self.root.destroy)
        menu.tk_popup(e.x_root, e.y_root)

    # -----------------------------------------------------------------------
    # Poll loop
    # -----------------------------------------------------------------------

    def _poll(self) -> None:
        sessions = self.detector.detect()
        self._refresh(sessions)
        self.root.after(self.poll_ms, self._poll)

    # -----------------------------------------------------------------------
    # Display refresh
    # -----------------------------------------------------------------------

    def _refresh(self, sessions: list[dict]) -> None:
        # Destroy previous dynamic rows
        for w in self._session_widgets:
            w.destroy()
        self._session_widgets.clear()

        if sessions:
            first_color = sessions[0]["project"].get("color", "#7e3af2")
            self.accent_bar.config(bg=first_color)
            for session in sessions:
                row = self._make_session_row(session)
                row.pack(fill="x")
                self._session_widgets.append(row)
        else:
            self.accent_bar.config(bg="#4a4a6a")
            idle = self._make_idle_row()
            idle.pack(fill="x")
            self._session_widgets.append(idle)

        self._resize_and_position(n_rows=max(len(sessions), 1))

    # -----------------------------------------------------------------------
    # Row builders
    # -----------------------------------------------------------------------

    def _make_session_row(self, session: dict) -> tk.Frame:
        project   = session["project"]
        color     = project.get("color", "#7e3af2")
        name      = project["name"]
        cwd       = session.get("path", "")
        window_id = session.get("window_id")

        # Show last two path components as subtitle
        parts = [p for p in cwd.strip("/").split("/") if p]
        subtitle = "/".join(parts[-2:]) if parts else "claude active"

        # ── Frame ──────────────────────────────────────────────────────────
        row = tk.Frame(
            self.body, bg="#1e1e2e",
            cursor="hand2" if window_id else "arrow",
        )

        # Colored left stripe
        stripe = tk.Frame(row, width=3, bg=color)
        stripe.pack(side="left", fill="y")

        # Content
        content = tk.Frame(row, bg="#1e1e2e", padx=10, pady=7)
        content.pack(side="left", fill="both", expand=True)

        name_font = tkfont.Font(family="SF Pro Display", size=12, weight="bold")
        path_font = tkfont.Font(family="SF Pro Mono", size=10)

        lbl_name = tk.Label(
            content, text=name, font=name_font,
            fg="#e2e8f0", bg="#1e1e2e", anchor="w",
        )
        lbl_name.pack(fill="x")

        lbl_path = tk.Label(
            content, text=subtitle, font=path_font,
            fg="#64748b", bg="#1e1e2e", anchor="w",
        )
        lbl_path.pack(fill="x")

        # ── Hover + click bindings ──────────────────────────────────────────
        # bg_targets: widgets whose background changes on hover (stripe excluded)
        bg_targets = [row, content, lbl_name, lbl_path]

        def enter(_e, targets=bg_targets):
            for w in targets:
                try:
                    w.config(bg="#252535")
                except tk.TclError:
                    pass

        def leave(_e, targets=bg_targets):
            for w in targets:
                try:
                    w.config(bg="#1e1e2e")
                except tk.TclError:
                    pass

        def click(_e, wid=window_id):
            if wid:
                self.detector.focus_window(wid)

        for w in bg_targets + [stripe]:
            w.bind("<Enter>",    enter)
            w.bind("<Leave>",    leave)
            w.bind("<Button-1>", click)
            w.bind("<Button-2>", self._show_menu)
            w.bind("<Button-3>", self._show_menu)

        # Also let the row participate in window drag when not clicking a session
        row.bind("<B1-Motion>", self._drag_move)

        return row

    def _make_idle_row(self) -> tk.Frame:
        row = tk.Frame(self.body, bg="#1e1e2e", padx=14, pady=12)
        font = tkfont.Font(family="SF Pro Text", size=11)
        tk.Label(
            row, text="no claude sessions",
            font=font, fg="#4a5568", bg="#1e1e2e",
        ).pack(anchor="w")

        # Idle row participates in drag
        row.bind("<Button-1>",  self._drag_start)
        row.bind("<B1-Motion>", self._drag_move)
        row.bind("<Button-2>",  self._show_menu)
        row.bind("<Button-3>",  self._show_menu)
        return row
