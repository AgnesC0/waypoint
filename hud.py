"""
hud.py — Ambient workspace indicator.

Two states:
  Collapsed (default) — a 30px pill showing ● current workspace.
                        The entire pill is a drag target. Nothing is clickable.
  Expanded (on click) — pill grows into a compact switcher list.
                        Click a row to focus that terminal and collapse.
                        Auto-collapses after 4 seconds.

Drag vs click is disambiguated by a movement threshold: press + move > 4px
is a drag; press + release in place is a click (toggle expand).
"""

import sys
import tkinter as tk
from typing import Optional

from detector import Workspace
from logger import WorkspaceLogger


# ── Palette ───────────────────────────────────────────────────────────────────
_TRANSP    = 'black'    # mapped to true transparency on macOS via -transparent
_PILL      = '#1c1c1e'  # pill surface (macOS dark systemBackground)
_EDGE      = '#3a3a3c'  # 1px subtle outline
_SEP       = '#38383a'  # divider between header and list
_DOT       = '#32d74b'  # active dot + checkmark (system green)
_TXT_ON    = '#f2f2f7'  # current workspace name
_TXT_OFF   = '#8e8e93'  # inactive workspace names
_HOVER     = '#2c2c2e'  # row hover fill

# ── Geometry ──────────────────────────────────────────────────────────────────
_W      = 160   # pill width
_PILL_H = 30    # collapsed height
_ITEM_H = 30    # expanded row height
_R      = 12    # corner radius
_PAD    = 12    # left padding for all text

# ── Behaviour ─────────────────────────────────────────────────────────────────
_DRAG_PX  = 4     # movement threshold to distinguish drag from click
_CLOSE_MS = 4000  # auto-collapse delay (ms)

# ── Platform fonts ────────────────────────────────────────────────────────────
if sys.platform == 'darwin':
    _F_NAME  = ('SF Pro Display', 12)
    _F_LIST  = ('SF Pro Text',    12)
    _F_CHECK = ('SF Pro Text',    11)
    _F_DOT   = ('SF Pro Display',  8)
else:
    _F_NAME  = ('Segoe UI', 11)
    _F_LIST  = ('Segoe UI', 11)
    _F_CHECK = ('Segoe UI', 10)
    _F_DOT   = ('Segoe UI',  8)


# ── Rounded-rectangle helper ──────────────────────────────────────────────────

def _rrect(cv: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kw):
    """Smooth rounded rectangle via B-spline polygon."""
    pts = [
        x1+r, y1,   x2-r, y1,    # top
        x2,   y1,   x2,   y1+r,  # top-right
        x2,   y2-r, x2,   y2,    # right
        x2-r, y2,   x1+r, y2,    # bottom
        x1,   y2,   x1,   y2-r,  # bottom-left
        x1,   y1+r, x1,   y1,    # left
    ]
    cv.create_polygon(pts, smooth=True, **kw)


# ── HUD ───────────────────────────────────────────────────────────────────────

