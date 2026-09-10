"""The sign-in / registration screen: the one place in the game that turns
raw keyboard input into an authenticated Firebase session.
"""

from __future__ import annotations

import pygame

import native_form
from firebase_client import FirebaseClient, FirebaseError
from native_form import _IS_EMSCRIPTEN

FIELD_BG = (25, 25, 35)
FIELD_BORDER_ACTIVE = (80, 200, 80)
FIELD_BORDER_IDLE = (120, 120, 130)
TEXT_COLOR = (230, 230, 230)
PLACEHOLDER_COLOR = (110, 110, 120)
ERROR_COLOR = (230, 90, 90)

_FORM_ID = "pf-login-form"

_FORM_HTML = """
<h1 style="margin:0 0 4px;font-size:28px;">PACKED FOOTBALL</h1>
<p style="color:#ccc;margin:0 0 20px;font-size:14px;">Sign in to save your squad and play PvP</p>
<div id="pf-login-name-wrap" style="display:none;width:100%;max-width:320px;">
  <input id="pf-login-name" type="text" placeholder="display name"
         style="width:100%;box-sizing:border-box;padding:12px;margin-bottom:10px;
                border-radius:6px;border:1px solid #555;background:#191923;
                color:#e6e6e6;font-size:16px;">
</div>
<input id="pf-login-email" type="email" placeholder="email" autocomplete="username"
       style="width:100%;max-width:320px;box-sizing:border-box;padding:12px;margin-bottom:10px;
              border-radius:6px;border:1px solid #555;background:#191923;color:#e6e6e6;font-size:16px;">
<input id="pf-login-password" type="password" placeholder="password" autocomplete="current-password"
       style="width:100%;max-width:320px;box-sizing:border-box;padding:12px;margin-bottom:14px;
              border-radius:6px;border:1px solid #555;background:#191923;color:#e6e6e6;font-size:16px;">
<button id="pf-login-toggle" type="button"
        style="background:none;border:none;color:#8f8;margin-bottom:16px;font-size:14px;">
  New here? Register instead
</button>
<button id="pf-login-submit" type="button"
        style="width:100%;max-width:320px;padding:14px;border-radius:8px;border:2px solid #fff;
               background:#329632;color:#fff;font-size:18px;">
  Sign In
</button>
<div id="pf-login-form-error" style="color:#e65a5a;margin-top:14px;min-height:20px;font-size:14px;text-align:center;"></div>
"""

_FORM_WIRING_JS = """
(function () {
    var state = { mode: 'login' };
    function applyMode() {
        document.getElementById('pf-login-name-wrap').style.display = state.mode === 'register' ? 'block' : 'none';
        document.getElementById('pf-login-submit').textContent = state.mode === 'register' ? 'Register' : 'Sign In';
        document.getElementById('pf-login-toggle').textContent =
            state.mode === 'register' ? 'Already have an account? Sign in' : 'New here? Register instead';
    }
    document.getElementById('pf-login-toggle').onclick = function () {
        state.mode = state.mode === 'login' ? 'register' : 'login';
        applyMode();
    };
    document.getElementById('pf-login-submit').onclick = function () {
        window.PFForm._pending['pf-login-form'] = {
            mode: state.mode,
            email: document.getElementById('pf-login-email').value,
            password: document.getElementById('pf-login-password').value,
            display_name: document.getElementById('pf-login-name').value,
        };
    };
    applyMode();
})();
"""


def friendly_auth_error(exc: FirebaseError) -> str:
    """Turns an Identity Toolkit error code into something a player can read."""
    code = exc.identity_error_code or ""
    if code.startswith("WEAK_PASSWORD"):
        return "Password must be at least 6 characters."
    known = {
        "EMAIL_EXISTS": "That email is already registered. Try signing in instead.",
        "EMAIL_NOT_FOUND": "No account found for that email. Try registering instead.",
        "INVALID_PASSWORD": "Incorrect password.",
        "INVALID_LOGIN_CREDENTIALS": "Incorrect email or password.",
        "INVALID_EMAIL": "That doesn't look like a valid email address.",
        "USER_DISABLED": "This account has been disabled.",
        "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Try again in a bit.",
        "OPERATION_NOT_ALLOWED": "Email/password sign-in isn't enabled for this project yet.",
    }
    return known.get(code, f"Sign-in failed ({code or 'unknown error'}).")


