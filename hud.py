"""
hud.py — Ambient workspace indicator.

Collapsed (default)
  28px pill: ● workspace-name.
  Entire surface is a drag target. Nothing is accidentally clickable.

Expanded (on click within header zone)
  Pill grows downward into a compact switcher list.
  Click a row → focus terminal → animate back to pill.
  Auto-collapses after 4 s of inactivity.

Animation
  Height interpolation over ~120 ms (8 frames × 15 ms, cubic ease-out).
  Expanding: items revealed progressively as pill grows downward.
  Collapsing: items hidden progressively as pill shrinks upward.

Drag vs click
  Movement > 4 px before release = drag; moves window.
  Press + release in place within header zone = click; toggles expand.
  Row tag_bind fires before the canvas-level binding; _eat_release
  prevents the canvas handler from also seeing the same release event.
"""

import sys
import tkinter as tk
from typing import Callable, Optional

from detector import Workspace
from logger import WorkspaceLogger


# ── Palette ───────────────────────────────────────────────────────────────────
_TRANSP  = 'black'    # maps to true alpha-0 transparency on macOS
_PILL    = '#2d2d2d'  # surface — lighter than near-black, lets translucency read
_SEP     = '#484848'  # 0.5px separator between header and list
_DOT     = '#32d74b'  # active indicator + checkmark (system green)
_TXT_ON  = '#e8e8e8'  # current workspace name
_TXT_OFF = '#8e8e93'  # inactive workspace names
_HOVER   = '#3a3a3a'  # item hover fill

# ── Geometry ──────────────────────────────────────────────────────────────────
_W      = 150   # pill width
_PILL_H = 28    # collapsed height — r=14 gives a true pill (semicircle ends)
_ITEM_H = 28    # expanded row height
_R      = 14    # corner radius
_X_DOT  = 11    # x: ● indicator
_X_HDR  = 23    # x: name in collapsed header
_X_CK   = 11    # x: ✓ checkmark
_X_ROW  = 24    # x: name in expanded rows

# ── Behaviour ─────────────────────────────────────────────────────────────────
_DRAG_PX  = 4     # px movement threshold for drag vs click
_CLOSE_MS = 4000  # auto-collapse after this many ms

# ── Animation ─────────────────────────────────────────────────────────────────
_ANIM_N  = 8     # frame count
_ANIM_MS = 15    # ms per frame  →  ~120 ms total

# ── Platform fonts ────────────────────────────────────────────────────────────
if sys.platform == 'darwin':
    _F_DOT  = ('SF Pro Display', 7)
    _F_NAME = ('SF Pro Display', 12)
    _F_ROW  = ('SF Pro Text',    12)
    _F_CK   = ('SF Pro Text',    11)
else:
    _F_DOT  = ('Segoe UI',  7)
    _F_NAME = ('Segoe UI', 11)
    _F_ROW  = ('Segoe UI', 11)
    _F_CK   = ('Segoe UI', 10)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ease_out(t: float) -> float:
    """Cubic ease-out: fast start, decelerate to rest."""
    return 1 - (1 - t) ** 3


def _rrect(cv: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kw) -> None:
    """Smooth rounded rectangle via B-spline polygon with smooth=True."""
    pts = [
        x1+r, y1,    x2-r, y1,
        x2,   y1,    x2,   y1+r,
        x2,   y2-r,  x2,   y2,
        x2-r, y2,    x1+r, y2,
        x1,   y2,    x1,   y2-r,
        x1,   y1+r,  x1,   y1,
    ]
    cv.create_polygon(pts, smooth=True, **kw)


# ── HUD ───────────────────────────────────────────────────────────────────────