class HUD:
    def __init__(self, root: tk.Tk, config: dict, detector) -> None:
        self.root     = root
        self.detector = detector
        self.poll_ms  = int(config.get('poll_interval', 2) * 1000)
        self.position = config.get('position', 'bottom-right')
        self._opacity = float(config.get('opacity', 0.88))
        self._logger  = WorkspaceLogger()

        # Display state
        self._expanded: bool             = False
        self._current_name: Optional[str] = None
        self._workspaces: list[Workspace] = []
        self._hover_name: Optional[str]   = None
        self._close_job                   = None

        # Drag state
        self._px = self._py = 0
        self._ox = self._oy = 0
        self._dragged = False
        self._eat_release = False  # absorbs canvas release after a row click

        self._init_window()
        self._init_canvas()
        self._poll()

    # ── Window ────────────────────────────────────────────────────────────────

    def _init_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.wm_attributes('-topmost', True)
        self.root.wm_attributes('-alpha', self._opacity)
        # True per-pixel transparency on macOS: pixels painted with bg colour
        # are fully composited against the desktop, not the window surface.
        try:
            self.root.wm_attributes('-transparent', True)
            self.root.configure(bg=_TRANSP)
            self._transp = True
        except tk.TclError:
            self.root.configure(bg=_PILL)
            self._transp = False
        self._refit()

    def _height(self) -> int:
        if not self._expanded or not self._workspaces:
            return _PILL_H
        return _PILL_H + 1 + len(self._workspaces) * _ITEM_H + 4

    def _refit(self) -> None:
        h = self._height()
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            if x == 0 and y == 0:
                raise ValueError
        except Exception:
            x, y = self._initial_xy(h)
        self.root.geometry(f'{_W}x{h}+{x}+{y}')

    def _initial_xy(self, h: int) -> tuple[int, int]:
        sw, sh, m = self.root.winfo_screenwidth(), self.root.winfo_screenheight(), 16
        return {
            'top-left':     (m,       40),
            'top-right':    (sw-_W-m, 40),
            'bottom-left':  (m,       sh-h-40),
            'bottom-right': (sw-_W-m, sh-h-40),
        }.get(self.position, (sw-_W-m, sh-h-40))

    # ── Canvas ────────────────────────────────────────────────────────────────

    def _init_canvas(self) -> None:
        bg = _TRANSP if self._transp else _PILL
        self._cv = tk.Canvas(self.root, bg=bg, highlightthickness=0, bd=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self._cv.bind('<Button-1>',        self._press)
        self._cv.bind('<B1-Motion>',       self._drag)
        self._cv.bind('<ButtonRelease-1>', self._release)
        self._cv.bind('<Button-2>',        self._ctx_menu)
        self._cv.bind('<Button-3>',        self._ctx_menu)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        self._refit()
        cv = self._cv
        cv.delete('all')
        h = self._height()

        # Background pill — the only visible shape; everything else is text
        _rrect(cv, 0, 0, _W, h, _R, fill=_PILL, outline=_EDGE, width=0.5)

        # Header: ● workspace-name
        cy  = _PILL_H // 2
        cur = self._active()
        cv.create_text(_PAD,      cy, anchor='w', text='●',
                       fill=_DOT, font=_F_DOT)
        cv.create_text(_PAD + 13, cy, anchor='w',
                       text=cur.name if cur else '—',
                       fill=_TXT_ON if cur else _TXT_OFF, font=_F_NAME)

        if not self._expanded or not self._workspaces:
            return

        # Separator
        cv.create_line(_R+2, _PILL_H, _W-_R-2, _PILL_H,
                       fill=_SEP, width=0.5)

        # Workspace rows
        y = _PILL_H + 1
        for ws in self._workspaces:
            self._draw_row(ws, y)
            y += _ITEM_H

    def _draw_row(self, ws: Workspace, y: int) -> None:
        cv   = self._cv
        tag  = f'row::{ws.name}'
        cy   = y + _ITEM_H // 2
        live = ws.name == self._current_name
        hot  = ws.name == self._hover_name

        if hot:
            cv.create_rectangle(_R//2, y+1, _W-_R//2, y+_ITEM_H-1,
                                 fill=_HOVER, outline='', tags=tag)
        if live:
            cv.create_text(_PAD, cy, anchor='w', text='✓',
                           fill=_DOT, font=_F_CHECK, tags=tag)
        cv.create_text(_PAD + 16, cy, anchor='w', text=ws.name,
                       fill=_TXT_ON if live else _TXT_OFF,
                       font=_F_LIST, tags=tag)

        # Transparent full-row hit area — must be last so it sits on top
        cv.create_rectangle(0, y, _W, y+_ITEM_H,
                             fill='', outline='', tags=(tag, 'rows'))

        cv.tag_bind(tag, '<Enter>',          lambda e, n=ws.name: self._row_enter(n))
        cv.tag_bind(tag, '<Leave>',          lambda e, n=ws.name: self._row_leave(n))
        # Use ButtonRelease so we can check self._dragged before acting
        cv.tag_bind(tag, '<ButtonRelease-1>', lambda e, n=ws.name: self._row_click(n))

    # ── Interaction ───────────────────────────────────────────────────────────

    def _press(self, e: tk.Event) -> None:
        self._px, self._py = e.x_root, e.y_root
        self._ox = e.x_root - self.root.winfo_x()
        self._oy = e.y_root - self.root.winfo_y()
        self._dragged = False

    def _drag(self, e: tk.Event) -> None:
        if abs(e.x_root-self._px) > _DRAG_PX or abs(e.y_root-self._py) > _DRAG_PX:
            self._dragged = True
        if self._dragged:
            self.root.geometry(f'+{e.x_root-self._ox}+{e.y_root-self._oy}')

    def _release(self, e: tk.Event) -> None:
        if self._eat_release:
            self._eat_release = False
            return
        if self._dragged:
            return
        # Toggle only when releasing in the header zone
        if e.y <= _PILL_H:
            self._toggle()

    def _row_enter(self, name: str) -> None:
        if self._hover_name != name:
            self._hover_name = name
            self._redraw()

    def _row_leave(self, name: str) -> None:
        if self._hover_name == name:
            self._hover_name = None
            self._redraw()

    def _row_click(self, name: str) -> None:
        # tag_bind fires before the canvas-level binding; eat the upcoming
        # canvas release so _release() doesn't also see it as a header tap.
        self._eat_release = True
        if not self._dragged:
            ws = next((w for w in self._workspaces if w.name == name), None)
            if ws:
                self.detector.focus(ws)
            self._current_name = name
            self._close()

    # ── Expand / collapse ─────────────────────────────────────────────────────

    def _toggle(self) -> None:
        self._close() if self._expanded else self._open()

    def _open(self) -> None:
        self._expanded   = True
        self._hover_name = None
        self._redraw()
        self._sched_close()

    def _close(self) -> None:
        self._expanded   = False
        self._hover_name = None
        self._cancel_close()
        self._redraw()

    def _sched_close(self) -> None:
        self._cancel_close()
        self._close_job = self.root.after(_CLOSE_MS, self._close)

    def _cancel_close(self) -> None:
        if self._close_job:
            self.root.after_cancel(self._close_job)
            self._close_job = None

    def _active(self) -> Optional[Workspace]:
        if not self._workspaces:
            return None
        if self._current_name:
            match = next((w for w in self._workspaces if w.name == self._current_name), None)
            if match:
                return match
        return self._workspaces[0]

    # ── Context menu ─────────────────────────────────────────────────────────

    def _ctx_menu(self, e: tk.Event) -> None:
        m = tk.Menu(self.root, tearoff=0,
                    bg='#1a1a1a', fg='#c0c0c0',
                    activebackground='#2a2a2a', activeforeground='#f0f0f0',
                    font=('SF Pro Text', 11), bd=0)
        sub = tk.Menu(m, tearoff=0, bg='#1a1a1a', fg='#c0c0c0',
                      activebackground='#2a2a2a', activeforeground='#f0f0f0')
        for pct in [100, 90, 75, 50]:
            sub.add_command(label=f'{pct}%',
                            command=lambda p=pct: self.root.wm_attributes('-alpha', p/100))
        m.add_cascade(label='Opacity', menu=sub)
        m.add_separator()
        m.add_command(label='Quit', command=self._quit)
        m.tk_popup(e.x_root, e.y_root)

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        workspaces = self.detector.detect()
        self._logger.update(workspaces)

        prev = [ws.name for ws in self._workspaces]
        nxt  = [ws.name for ws in workspaces]
        self._workspaces = workspaces

        # Keep _current_name pointing at a workspace that still exists
        if self._current_name not in {ws.name for ws in workspaces}:
            self._current_name = workspaces[0].name if workspaces else None

        if prev != nxt:
            self._redraw()

        self.root.after(self.poll_ms, self._poll)

    def _quit(self) -> None:
        self._logger.shutdown()
        self.root.destroy()