class TextInput:
    """A single-line text field for the desktop build.

    Driven by pygame TEXTINPUT events -- desktop only. The browser build
    doesn't use this at all; see native_form.py and AuthScene's emscripten
    path below for why (mobile Safari and on-canvas text entry don't mix).

    Call handle_event() with every pygame event each frame, then draw().
    """

    def __init__(self, rect, placeholder: str = "", is_password: bool = False, max_length: int = 96):
        self.rect = pygame.Rect(rect)
        self.text = ""
        self.placeholder = placeholder
        self.is_password = is_password
        self.max_length = max_length
        self.active = False

    def handle_event(self, event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.TEXTINPUT and self.active:
            if len(self.text) < self.max_length:
                self.text += event.text
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]

    def draw(self, screen, font) -> None:
        border = FIELD_BORDER_ACTIVE if self.active else FIELD_BORDER_IDLE
        pygame.draw.rect(screen, FIELD_BG, self.rect, border_radius=6)
        pygame.draw.rect(screen, border, self.rect, 2, border_radius=6)

        shown = ("•" * len(self.text)) if self.is_password else self.text
        if shown:
            surf = font.render(shown, True, TEXT_COLOR)
        else:
            surf = font.render(self.placeholder, True, PLACEHOLDER_COLOR)
        screen.blit(surf, (self.rect.x + 10, self.rect.y + (self.rect.height - surf.get_height()) // 2))


class AuthScene:
    """Renders the sign-in/register form and drives the Firebase calls behind it.

    Two completely different UIs depending on platform:
      - Desktop: the pygame-drawn TextInput fields below, unchanged from before.
      - Browser: a full-page native HTML form (native_form.py) that takes over
        the whole screen while showing, since that's the only approach that's
        proven reliable on mobile Safari -- see native_form.py's docstring
        for the two things that were tried before this and didn't work.

    Usage from main.py's per-frame loop:

        result = await auth_scene.update(screen, events, mouse_pos, mouse_clicked,
                                          font_large, font_btn, font_small, draw_button)
        if result is not None:
            # signed in this frame -- result["display_name"] is the name the
            # player chose at registration, or None for login/guest (in which
            # case the caller should fall back to whatever's already saved).
            ...
    """

    def __init__(self, client: FirebaseClient):
        self.client = client
        self.mode = "login"  # or "register" -- desktop path only
        self.email = TextInput((490, 260, 300, 44), placeholder="email")
        self.password = TextInput((490, 320, 300, 44), placeholder="password", is_password=True)
        self.name = TextInput((490, 380, 300, 44), placeholder="display name")
        self.error = ""
        self.busy = False
        self._native_shown = False

    def hide_native_inputs(self) -> None:
        """Hides the native form overlay, if it's showing. Call before leaving this scene."""
        if self._native_shown:
            native_form.hide(_FORM_ID)
            self._native_shown = False

    async def update(self, screen, events, mouse_pos, mouse_clicked, font_large, font_btn, font_small, draw_button):
        if _IS_EMSCRIPTEN:
            return await self._update_native()
        return await self._update_desktop(screen, events, mouse_pos, mouse_clicked, font_large, font_btn, font_small, draw_button)

    # -- browser: full-page native HTML form -----------------------------------

    async def _update_native(self):
        if not self._native_shown:
            native_form.show(_FORM_ID, _FORM_HTML, _FORM_WIRING_JS)
            self._native_shown = True

        data = native_form.take_submission(_FORM_ID)
        if data is None:
            return None

        email = (data.get("email") or "").strip()
        password = data.get("password") or ""
        mode = data.get("mode") or "login"
        if not email or not password:
            native_form.set_error(_FORM_ID, "Enter an email and password.")
            return None

        native_form.set_busy(_FORM_ID, True)
        try:
            if mode == "register":
                display_name = (data.get("display_name") or "").strip() or email.split("@")[0]
                await self.client.register_with_email(email, password)
                self.hide_native_inputs()
                return {"display_name": display_name}
            else:
                await self.client.sign_in_with_email(email, password)
                self.hide_native_inputs()
                return {"display_name": None}
        except FirebaseError as exc:
            native_form.set_error(_FORM_ID, friendly_auth_error(exc))
            return None
        finally:
            native_form.set_busy(_FORM_ID, False)

    # -- desktop: pygame-drawn fields ---------------------------------------

    async def _update_desktop(self, screen, events, mouse_pos, mouse_clicked, font_large, font_btn, font_small, draw_button):
        window_w = screen.get_width()

        title = font_large.render("PACKED FOOTBALL", True, (255, 255, 255))
        screen.blit(title, title.get_rect(center=(window_w / 2, 120)))
        subtitle = font_small.render("Sign in to save your squad and play PvP", True, (200, 200, 200))
        screen.blit(subtitle, subtitle.get_rect(center=(window_w / 2, 160)))

        for event in events:
            self.email.handle_event(event)
            self.password.handle_event(event)
            if self.mode == "register":
                self.name.handle_event(event)

        self.email.draw(screen, font_btn)
        self.password.draw(screen, font_btn)
        if self.mode == "register":
            self.name.draw(screen, font_btn)

        toggle_label = "New here? Register instead" if self.mode == "login" else "Already have an account? Sign in"
        if draw_button(screen, toggle_label, 490, 440, 300, 40, mouse_pos, mouse_clicked, font_small):
            self.mode = "register" if self.mode == "login" else "login"
            self.error = ""

        submit_label = "Register" if self.mode == "register" else "Sign In"
        submit_clicked = draw_button(screen, submit_label, 490, 500, 300, 55, mouse_pos, mouse_clicked, font_btn)

        if self.busy:
            busy_surf = font_small.render("Working...", True, (200, 200, 200))
            screen.blit(busy_surf, busy_surf.get_rect(center=(window_w / 2, 640)))
        elif self.error:
            err_surf = font_small.render(self.error, True, ERROR_COLOR)
            screen.blit(err_surf, err_surf.get_rect(center=(window_w / 2, 640)))

        if self.busy:
            return None

        if submit_clicked:
            email = self.email.text.strip()
            password = self.password.text
            if not email or not password:
                self.error = "Enter an email and password."
                return None

            self.busy = True
            try:
                if self.mode == "register":
                    display_name = self.name.text.strip() or email.split("@")[0]
                    await self.client.register_with_email(email, password)
                    return {"display_name": display_name}
                else:
                    await self.client.sign_in_with_email(email, password)
                    return {"display_name": None}
            except FirebaseError as exc:
                self.error = friendly_auth_error(exc)
                return None
            finally:
                self.busy = False

        return None