class HUD:
    def __init__(self, root: tk.Tk, config: dict, detector) -> None:
        self.root     = root
        self.detector = detector
        self.poll_ms  = int(config.get('poll_interval', 2) * 1000)
        self.position = config.get('position', 'bottom-right')
        self._opacity = float(config.get('opacity', 0.82))
        self._logger  = WorkspaceLogger()

        self._expanded: bool              = False
        self._current_name: Optional[str] = None
        self._workspaces: list[Workspace] = []
        self._hover_name: Optional[str]   = None
        self._close_job                   = None
        self._anim_job                    = None
        self._animating: bool             = False
        self._eat_release: bool           = False

        self._px = self._py = 0    # press position (for drag detection)
        self._ox = self._oy = 0    # window offset at press time
        self._dragged: bool = False

        self._init_window()
        self._init_canvas()
        self._poll()

    # ── Window ────────────────────────────────────────────────────────────────

    def _init_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.wm_attributes('-topmost', True)
        self.root.wm_attributes('-alpha', self._opacity)
        # On macOS, -transparent makes pixels painted with the configured bg
        # colour fully transparent in the compositor.  Other pixels (the pill)
        # render at the -alpha level, creating genuine translucency.
        try:
            self.root.wm_attributes('-transparent', True)
            self.root.configure(bg=_TRANSP)
            self._transp = True
        except tk.TclError:
            self.root.configure(bg=_PILL)
            self._transp = False
        self._set_geometry(_PILL_H)

    def _full_h(self) -> int:
        """Target height when expanded (or collapsed if not expanded)."""
        if not self._expanded or not self._workspaces:
            return _PILL_H
        return _PILL_H + 1 + len(self._workspaces) * _ITEM_H + 4

    def _set_geometry(self, h: int) -> None:
        """Set window height to h, preserving current x/y position."""
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

    def _redraw(self, anim_h: Optional[int] = None) -> None:
        """
        Redraw the canvas.
        anim_h=None  → full target height (settled state).
        anim_h=n     → animation frame at intermediate height n; only draw
                        items whose top edge falls within n so they appear
                        progressively as the pill expands.
        """
        h = anim_h if anim_h is not None else self._full_h()
        self._set_geometry(h)

        cv = self._cv
        cv.delete('all')

        # Background pill at current height — no visible border, shape alone defines it
        _rrect(cv, 0, 0, _W, h, _R, fill=_PILL, outline='', width=0)

        # Header: ● workspace-name (always visible)
        cy  = _PILL_H // 2
        cur = self._active()
        cv.create_text(_X_DOT, cy, anchor='w',
                       text='●', fill=_DOT, font=_F_DOT)
        cv.create_text(_X_HDR, cy, anchor='w',
                       text=cur.name if cur else '—',
                       fill=_TXT_ON if cur else _TXT_OFF, font=_F_NAME)

        if not self._expanded or not self._workspaces:
            return

        # Separator — only once the pill has grown past the header
        if anim_h is None or anim_h > _PILL_H + 2:
            cv.create_line(_R+2, _PILL_H, _W-_R-2, _PILL_H,
                           fill=_SEP, width=0.5)

        # Rows — draw only those whose top edge fits within the current height
        iy = _PILL_H + 1
        for ws in self._workspaces:
            if anim_h is not None and iy >= anim_h:
                break
            self._draw_row(ws, iy)
            iy += _ITEM_H

    def _draw_row(self, ws: Workspace, y: int) -> None:
        cv   = self._cv
        tag  = f'row::{ws.name}'
        cy   = y + _ITEM_H // 2
        live = ws.name == self._current_name
        hot  = ws.name == self._hover_name

        if hot:
            cv.create_rectangle(
                _R//2, y+1, _W-_R//2, y+_ITEM_H-1,
                fill=_HOVER, outline='', tags=tag,
            )
        if live:
            cv.create_text(_X_CK, cy, anchor='w',
                           text='✓', fill=_DOT, font=_F_CK, tags=tag)
        cv.create_text(_X_ROW, cy, anchor='w',
                       text=ws.name,
                       fill=_TXT_ON if live else _TXT_OFF,
                       font=_F_ROW, tags=tag)

        # Full-row transparent hit area — placed last so it sits on top
        cv.create_rectangle(0, y, _W, y+_ITEM_H,
                             fill='', outline='', tags=(tag, 'rows'))

        cv.tag_bind(tag, '<Enter>',
                    lambda e, n=ws.name: self._row_enter(n))
        cv.tag_bind(tag, '<Leave>',
                    lambda e, n=ws.name: self._row_leave(n))
        # ButtonRelease (not Button-1) so _dragged is known before we act
        cv.tag_bind(tag, '<ButtonRelease-1>',
                    lambda e, n=ws.name: self._row_click(n))

    # ── Animation ─────────────────────────────────────────────────────────────

    def _animate(self, from_h: int, to_h: int,
                  step: int = 0, on_done: Optional[Callable] = None) -> None:
        self._animating = True

        if step > _ANIM_N:
            self._animating = False
            if on_done:
                on_done()       # caller draws final settled state
            else:
                self._redraw()  # expand: draw full content at target height
            return

        t = _ease_out(step / _ANIM_N)
        h = int(from_h + t * (to_h - from_h))
        self._redraw(anim_h=h)

        self._anim_job = self.root.after(
            _ANIM_MS,
            lambda: self._animate(from_h, to_h, step + 1, on_done),
        )

    def _cancel_anim(self) -> None:
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None
        self._animating = False

    # ── Expand / collapse ─────────────────────────────────────────────────────

    def _toggle(self) -> None:
        self._close() if self._expanded else self._open()

    def _open(self) -> None:
        self._cancel_anim()
        self._expanded   = True
        self._hover_name = None
        target = self._full_h()
        # Animate from pill height up to expanded height.
        # Step 0 draws at _PILL_H (header only), subsequent steps reveal items.
        self._animate(_PILL_H, target)
        self._sched_close()

    def _close(self) -> None:
        self._cancel_anim()
        self._cancel_close()
        start = self.root.winfo_height()

        def _finish() -> None:
            self._expanded   = False
            self._hover_name = None
            self._redraw()  # _expanded now False → draws at _PILL_H

        self._animate(start, _PILL_H, on_done=_finish)

    def _sched_close(self) -> None:
        self._cancel_close()
        self._close_job = self.root.after(_CLOSE_MS, self._close)

    def _cancel_close(self) -> None:
        if self._close_job:
            self.root.after_cancel(self._close_job)
            self._close_job = None

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
        # Only toggle when releasing within the header strip
        if e.y <= _PILL_H:
            self._toggle()

    def _row_enter(self, name: str) -> None:
        if self._hover_name != name and not self._animating:
            self._hover_name = name
            self._redraw()

    def _row_leave(self, name: str) -> None:
        if self._hover_name == name and not self._animating:
            self._hover_name = None
            self._redraw()

    def _row_click(self, name: str) -> None:
        # tag_bind fires before canvas-level binding; flag absorbs the
        # canvas release so _release() doesn't also see it as a header tap.
        self._eat_release = True
        if not self._dragged:
            ws = next((w for w in self._workspaces if w.name == name), None)
            if ws:
                self.detector.focus(ws)
            self._current_name = name
            self._close()

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

        prev = [ws.name for ws in self._workspaces]
        nxt  = [ws.name for ws in workspaces]
        self._workspaces = workspaces

        # Keep _current_name pointing at a workspace that still exists
        if self._current_name not in {ws.name for ws in workspaces}:
            self._current_name = workspaces[0].name if workspaces else None

        # Redraw on change, but never interrupt an in-progress animation
        if prev != nxt and not self._animating:
            self._redraw()

        self.root.after(self.poll_ms, self._poll)

    def _quit(self) -> None:
        self._logger.shutdown()
        self.root.destroy()
