Closes #182.

**Why:** #159 unchecks Split when a window leaves the split. This is the other way: when AJ snaps the windows into the split himself, the checkbox follows, so it always matches the screen.

**What changed**

| While Split is off | Result |
|---|---|
| wall snapped left, fleet terminal right, one monitor, still for 1 s | Split checks itself and saves on; nothing moves |
| reversed, 60/40, one window only, or two monitors | stays off |
| the layout was already there when Split went off | stays off until it is left and snapped again |

**Status:** ready for review.

| Check | Result |
|---|---|
| wall JS tests | 18 passed |
| Windows tests (real windows) | RESULT |

<details><summary>Details</summary>

- `split.rs`: `in_split` (pure, 8 px for a snap's rounding) and `snapped` (only a change into the layout counts). `watch::arm_snap` runs while Split is off: out-of-context WinEvent hooks on both windows' threads for move-size-end and location changes; each event restarts a 1 s thread timer, and the settled look reads DWM frame bounds, show state and the monitor. It shares the split watcher's generation, so a toggle, an unsplit or exit ends it.
- Armed when the wall loads with Split saved off, after an unsplit or a failed split, and after a window leaves the split. A hand-made split clears the saved placements, so turning it off moves nothing.
- `jump.rs`: `fleet_window_quiet` finds the fleet terminal without selecting its tab (the watcher must change nothing).
- The wall takes `{on: true, note}` on the same channel as the leave.
- Geometry is the signal: `IsWindowArranged` says a window is snapped but not where, and a split dragged into place by hand counts too ([IsWindowArranged](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindowarranged), [SetWinEventHook](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook), [DWMWA_EXTENDED_FRAME_BOUNDS](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute), [MonitorFromWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-monitorfromwindow)).
</details>

