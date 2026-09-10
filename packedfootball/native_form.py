"""Full-page HTML form takeover, for text entry on the browser build.

Why this exists, replacing an earlier per-field overlay attempt: pygame's
TEXTINPUT events need a physical keyboard (broken on mobile browsers), and
both window.prompt() and a script-triggered .focus() on an overlay <input>
need to run synchronously inside the browser's own "trusted user gesture"
window to summon the on-screen keyboard -- by the time pygame's event queue
delivers a tap to Python, that window has already closed, so both got
silently blocked (this is what happened with window.prompt()).

The next attempt overlaid a real <input> directly on the canvas so the
user's own tap would focus it natively. That works in principle, but it
repositioned the input every frame to track the pygame rect against the
canvas's live on-screen size -- and iOS Safari resizes the visual viewport
unpredictably while the on-screen keyboard animates open, so a
continuously-recalculated `position: fixed` element fighting that animation
is exactly the combination Safari handles worst. Reported result: the input
visibly jumping around and not reliably taking focus.

This sidesteps both problems at once: hide the canvas, show a completely
static, full-page HTML form -- no per-frame repositioning, no interaction
with the canvas's coordinate system or scaling at all, just a normal
webpage doing what normal webpages are extremely good at.
"""

from __future__ import annotations

import json
import sys

_IS_EMSCRIPTEN = sys.platform == "emscripten"

_FORM_JS = r"""
window.PFForm = window.PFForm || {};
window.PFForm._pending = window.PFForm._pending || {};

window.PFForm.ensure = function (formId, html) {
    var existing = document.getElementById(formId);
    if (existing) return existing;
    var overlay = document.createElement('div');
    overlay.id = formId;
    overlay.style.cssText =
        'position:fixed;top:0;left:0;right:0;bottom:0;background:#1e1e28;z-index:999999;' +
        'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
        'font-family:sans-serif;color:#e6e6e6;padding:24px;box-sizing:border-box;overflow:auto;';
    overlay.innerHTML = html;
    document.body.appendChild(overlay);

    // SDL2's Emscripten runtime listens for keyboard events across the
    // whole page (so pygame gets them no matter what's nominally focused)
    // and typically calls preventDefault() to stop default browser key
    // behavior -- which silently blocks typing into a real focused <input>
    // too: focus still works, but the character never lands. Stop these
    // events from ever reaching that page-level listener while the user is
    // typing into one of our own fields, in both the capture and bubble
    // phases (belt and suspenders, since it's not visible from here which
    // phase SDL's own listener uses).
    var stopIt = function (e) { e.stopPropagation(); };
    overlay.querySelectorAll('input').forEach(function (input) {
        ["keydown", "keyup", "keypress", "input", "beforeinput"].forEach(function (type) {
            input.addEventListener(type, stopIt, true);
            input.addEventListener(type, stopIt, false);
        });
    });

    return overlay;
};
window.PFForm.show = function (formId) {
    var el = document.getElementById(formId);
    if (el) el.style.display = 'flex';
    var canvas = document.getElementById('canvas');
    if (canvas) canvas.style.visibility = 'hidden';
};
window.PFForm.hide = function (formId) {
    var el = document.getElementById(formId);
    if (el) el.style.display = 'none';
    var canvas = document.getElementById('canvas');
    if (canvas) canvas.style.visibility = 'visible';
};
window.PFForm.setError = function (formId, msg) {
    var el = document.getElementById(formId + '-error');
    if (el) el.textContent = msg || '';
};
window.PFForm.setBusy = function (formId, busy) {
    var el = document.getElementById(formId);
    if (!el) return;
    el.querySelectorAll('button').forEach(function (b) { b.disabled = !!busy; });
};
window.PFForm.take = function (formId) {
    var p = window.PFForm._pending[formId];
    window.PFForm._pending[formId] = null;
    return p ? JSON.stringify(p) : null;
};
"""

_js_ready = False


def _ensure_js() -> None:
    global _js_ready
    if _js_ready:
        return
    import platform  # pygbag's browser-interop shim, not stdlib platform

    platform.window.eval(_FORM_JS)
    _js_ready = True


def show(form_id: str, html: str, wiring_js: str) -> None:
    """Creates (first call) and shows a full-page HTML form, hiding the canvas.

    `html` becomes the overlay's innerHTML. `wiring_js` is eval'd separately,
    every call -- innerHTML doesn't execute embedded <script> tags, so button
    behavior has to be attached this way; re-running it is harmless since it
    only ever does `element.onclick = ...` assignments, which replace rather
    than stack.
    """
    import platform

    _ensure_js()
    platform.window.PFForm.ensure(form_id, html)
    platform.window.eval(wiring_js)
    platform.window.PFForm.show(form_id)


def hide(form_id: str) -> None:
    if not _js_ready:
        return
    import platform

    platform.window.PFForm.hide(form_id)


def set_error(form_id: str, message: str) -> None:
    if not _js_ready:
        return
    import platform

    platform.window.PFForm.setError(form_id, message)


def set_busy(form_id: str, busy: bool) -> None:
    if not _js_ready:
        return
    import platform

    platform.window.PFForm.setBusy(form_id, busy)


def take_submission(form_id: str) -> dict | None:
    """Returns the submitted field values if the user tapped submit this
    frame, else None. Call once per frame while the form is showing."""
    if not _js_ready:
        return None
    import platform

    raw = platform.window.PFForm.take(form_id)
    return json.loads(raw) if raw else None
