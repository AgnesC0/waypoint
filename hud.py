"""
hud.py — Borderless floating HUD window built with tkinter.

Features:
  - Always-on-top, borderless, transparent window
  - Colored accent bar + dot that reflect the active project
  - Drag to reposition anywhere on screen
  - Right-click context menu for opacity control and quit
"""

import tkinter as tk
from tkinter import font as tkfont
from typing import Optional


# Default window dimensions (width × height in pixels)
_W, _H = 210, 62


class HUD:
    def __init__(self, root: tk.Tk, config: dict, detector) -> None:
        self.root = root
        self.config = config
        self.detector = detector

        # Poll interval converted from seconds → milliseconds
        self.poll_ms = int(config.get("poll_interval", 2) * 1000)
        self.opacity = float(config.get("opacity", 0.92))
        self.position = config.get("position", "bottom-right")

        # Stores window-relative grab point during a drag
        self._drag_x = 0
        self._drag_y = 0

        self._setup_window()
        self._build_ui()
        self._bind_drag_and_menu()
        self._poll()

    # ------------------------------------------------------------------
    # Window initialisation
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.overrideredirect(True)          # remove title bar / chrome
        self.root.wm_attributes("-topmost", True) # float above all windows
        self.root.wm_attributes("-alpha", self.opacity)
        self.root.configure(bg="#1e1e2e")
        self._place_at(self.position)

    def _place_at(self, position: str) -> None:
        """Position the window based on a cardinal quadrant string."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        margin = 16

        coords = {
            "top-left":     (margin,          40),
            "top-right":    (sw - _W - margin, 40),
            "bottom-left":  (margin,          sh - _H - 40),
            "bottom-right": (sw - _W - margin, sh - _H - 40),
        }
        x, y = coords.get(position, coords["bottom-right"])
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Thin accent bar across the top — color changes with active project
        self.accent = tk.Frame(self.root, height=3, bg="#4a4a6a")
        self.accent.pack(fill="x", side="top")

        # Main content area
        body = tk.Frame(self.root, bg="#1e1e2e", padx=14, pady=7)
        body.pack(fill="both", expand=True)

        # ── Row 1: dot indicator + project name ──────────────────────
        row1 = tk.Frame(body, bg="#1e1e2e")
        row1.pack(fill="x")

        # Small circular color dot drawn on a Canvas so we can recolor it
        self._dot_cv = tk.Canvas(
            row1, width=10, height=10,
            bg="#1e1e2e", highlightthickness=0,
        )
        self._dot_cv.pack(side="left", padx=(0, 7))
        self._dot = self._dot_cv.create_oval(1, 1, 9, 9, fill="#4a4a6a", outline="")

        name_font = tkfont.Font(family="SF Pro Display", size=13, weight="bold")
        self._lbl_name = tk.Label(
            row1, text="Waypoint",
            font=name_font, fg="#e2e8f0", bg="#1e1e2e",
        )
        self._lbl_name.pack(side="left")

        # ── Row 2: status line ────────────────────────────────────────
        status_font = tkfont.Font(family="SF Pro Text", size=10)
        self._lbl_status = tk.Label(
            body, text="scanning…",
            font=status_font, fg="#64748b", bg="#1e1e2e",
        )
        self._lbl_status.pack(anchor="w", pady=(2, 0))

        # Collect every widget so we can attach the same bindings to all of them
        self._all_widgets = [
            self.root, self.accent, body, row1,
            self._dot_cv, self._lbl_name, self._lbl_status,
        ]

    # ------------------------------------------------------------------
    # Drag + context menu
    # ------------------------------------------------------------------

    def _bind_drag_and_menu(self) -> None:
        for w in self._all_widgets:
            w.bind("<Button-1>",   self._on_drag_start)
            w.bind("<B1-Motion>",  self._on_drag_move)
            w.bind("<Button-2>",   self._on_right_click)  # two-finger tap
            w.bind("<Button-3>",   self._on_right_click)  # right-click

    def _on_drag_start(self, event: tk.Event) -> None:
        # Record where inside the window the user clicked
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _on_drag_move(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_right_click(self, event: tk.Event) -> None:
        menu = tk.Menu(
            self.root, tearoff=0,
            bg="#2d2d3f", fg="#e2e8f0",
            activebackground="#3d3d5f", activeforeground="#ffffff",
            font=("SF Pro Text", 11), bd=0,
        )

        # Opacity sub-menu
        sub = tk.Menu(
            menu, tearoff=0,
            bg="#2d2d3f", fg="#e2e8f0",
            activebackground="#3d3d5f", activeforeground="#ffffff",
        )
        for pct in [100, 90, 75, 50]:
            sub.add_command(
                label=f"{pct}%",
                command=lambda p=pct: self.root.wm_attributes("-alpha", p / 100),
            )
        menu.add_cascade(label="Opacity", menu=sub)
        menu.add_separator()
        menu.add_command(label="Quit Waypoint", command=self.root.destroy)
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Ask the detector for the active project and refresh the display."""
        project = self.detector.detect()
        self._refresh(project)
        self.root.after(self.poll_ms, self._poll)

    def _refresh(self, project: Optional[dict]) -> None:
        if project:
            color = project.get("color", "#7e3af2")
            self._dot_cv.itemconfig(self._dot, fill=color)
            self._lbl_name.config(text=project["name"])
            self._lbl_status.config(text="● active", fg=color)
            self.accent.config(bg=color)
        else:
            idle = "#4a4a6a"
            self._dot_cv.itemconfig(self._dot, fill=idle)
            self._lbl_name.config(text="Waypoint")
            self._lbl_status.config(text="no project detected", fg="#64748b")
            self.accent.config(bg=idle)
