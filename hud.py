"""
hud.py — Context restoration HUD.

Always-visible panel showing all tracked workspaces at a glance.

Header
  Active workspace name + session duration.
  Example: ● Waypoint · 42m

Body
  Every tracked workspace with its resume hint.
  Example:
    ✓ Waypoint
      ↳ terminal detection
      CogPass Light
      ↳ execution cost
      SalzLab
      ↳ RSA analysis

Interaction
  Drag the panel to reposition.
  Click any workspace row to focus that terminal.
  Right-click for opacity / quit.
"""

import sys
import time
import tkinter as tk
from typing import Optional

from detector import Workspace
from logger import WorkspaceLogger, HintStore


# ── Palette ───────────────────────────────────────────────────────────────────
_TRANSP   = 'black'    # compositor key-colour → alpha-0 on macOS
_PILL     = '#2d2d2d'  # panel surface
_SEP      = '#484848'  # separator between header and list
_DOT      = '#32d74b'  # active dot + checkmark (system green)
_TXT_ON   = '#e8e8e8'  # active workspace name
_TXT_OFF  = '#8e8e93'  # inactive workspace names
_TXT_HINT = '#6e6e73'  # resume hint — visually subordinate
_HOVER    = '#3a3a3a'  # row hover fill

# ── Geometry ──────────────────────────────────────────────────────────────────
_W        = 180   # panel width
_HEADER_H = 36    # header row height
_ITEM_H   = 42    # height per workspace row (name + hint)
_PAD_B    = 6     # bottom padding inside panel
_R        = 14    # corner radius
_X_DOT    = 11    # x: ● in header
_X_HDR    = 23    # x: text in header
_X_CK     = 11    # x: ✓ checkmark in list
_X_NAME   = 23    # x: workspace name in list
_X_HINT   = 29    # x: ↳ hint (indented)

# y offsets within each workspace row
_Y_NAME_WITH_HINT = 13   # name center when a hint is present
_Y_HINT_ROW       = 28   # hint center

# ── Behaviour ─────────────────────────────────────────────────────────────────
_DRAG_PX = 4   # px movement before a press becomes a drag

# ── Platform fonts ────────────────────────────────────────────────────────────
if sys.platform == 'darwin':
    _F_DOT  = ('SF Pro Display', 7)
    _F_NAME = ('SF Pro Display', 12)
    _F_HINT = ('SF Pro Text',    10)
    _F_ROW  = ('SF Pro Text',    12)
    _F_CK   = ('SF Pro Text',    11)
else:
    _F_DOT  = ('Segoe UI',  7)
    _F_NAME = ('Segoe UI', 11)
    _F_HINT = ('Segoe UI',  9)
    _F_ROW  = ('Segoe UI', 11)
    _F_CK   = ('Segoe UI', 10)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rrect(cv: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kw) -> None:
    pts = [
        x1+r, y1,    x2-r, y1,
        x2,   y1,    x2,   y1+r,
        x2,   y2-r,  x2,   y2,
        x2-r, y2,    x1+r, y2,
        x1,   y2,    x1,   y2-r,
        x1,   y1+r,  x1,   y1,
    ]
    cv.create_polygon(pts, smooth=True, **kw)


def _fmt_duration(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 1:
        return "< 1m"
    if m < 60:
        return f"{m}m"
    h, rem = divmod(m, 60)
    return f"{h}h {rem}m" if rem else f"{h}h"


# ── HUD ───────────────────────────────────────────────────────────────────────

class HUD:
    def __init__(self, root: tk.Tk, config: dict, detector) -> None:
        self.root     = root
        self.detector = detector
        self.poll_ms  = int(config.get('poll_interval', 2) * 1000)
        self.position = config.get('position', 'bottom-right')
        self._opacity = float(config.get('opacity', 0.82))
        self._logger  = WorkspaceLogger()
        self._hints   = HintStore()

        self._current_name: Optional[str]    = None
        self._last_active_name: Optional[str] = None
        self._context_since: float           = time.time()
        self._workspaces: list[Workspace]    = []
        self._hover_name: Optional[str]      = None

        self._px = self._py = 0
        self._ox = self._oy = 0
        self._dragged: bool = False

        self._init_window()
        self._init_canvas()
        self._poll()

    # ── Window ────────────────────────────────────────────────────────────────

    def _init_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.wm_attributes('-topmost', True)
        self.root.wm_attributes('-alpha', self._opacity)
        try:
            self.root.wm_attributes('-transparent', True)
            self.root.configure(bg=_TRANSP)
            self._transp = True
        except tk.TclError:
            self.root.configure(bg=_PILL)
            self._transp = False
        self._set_geometry(self._full_h())

    def _full_h(self) -> int:
        n = len(self._workspaces)
        return _HEADER_H if n == 0 else _HEADER_H + 1 + n * _ITEM_H + _PAD_B

    def _set_geometry(self, h: int) -> None:
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            if x == 0 and y == 0:
                raise ValueError
        except Exception:
            x, y = self._default_xy(h)
        self.root.geometry(f'{_W}x{h}+{x}+{y}')

    def _default_xy(self, h: int) -> tuple[int, int]:
        sw, sh, m = self.root.winfo_screenwidth(), self.root.winfo_screenheight(), 16
        return {
            'top-left':     (m,        40),
            'top-right':    (sw-_W-m,  40),
            'bottom-left':  (m,        sh-h-40),
            'bottom-right': (sw-_W-m,  sh-h-40),
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
        h = self._full_h()
        self._set_geometry(h)

        cv = self._cv
        cv.delete('all')
        _rrect(cv, 0, 0, _W, h, _R, fill=_PILL, outline='', width=0)

        # Header: ● WorkspaceName · duration
        cur = self._active()
        cy  = _HEADER_H // 2
        if cur:
            elapsed     = time.time() - self._context_since
            header_text = f"{cur.name} · {_fmt_duration(elapsed)}"
        else:
            header_text = '—'
        cv.create_text(_X_DOT, cy, anchor='w',
                       text='●', fill=_DOT, font=_F_DOT)
        cv.create_text(_X_HDR, cy, anchor='w',
                       text=header_text,
                       fill=_TXT_ON if cur else _TXT_OFF, font=_F_NAME)

        if not self._workspaces:
            return

        cv.create_line(_R+2, _HEADER_H, _W-_R-2, _HEADER_H,
                       fill=_SEP, width=0.5)

        iy = _HEADER_H + 1
        for ws in self._workspaces:
            self._draw_row(ws, iy)
            iy += _ITEM_H

    def _draw_row(self, ws: Workspace, y: int) -> None:
        cv   = self._cv
        tag  = f'row::{ws.name}'
        live = ws.name == self._current_name
        hot  = ws.name == self._hover_name
        hint = self._hints.get(ws.name)

        # Shift name up when a hint is present so both lines sit comfortably
        name_cy = y + (_Y_NAME_WITH_HINT if hint else _ITEM_H // 2)
        hint_cy = y + _Y_HINT_ROW

        if hot:
            cv.create_rectangle(
                _R//2, y+1, _W-_R//2, y+_ITEM_H-1,
                fill=_HOVER, outline='', tags=tag,
            )
        if live:
            cv.create_text(_X_CK, name_cy, anchor='w',
                           text='✓', fill=_DOT, font=_F_CK, tags=tag)
        cv.create_text(_X_NAME, name_cy, anchor='w',
                       text=ws.name,
                       fill=_TXT_ON if live else _TXT_OFF,
                       font=_F_ROW, tags=tag)
        if hint:
            cv.create_text(_X_HINT, hint_cy, anchor='w',
                           text=f"↳ {hint}",
                           fill=_TXT_HINT, font=_F_HINT, tags=tag)

        # Full-row transparent hit area on top for reliable click/hover
        cv.create_rectangle(0, y, _W, y+_ITEM_H,
                            fill='', outline='', tags=(tag, 'rows'))
        cv.tag_bind(tag, '<Enter>',
                    lambda e, n=ws.name: self._row_enter(n))
        cv.tag_bind(tag, '<Leave>',
                    lambda e, n=ws.name: self._row_leave(n))
        cv.tag_bind(tag, '<ButtonRelease-1>',
                    lambda e, n=ws.name: self._row_click(n))

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
        pass  # rows handle their own clicks; drag is handled in _drag

    def _row_enter(self, name: str) -> None:
        if self._hover_name != name:
            self._hover_name = name
            self._redraw()

    def _row_leave(self, name: str) -> None:
        if self._hover_name == name:
            self._hover_name = None
            self._redraw()

    def _row_click(self, name: str) -> None:
        if self._dragged:
            return
        ws = next((w for w in self._workspaces if w.name == name), None)
        if ws:
            self.detector.focus(ws)
        self._current_name     = name
        self._context_since    = time.time()
        self._last_active_name = name
        self._redraw()

    def _active(self) -> Optional[Workspace]:
        if not self._workspaces:
            return None
        if self._current_name:
            m = next((w for w in self._workspaces if w.name == self._current_name), None)
            if m:
                return m
        return self._workspaces[0]

    # ── Context menu ─────────────────────────────────────────────────────────

    def _ctx_menu(self, e: tk.Event) -> None:
        m = tk.Menu(self.root, tearoff=0,
                    bg='#1a1a1a', fg='#c0c0c0',
                    activebackground='#2a2a2a', activeforeground='#f0f0f0',
                    font=('SF Pro Text', 11), bd=0)
        sub = tk.Menu(m, tearoff=0, bg='#1a1a1a', fg='#c0c0c0',
                      activebackground='#2a2a2a', activeforeground='#f0f0f0')
        for pct in [100, 90, 82, 72, 60]:
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
        self._workspaces = workspaces

        # Keep _current_name pointing at a workspace that still exists
        valid = {ws.name for ws in workspaces}
        if self._current_name not in valid:
            self._current_name = workspaces[0].name if workspaces else None

        # Reset duration timer when the active workspace changes
        active = self._active()
        if active and active.name != self._last_active_name:
            self._context_since    = time.time()
            self._last_active_name = active.name

        # Refresh hints for every visible workspace so the list stays current
        for ws in workspaces:
            self._hints.update_from_workspace(ws)

        self._redraw()
        self.root.after(self.poll_ms, self._poll)

    def _quit(self) -> None:
        self._logger.shutdown()
        self.root.destroy()
