# /// script
# dependencies = ["numpy"]
# ///

import asyncio
import pygame
import random

from packEngine import PackManager, PACK_DATABASE, TIER_RANGES
from gameEngine import game


from player.player import Attributes
from player.classes.goalkeeper import Goalkeeper
from player.classes.defender import Defender, CenterBack, Fullback, Wingback
from player.classes.midfielder import Midfielder, DefensiveMid, AttackingMid
from player.classes.forward import Forward, Winger

from firebase_client import FirebaseClient
from firebase_config import BACKEND_URL, FIREBASE_API_KEY, FIREBASE_PROJECT_ID
from game_state import GameState
from auth_scene import AuthScene, TextInput
import native_form
from native_form import _IS_EMSCRIPTEN

WINDOW_SIZE = (1280, 800)

# Renaming your manager on the browser build uses the same full-page native
# HTML form takeover as the login screen (see native_form.py's docstring for
# why in-canvas text entry doesn't work reliably on mobile Safari).
_RENAME_FORM_ID = "pf-rename-form"
_RENAME_FORM_HTML = """
<h1 style="margin:0 0 20px;font-size:24px;">Manager Name</h1>
<input id="pf-rename-name" type="text" placeholder="display name"
       style="width:100%;max-width:320px;box-sizing:border-box;padding:12px;margin-bottom:14px;
              border-radius:6px;border:1px solid #555;background:#191923;color:#e6e6e6;font-size:16px;">
<button id="pf-rename-submit" type="button"
        style="width:100%;max-width:320px;padding:14px;border-radius:8px;border:2px solid #fff;
               background:#329632;color:#fff;font-size:18px;margin-bottom:10px;">
  Save
</button>
<button id="pf-rename-cancel" type="button"
        style="width:100%;max-width:320px;padding:12px;border-radius:8px;border:2px solid #888;
               background:none;color:#ccc;font-size:16px;">
  Cancel
</button>
<div id="pf-rename-form-error" style="color:#e65a5a;margin-top:14px;min-height:20px;font-size:14px;text-align:center;"></div>
"""
_RENAME_FORM_WIRING_JS = """
(function () {
    document.getElementById('pf-rename-submit').onclick = function () {
        window.PFForm._pending['pf-rename-form'] = {
            action: 'save',
            display_name: document.getElementById('pf-rename-name').value,
        };
    };
    document.getElementById('pf-rename-cancel').onclick = function () {
        window.PFForm._pending['pf-rename-form'] = { action: 'cancel' };
    };
})();
"""
FPS = 60
ELO_K = 32  # standard Elo K-factor: how many points swing on a single result

previous_5_scores = []
user_inventory = [] 

pack_manager = PackManager(PACK_DATABASE)

TIER_COLORS = {
    "bronze": (205, 127, 50),
    "silver": (192, 192, 192),
    "gold": (255, 215, 0),
    "platinum": (200, 240, 255),
    "diamond": (154, 197, 240),
    "special": (187, 68, 240),
    "icon": (235,246,231),
}

UI_FORMATION = [
    (150, 600), # 0: GK
    (50, 450),  # 1: LB
    (115, 450), # 2: LCB
    (185, 450), # 3: RCB
    (250, 450), # 4: RB
    (50, 300),  # 5: LM
    (115, 300), # 6: LCM
    (185, 300), # 7: RCM
    (250, 300), # 8: RM
    (115, 150), # 9: LS
    (185, 150)  # 10: RS
]


### ILLEGAL SHIT START, integral for initing game but it should be scraped!

PLAYER_CLASS_MAP = {
    "GK": Goalkeeper,
    "CB": CenterBack,
    "LB": Fullback,
    "RB": Fullback,
    "WB": Wingback,
    "CDM": DefensiveMid,
    "CM": Midfielder,
    "CAM": AttackingMid,
    "LM": Midfielder,
    "RM": Midfielder,
    "LW": Winger,
    "RW": Winger,
    "ST": Forward,
}

def build_player(first, last, position, tier):
    attrs = Attributes()
    base_stats = {
        "stamina": 50, "pass_tendency": 1, "shoot_tendency": 70,
        "drible_tendency": 60, "aggression": 50, "clear_tendency": 30,
    }
    for key, value in base_stats.items():
        setattr(attrs, key, value)
        
    overrides = generate_tier_attributes(position, tier)
    for key, value in overrides.items():
        setattr(attrs, key, value)
        
    player_cls = PLAYER_CLASS_MAP.get(position, Midfielder)
    return player_cls(first, last, tier, position, attrs)

def get_tier_roster(tier: str):
    """Generates a full 11-man roster for a given tier."""
    positions = ["GK", "LB", "CB", "CB", "RB", "LW", "CM", "CM", "RW", "ST", "ST"]
    
    return [("Player", f"{tier.capitalize()} {pos}", pos, tier) for pos in positions]

def generate_tier_attributes(position: str, tier: str) -> dict:
    min_s, max_s = TIER_RANGES.get(tier.lower(), (40, 50))

    def roll_stat(stat_type):
        if stat_type == "primary":
            return random.randint(min_s + (max_s - min_s) // 2, max_s)
        elif stat_type == "secondary":
            return random.randint(min_s, max_s)
        elif stat_type == "nerfed":
            return random.randint(30, 55)

    profile = {
        "speed": "secondary", "agility": "secondary", "passing": "secondary", 
        "ballcontrol": "secondary", "defending": "secondary", "tackling": "secondary", 
        "dribbiling": "secondary", "shooting": "secondary", "power": "secondary", 
        "accuracy": "secondary", "vision": "secondary", "composure": "secondary"
    }

    if position == "GK":
        profile.update(defending="nerfed", tackling="nerfed", shooting="nerfed", dribbiling="nerfed", passing="primary", agility="primary", composure="primary", ballcontrol="primary")
    elif position in ["CB", "LB", "RB"]:
        profile.update(defending="primary", tackling="primary", shooting="nerfed", dribbiling="nerfed")
    elif position == "WB":
        profile.update(speed="primary", passing="primary", defending="secondary", tackling="secondary", shooting="nerfed")
    elif position == "CDM":
        profile.update(defending="primary", tackling="primary", passing="primary", shooting="nerfed")
    elif position in ["CM", "AM", "CAM"]:
        profile.update(passing="primary", ballcontrol="primary", vision="primary")
        if position in ["AM", "CAM"]:
            profile.update(shooting="primary", defending="nerfed", tackling="nerfed")
    elif position in ["LM", "RM"]:
        profile.update(passing="primary", ballcontrol="primary", speed="primary")
    elif position in ["LW", "RW"]:
        profile.update(speed="primary", agility="primary", dribbiling="primary", defending="nerfed", tackling="nerfed")
    elif position == "ST":
        profile.update(shooting="primary", power="primary", accuracy="primary", defending="nerfed", tackling="nerfed")

    return {stat: roll_stat(s_type) for stat, s_type in profile.items()}


user_roster_rows = get_tier_roster("bronze")
user_starting_xi = [build_player(first, last, pos, tier) for first, last, pos, tier in user_roster_rows]

### ILLEGAL SHIT END, integral for initing game but it should be scraped!

class UserTeam:
    def __init__(self, name, players):
        self.name = name
        self.players = players

class Team:
    def __init__(self, name, prefix, rows):
        self.name = name
        self.prefix = prefix
        self.players = [build_player(first, last, position, tier) for first, last, position, tier in rows]


# --- Simple UI Button Helper ---
def draw_button(screen, text, x, y, w, h, mouse_pos, mouse_clicked, font):
    is_hovered = x <= mouse_pos[0] <= x + w and y <= mouse_pos[1] <= y + h
    color = (80, 180, 80) if is_hovered else (50, 130, 50)
    
    pygame.draw.rect(screen, color, (x, y, w, h), border_radius=8)
    pygame.draw.rect(screen, (255, 255, 255), (x, y, w, h), 2, border_radius=8)
    
    text_surf = font.render(text, True, (255, 255, 255))
    text_rect = text_surf.get_rect(center=(x + w / 2, y + h / 2))
    screen.blit(text_surf, text_rect)
    
    return is_hovered and mouse_clicked

def setup_demo_match(user_players, bot_tier):
    user_team = UserTeam("My Squad", user_players)

    bot_rows = get_tier_roster(bot_tier)
    bot_team = Team(f"{bot_tier.capitalize()} AI", "bot", bot_rows)

    return game(bot_team, user_team)

async def _load_account_state(firebase, default_roster, default_display_name):
    """Loads (or creates) the signed-in user's Firestore-backed state.
    """
    game_state = GameState(firebase, PLAYER_CLASS_MAP, Midfielder)
    profile = await game_state.load_or_create_profile(default_roster, default_display_name)
    return game_state, profile

async def main():
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("Packed Football - Web Demo")
    if not _IS_EMSCRIPTEN:
        # Only desktop's pygame-drawn TextInput fields need this. On the
        # browser build every text field goes through native_form.py's real
        # HTML forms instead, and leaving SDL's own text-input/IME handling
        # active turned out to compete with typing into those real inputs --
        # focus worked, but keystrokes never landed in the field.
        pygame.key.start_text_input()
    clock = pygame.time.Clock()
    font_large = pygame.font.SysFont(None, 64)
    font_small = pygame.font.SysFont(None,22)
    font_btn = pygame.font.SysFont(None, 36)

    # --- Firebase: sign in (or show a login screen) and load saved state ---
    # CLIENT-TRUSTED PHASE: the client writes directly to Firestore with its
    # own ID token. See firebase_client.py and firestore.rules for what that
    # does and doesn't protect against. No offline mode: if Firestore can't
    # be reached, _load_account_state() raises and the game crashes rather
    # than silently playing on fake local data.
    global user_starting_xi, user_inventory
    firebase = FirebaseClient(api_key=FIREBASE_API_KEY, project_id=FIREBASE_PROJECT_ID)
    auth_scene = AuthScene(firebase)
    game_state = None
    display_name = "Player"
    user_credits = 1000
    manager_wins = manager_losses = manager_draws = 0
    manager_elo = 1200
    campaign_level = 0

    async def _publish_lobby():
        # One place for the "publish my public snapshot" call so every scene
        # that changes a leaderboard-visible stat (name, roster, wins, elo,
        # campaign progress) stays consistent without repeating all five
        # arguments at each call site.
        await game_state.publish_lobby_entry(
            display_name=display_name,
            roster=user_starting_xi,
            wins=manager_wins,
            elo=manager_elo,
            campaign_level=campaign_level,
        )

    # Returning players on this device resume silently via a cached refresh
    # token (desktop only for now -- see firebase_client.py). Everyone else,
    # including every browser session until that's wired up, sees the login
    # screen below.
    current_scene = "AUTH"
    if await firebase.try_resume_session():
        display_name = f"Player-{firebase.uid[:6]}"
        game_state, profile = await _load_account_state(firebase, user_starting_xi, display_name)
        user_credits = profile["credits"]
        display_name = profile["display_name"]
        manager_wins = profile["wins"]
        manager_losses = profile["losses"]
        manager_draws = profile["draws"]
        manager_elo = profile["elo"]
        campaign_level = profile["campaign_level"]
        user_starting_xi = profile["roster"]
        user_inventory = await game_state.load_inventory()
        await _publish_lobby()
        current_scene = "MENU"

    # --- Master State Machine ---
    match_engine = None
    selected_pitch_idx = -1
    is_campaign_match = True
    active_opponent_label = ""
    active_opponent_elo = None  # opponent's elo at challenge time; None for campaign (no elo change)
    team_dirty = False  # True when TEAM-scene swaps haven't been saved yet
    team_swap_page = 0  # current page through the "Available Replacements" list

    # --- Animation State ---
    shop_state = "IDLE"
    pulled_cards = []
    current_card_idx = 0
    anim_timer = 0

    # --- PvP lobby state ---
    pvp_opponents = []
    pvp_loaded = False
    pvp_view = "CHALLENGE"  # or "LEADERBOARD" -- both live inside the PVP scene
    leaderboard_segment = "wins"  # "wins" | "elo" | "campaign" | "player"
    leaderboard_entries = []
    leaderboard_loaded = False

    # "Player" leaderboard sub-view: goals/assists/matches_played, fetched
    # from the backend (the players collection isn't directly readable by
    # the client -- see backend/main.py's /leaderboard/players).
    player_leaderboard_stat = "goals"  # "goals" | "assists" | "matches_played"
    player_leaderboard_entries = []
    player_leaderboard_loaded = False

    # --- Profile page state ---
    profile_name_input = TextInput((440, 260, 340, 44), placeholder="display name")
    profile_rename_shown = False  # browser build only -- see native_form.py

    # campaign_level itself was already loaded from the profile above (or
    # defaulted to 0 pre-login) -- only the fixed tier list is a constant.
    campaign_tiers = ["bronze", "silver", "gold", "platinum", "diamond", "special"]

    while True:
        dt = 1.0 / FPS
        mouse_pos = pygame.mouse.get_pos()
        mouse_clicked = False

        # Event Processing
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_clicked = True

        screen.fill((30, 30, 40))

        # Scene Routing
        if current_scene == "AUTH":
            result = await auth_scene.update(
                screen, events, mouse_pos, mouse_clicked, font_large, font_btn, font_small, draw_button
            )
            if result is not None:
                display_name = result["display_name"] or display_name
                game_state, profile = await _load_account_state(firebase, user_starting_xi, display_name)
                user_credits = profile["credits"]
                display_name = profile["display_name"]
                manager_wins = profile["wins"]
                manager_losses = profile["losses"]
                manager_draws = profile["draws"]
                manager_elo = profile["elo"]
                campaign_level = profile["campaign_level"]
                user_starting_xi = profile["roster"]
                user_inventory = await game_state.load_inventory()
                await _publish_lobby()
                current_scene = "MENU"

        elif current_scene == "MENU":
            title = font_large.render("PACKED FOOTBALL", True, (255, 255, 255))
            screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0]/2, 200)))
            
            cred_text = font_btn.render(f"Credits: {user_credits}", True, (255, 215, 0))
            screen.blit(cred_text, (20, 20))

            history_title = font_btn.render("Recent Matches:", True, (255, 215, 0))
            screen.blit(history_title, (100, 320))

            hist_y = 360
            for score_str in reversed(previous_5_scores):
                score_surf = font_small.render(score_str, True, (200, 200, 255))
                screen.blit(score_surf, (100, hist_y))
                hist_y += 30

            if draw_button(screen, "Play Campaign Match", 490, 350, 300, 60, mouse_pos, mouse_clicked, font_btn):
                match_engine = setup_demo_match(user_starting_xi,campaign_tiers[campaign_level])
                is_campaign_match = True
                active_opponent_label = f"{campaign_tiers[campaign_level].capitalize()} Team"
                active_opponent_elo = None
                current_scene = "MATCH"

            vs_text = font_btn.render(f"vs {campaign_tiers[campaign_level].capitalize()} Team", True, (200, 200, 200))
            screen.blit(vs_text, (810, 365))

            if draw_button(screen, "Manage Team", 490, 430, 300, 60, mouse_pos, mouse_clicked, font_btn):
                current_scene = "TEAM"

            if draw_button(screen, "Open Shop", 490, 510, 300, 60, mouse_pos, mouse_clicked, font_btn):
                current_scene = "SHOP"

            if draw_button(screen, "Find Opponent (PvP)", 490, 590, 300, 60, mouse_pos, mouse_clicked, font_btn):
                pvp_loaded = False
                current_scene = "PVP"

            if draw_button(screen, "Manager Profile", 490, 670, 300, 60, mouse_pos, mouse_clicked, font_btn):
                profile_name_input.text = display_name
                current_scene = "PROFILE"


        elif current_scene == "SHOP":
            if shop_state == "IDLE":
                title = font_large.render("PLAYER PACKS", True, (255, 255, 255))
                screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0]/2, 100)))
                
                cred_text = font_btn.render(f"Credits: {user_credits}", True, (255, 215, 0))
                screen.blit(cred_text, (20, 20))

                available_packs = pack_manager.get_all_packs()
                pack_y = 200
                
                for pack_data in available_packs:
                    btn_text = f"Buy {pack_data['name']} ({pack_data['price']})"
                    
                    if draw_button(screen, btn_text, 390, pack_y, 500, 60, mouse_pos, mouse_clicked, font_btn):
                        if user_credits >= pack_data["price"]:
                            user_credits -= pack_data["price"]
                            await game_state.set_credits(user_credits)

                            # 1. Pull the cards and trigger the animation state instead of instant inventory
                            pulled_cards = pack_manager.open_pack(pack_data["pack_id"])
                            shop_state = "OPENING"
                            current_card_idx = 0
                            anim_timer = 0
                                
                    pack_y += 80 

                if draw_button(screen, "Back to Menu", 490, 650, 300, 60, mouse_pos, mouse_clicked, font_btn):
                    current_scene = "MENU"

            elif shop_state == "OPENING":
                anim_timer += 1
                card = pulled_cards[current_card_idx]
                
                screen.fill((15, 15, 25)) 
                title = font_large.render("OPENING PACK...", True, (255, 255, 255))
                screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0]/2, 100)))

                center_x, center_y = WINDOW_SIZE[0]/2, WINDOW_SIZE[1]/2
                
                ball_color = (255, 255, 255) #default ball color

                if anim_timer > 120: #card tier show
                    ball_color = TIER_COLORS.get(card.tier.lower(), (255, 255, 255))

                pygame.draw.circle(screen, ball_color, (center_x, center_y), 120)
                pygame.draw.circle(screen, (0, 0, 0), (center_x, center_y), 120, 6)

                if anim_timer > 60: #card pos show
                    pos_text = font_large.render(card.position, True, (0, 0, 0))
                    screen.blit(pos_text, pos_text.get_rect(center=(center_x, center_y - 25)))

                if anim_timer > 180:
                    ovr_text = font_large.render(f"OVR {card.overall}", True, (0, 0, 0))
                    screen.blit(ovr_text, ovr_text.get_rect(center=(center_x, center_y + 35)))
                    
                    name_text = font_btn.render(f"{card.fname} {card.lname}", True, ball_color)
                    screen.blit(name_text, name_text.get_rect(center=(center_x, center_y + 160)))

                if mouse_clicked:
                    anim_timer = 300 

                if anim_timer >= 300: # 5 seconds total per card
                    user_inventory.append(card)
                    await game_state.add_inventory_card(card)
                    current_card_idx += 1
                    anim_timer = 0

                    # Return to shop if pack is empty
                    if current_card_idx >= len(pulled_cards):
                        shop_state = "OPENED"

            elif shop_state == "OPENED":
                screen.fill((15, 15, 25))
                
                title = font_large.render("PACK SUMMARY", True, (255, 255, 255))
                screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0]/2, 100)))

                # Dynamically calculate spacing so large packs don't overlap
                num_cards = len(pulled_cards)
                spacing = WINDOW_SIZE[0] / (num_cards + 1)
                
                # Shrink the circles slightly if there are many cards
                circle_radius = min(60, int(spacing / 2) - 10)

                for idx, card in enumerate(pulled_cards):
                    cx = spacing * (idx + 1)
                    cy = WINDOW_SIZE[1] / 2
                    
                    ball_color = TIER_COLORS.get(card.tier.lower(), (255, 255, 255))
                    
                    pygame.draw.circle(screen, ball_color, (cx, cy), circle_radius)
                    pygame.draw.circle(screen, (0, 0, 0), (cx, cy), circle_radius, max(2, circle_radius // 10))
                    
                    pos_text = font_btn.render(card.position, True, (0, 0, 0))
                    screen.blit(pos_text, pos_text.get_rect(center=(cx, cy - circle_radius // 4)))
                    
                    ovr_text = font_small.render(f"OVR {card.overall}", True, (0, 0, 0))
                    screen.blit(ovr_text, ovr_text.get_rect(center=(cx, cy + circle_radius // 3)))
                    
                    name_text = font_small.render(card.lname, True, ball_color)
                    screen.blit(name_text, name_text.get_rect(center=(cx, cy + circle_radius + 30)))

                prompt = font_btn.render("Click anywhere to continue", True, (150, 150, 150))
                screen.blit(prompt, prompt.get_rect(center=(WINDOW_SIZE[0]/2, WINDOW_SIZE[1] - 100)))
                user_inventory.sort(key=lambda p: p.overall, reverse=True)               

                # Return to the main shop screen
                if mouse_clicked:
                    shop_state = "IDLE"

        elif current_scene == "PVP":
            title = font_large.render(
                "FIND OPPONENT" if pvp_view == "CHALLENGE" else "LEADERBOARD", True, (255, 255, 255)
            )
            screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0] / 2, 70)))

            # --- View toggle: Challenge an opponent, or browse standings ---
            challenge_label = "[ Challenge ]" if pvp_view == "CHALLENGE" else "Challenge"
            if draw_button(screen, challenge_label, 390, 115, 220, 44, mouse_pos, mouse_clicked, font_small):
                pvp_view = "CHALLENGE"
            leaderboard_label = "[ Leaderboard ]" if pvp_view == "LEADERBOARD" else "Leaderboard"
            if draw_button(screen, leaderboard_label, 630, 115, 220, 44, mouse_pos, mouse_clicked, font_small):
                pvp_view = "LEADERBOARD"

            if pvp_view == "CHALLENGE":
                if not pvp_loaded:
                    pvp_opponents = await game_state.list_opponents()
                    pvp_loaded = True

                if not pvp_opponents:
                    msg = font_btn.render("No other squads published yet. Check back soon!", True, (150, 150, 150))
                    screen.blit(msg, msg.get_rect(center=(WINDOW_SIZE[0] / 2, 300)))
                else:
                    opp_y = 190
                    for opp in pvp_opponents:
                        btn_text = f"Challenge {opp['display_name']} (OVR {opp['overall']}, Elo {opp['elo']})"
                        if draw_button(screen, btn_text, 390, opp_y, 500, 60, mouse_pos, mouse_clicked, font_btn):
                            match_engine = game(
                                UserTeam(opp["display_name"], opp["players"]),
                                UserTeam("My Squad", user_starting_xi),
                            )
                            is_campaign_match = False
                            active_opponent_label = opp["display_name"]
                            active_opponent_elo = opp["elo"]
                            current_scene = "MATCH"
                        opp_y += 80

                if draw_button(screen, "Refresh", 390, 650, 240, 50, mouse_pos, mouse_clicked, font_btn):
                    pvp_loaded = False

            else:  # pvp_view == "LEADERBOARD"
                # Four segments: three manager standings (campaign progress,
                # elo, total wins), plus "Player" for the per-card stat
                # leaderboards (goals/assists/matches played) served by the
                # backend -- the players collection isn't directly readable
                # by the client, so that one's a separate fetch below.
                segments = [("campaign", "Campaign"), ("elo", "Elo"), ("wins", "Wins"), ("player", "Player")]
                seg_x = 390
                for seg_key, seg_label in segments:
                    label = f"[{seg_label}]" if leaderboard_segment == seg_key else seg_label
                    if draw_button(screen, label, seg_x, 175, 150, 44, mouse_pos, mouse_clicked, font_small):
                        leaderboard_segment = seg_key
                    seg_x += 170

                if leaderboard_segment == "player":
                    # Sub-tabs for which per-card stat to rank by.
                    stat_options = [("goals", "Goals", 130), ("assists", "Assists", 130), ("matches_played", "Matches Played", 190)]
                    stat_x = 390
                    for stat_key, stat_label, stat_w in stat_options:
                        label = f"[{stat_label}]" if player_leaderboard_stat == stat_key else stat_label
                        if draw_button(screen, label, stat_x, 225, stat_w, 40, mouse_pos, mouse_clicked, font_small):
                            if player_leaderboard_stat != stat_key:
                                player_leaderboard_stat = stat_key
                                player_leaderboard_loaded = False
                        stat_x += stat_w + 15

                    if not player_leaderboard_loaded:
                        result = await firebase.call_backend(
                            "GET", f"{BACKEND_URL}/leaderboard/players?stat={player_leaderboard_stat}&limit=5"
                        )
                        player_leaderboard_entries = result["entries"]
                        player_leaderboard_loaded = True

                    if not player_leaderboard_entries:
                        msg = font_btn.render("No player data yet.", True, (150, 150, 150))
                        screen.blit(msg, msg.get_rect(center=(WINDOW_SIZE[0] / 2, 340)))
                    else:
                        row_y = 290
                        for rank, entry in enumerate(player_leaderboard_entries, start=1):
                            row_text = f"{rank}. {entry['fname']} {entry['lname']} ({entry['position']}) - {entry['value']}"
                            row_surf = font_btn.render(row_text, True, (200, 200, 255))
                            screen.blit(row_surf, (390, row_y))
                            row_y += 42
                else:
                    # A POC leaderboard just needs a top list per segment --
                    # no pagination, no "your rank" if outside the top 10.
                    if not leaderboard_loaded:
                        leaderboard_entries = await game_state.list_leaderboard()
                        leaderboard_loaded = True

                    sort_field = {"campaign": "campaign_level", "elo": "elo", "wins": "wins"}[leaderboard_segment]
                    ranked = sorted(leaderboard_entries, key=lambda e: e.get(sort_field, 0), reverse=True)[:10]

                    if not ranked:
                        msg = font_btn.render("No leaderboard data yet.", True, (150, 150, 150))
                        screen.blit(msg, msg.get_rect(center=(WINDOW_SIZE[0] / 2, 320)))
                    else:
                        row_y = 240
                        for rank, entry in enumerate(ranked, start=1):
                            if leaderboard_segment == "campaign":
                                idx = entry.get("campaign_level", 0)
                                value_label = campaign_tiers[idx].capitalize() if 0 <= idx < len(campaign_tiers) else str(idx)
                            elif leaderboard_segment == "elo":
                                value_label = str(entry.get("elo", 1200))
                            else:
                                value_label = str(entry.get("wins", 0))

                            is_you = firebase.uid is not None and entry["uid"] == firebase.uid
                            row_color = (255, 215, 0) if is_you else (200, 200, 255)
                            row_text = f"{rank}. {entry['display_name']}{' (you)' if is_you else ''} - {value_label}"
                            row_surf = font_btn.render(row_text, True, row_color)
                            screen.blit(row_surf, (390, row_y))
                            row_y += 42

                if draw_button(screen, "Refresh", 390, 650, 240, 50, mouse_pos, mouse_clicked, font_btn):
                    leaderboard_loaded = False
                    player_leaderboard_loaded = False

            if draw_button(screen, "Back to Menu", 650, 650, 240, 50, mouse_pos, mouse_clicked, font_btn):
                current_scene = "MENU"

        elif current_scene == "MATCH":
            if match_engine:
                MAX_MATCH_FRAMES = 10800  
                HALF_TIME_FRAMES = 5400
                
                if match_engine.match_clock_frames < MAX_MATCH_FRAMES:
                    if match_engine.match_clock_frames != HALF_TIME_FRAMES:
                        if match_engine.match_clock_frames % 2 == 0:
                            match_engine.step()
                        match_engine.tick(dt)
                else:
                    if not hasattr(match_engine, "final_whistle_clock"):
                        match_engine.final_whistle_clock = 0
                    match_engine.final_whistle_clock += 1
                    match_engine.goal_popup = {"text": "FULL TIME", "timer": 60, "team": None}

                match_engine.render(screen, WINDOW_SIZE)
                
                if match_engine.match_clock_frames == HALF_TIME_FRAMES:
                    overlay = pygame.Surface(WINDOW_SIZE, pygame.SRCALPHA)
                    overlay.fill((0, 0, 0, 150))
                    screen.blit(overlay, (0, 0))
                    
                    ht_text = font_large.render(f"HALF TIME: {match_engine.scores[0]} - {match_engine.scores[1]}", True, (255, 255, 255))
                    screen.blit(ht_text, ht_text.get_rect(center=(WINDOW_SIZE[0]/2, WINDOW_SIZE[1]/2 - 50)))
                    
                    if draw_button(screen, "Start 2nd Half", WINDOW_SIZE[0]/2 - 150, WINDOW_SIZE[1]/2 + 20, 300, 60, mouse_pos, mouse_clicked, font_btn):
                        match_engine.match_clock_frames += 1 
                        match_engine.reset_positions(restart_type="kickoff", team=1)

                if draw_button(screen, "Toggle Camera", WINDOW_SIZE[0] - 180, WINDOW_SIZE[1] - 80, 160, 45, mouse_pos, mouse_clicked, font_btn):
                    match_engine.camera_mode = "full" if getattr(match_engine, "camera_mode", "zoom") == "zoom" else "zoom"

                # --- Skip Match Button ---
                if draw_button(screen, "Skip Match", WINDOW_SIZE[0] - 180, WINDOW_SIZE[1] - 140, 160, 45, mouse_pos, mouse_clicked, font_btn):
                    while match_engine.match_clock_frames < MAX_MATCH_FRAMES:
                        if match_engine.match_clock_frames == HALF_TIME_FRAMES:
                            match_engine.match_clock_frames += 1
                            
                        if match_engine.match_clock_frames % 2 == 0:
                            match_engine.step()
                        match_engine.tick(dt)
                    match_engine.final_whistle_clock = 600

                if hasattr(match_engine, "final_whistle_clock") and match_engine.final_whistle_clock >= 600:
                    my_score = match_engine.scores[1]
                    opp_score = match_engine.scores[0]
                    previous_5_scores.append(f"{display_name} {my_score} - {opp_score} {active_opponent_label}")
                    if len(previous_5_scores) > 5:
                        previous_5_scores.pop(0)
                    for i in range(len(match_engine.teamB.players)):
                        match_engine.teamB.players[i].match_played()

                    if is_campaign_match: #campaing update, only way to get money
                        if my_score > opp_score:
                            user_credits += 500
                            if campaign_level < len(campaign_tiers) - 1:
                                campaign_level += 1
                        elif my_score == opp_score:
                            user_credits += 100
                        else:
                            user_credits += 50
                    elif not is_campaign_match and active_opponent_elo is not None: #pvp update
  
                        actual_score = 1.0 if my_score > opp_score else (0.5 if my_score == opp_score else 0.0)
                        expected_score = 1.0 / (1.0 + 10 ** ((active_opponent_elo - manager_elo) / 400.0))
                        manager_elo = round(manager_elo + ELO_K * (actual_score - expected_score))
                    
                        if my_score > opp_score:
                            manager_wins += 1
                        elif my_score == opp_score:
                            manager_draws += 1
                        else:
                            manager_losses += 1

                    await game_state.set_credits(user_credits)
                    await game_state.save_roster(user_starting_xi)
                    
                    if is_campaign_match:
                        await game_state.set_campaign_level(campaign_level)
                    else:
                        await game_state.set_elo(manager_elo)
                        await game_state.record_match_result(manager_wins, manager_losses, manager_draws)
                    await _publish_lobby()

                    current_scene = "MENU"
                    match_engine = None

        elif current_scene == "TEAM":
            pitch_rect = pygame.Rect(20, 50, 300, 600)
            pygame.draw.rect(screen, (22, 120, 55), pitch_rect)
            pygame.draw.rect(screen, (255, 255, 255), pitch_rect, 2)
            
            for i, (px, py) in enumerate(UI_FORMATION):
                player_obj = user_starting_xi[i]
                
                # Tier based view on small
                color = (100,100,100)
                if selected_pitch_idx == i:
                    color = (0, 215, 0) 
                else:
                    color = TIER_COLORS[player_obj.tier]
                circle_rect = pygame.draw.circle(screen, color, (px + 20, py + 50), 20)
                
                lbl = font_btn.render(player_obj.position, True, (0, 0, 0))
                screen.blit(lbl, lbl.get_rect(center=(px + 20, py + 50)))
                
                # Check for clicks
                if mouse_clicked and circle_rect.collidepoint(mouse_pos):
                    selected_pitch_idx = i
                    team_swap_page = 0

            # --- Draw Player Detail Panel (Right Side) ---
            panel_rect = pygame.Rect(350, 50, WINDOW_SIZE[0] - 370, 600)
            pygame.draw.rect(screen, (40, 40, 50), panel_rect, border_radius=12)
            
            if selected_pitch_idx != -1:
                active_player = user_starting_xi[selected_pitch_idx]
                
                # Header
                name_text = font_large.render(f"{active_player.fname} {active_player.lname} - {active_player.position}", True, (255, 255, 255))
                screen.blit(name_text, (380, 70))
                name_text = font_btn.render(f"OVR {active_player.overall} - {(active_player.tier).title()}", True, (255, 255, 180))
                screen.blit(name_text, (380, 120))
                origin_text = font_small.render(f"{active_player.country} - {active_player.hometown}", True, (200, 200, 200))
                screen.blit(origin_text, (380, 150))

                # Stats Grid
                stats = active_player.getStatistics()
                sy_offset = 180
                sx_offset = 380
                statistics = [
                    f"Matches Played: {stats['matches_played']}",
                    f"Goals: {stats['goals']}",
                    f"Assists: {stats['assists']}"
                ]

                # Attributes Grid
                attrs = active_player.getAttributes()
                ay_offset = 270
                ax_offset = 380
                
                attributes = [
                    f"Speed: {attrs.speed}", f"Agility: {attrs.agility}", f"Passing: {attrs.passing}",
                    f"Control: {attrs.ballcontrol}", f"Defending: {attrs.defending}", f"Tackling: {attrs.tackling}",
                    f"Dribbling: {attrs.dribbiling}", f"Shooting: {attrs.shooting}", f"Power: {attrs.power}",
                    f"Vision: {attrs.vision}", f"Composure: {attrs.composure}"
                ]


                for idx, stat in enumerate(statistics):
                    stat_surf = font_small.render(stat, True, (200, 200, 255))
                    screen.blit(stat_surf, (sx_offset, sy_offset))
                    sy_offset += 30
                    if sy_offset > 230:
                        sy_offset = 180
                        sx_offset += 250
                
                attr_text = font_btn.render("Attributes", True, (240, 240, 240))
                screen.blit(attr_text, (ax_offset, 230))
                for idx, attr in enumerate(attributes):
                    attr_surf = font_small.render(attr, True, (200, 200, 255))
                    screen.blit(attr_surf, (ax_offset, ay_offset))
                    ay_offset += 30

                    if ay_offset > 800:
                        ay_offset = 270
                        ax_offset += 250
                        
                


                # --- Inventory Swap List (sorted best-first, paginated) ---
                inv_title = font_btn.render("Available Replacements:", True, (255, 215, 0))
                screen.blit(inv_title, (880, 110))

                SWAP_PAGE_SIZE = 8
                matches = sorted(
                    (p for p in user_inventory if p.position == active_player.position),
                    key=lambda p: p.overall,
                    reverse=True,
                )
                total_pages = max(1, (len(matches) + SWAP_PAGE_SIZE - 1) // SWAP_PAGE_SIZE)
                team_swap_page = max(0, min(team_swap_page, total_pages - 1))
                page_start = team_swap_page * SWAP_PAGE_SIZE
                page_matches = matches[page_start:page_start + SWAP_PAGE_SIZE]

                inv_y = 150
                for inv_player in page_matches:
                    btn_text = f"Swap {inv_player.fname} {inv_player.lname} (OVR ~{inv_player.overall})"

                    # Draw buttons safely in the right-hand column
                    if draw_button(screen, btn_text, 880, inv_y, 280, 40, mouse_pos, mouse_clicked, font_small):
                        # Swap the benched player onto the pitch and put the
                        # active player in inventory. Local-only: nothing
                        # touches Firestore here, so swapping stays instant
                        # no matter how many times you click around. Hit
                        # "Save Team" below to persist once you're done.
                        user_inventory[user_inventory.index(inv_player)] = active_player
                        user_starting_xi[selected_pitch_idx] = inv_player
                        team_dirty = True
                        selected_pitch_idx = -1
                        break

                    inv_y += 50

                controls_y = 150 + len(page_matches) * 50 + 10
                if not matches:
                    empty_text = font_small.render(f"No benched players for {active_player.position}.", True, (150, 150, 150))
                    screen.blit(empty_text, (880, 150))
                elif total_pages > 1:
                    page_label = font_small.render(f"Page {team_swap_page + 1}/{total_pages}", True, (200, 200, 200))
                    screen.blit(page_label, (880, controls_y))

                    if team_swap_page > 0:
                        if draw_button(screen, "Prev", 880, controls_y + 30, 130, 36, mouse_pos, mouse_clicked, font_small):
                            team_swap_page -= 1
                    if team_swap_page < total_pages - 1:
                        if draw_button(screen, "Next", 1030, controls_y + 30, 130, 36, mouse_pos, mouse_clicked, font_small):
                            team_swap_page += 1
                
            else:
                prompt = font_btn.render("Select a player on the pitch to view stats.", True, (150, 150, 150))
                screen.blit(prompt, prompt.get_rect(center=panel_rect.center))

            # Back Button
            if draw_button(screen, "Back to Menu", 20, 670, 300, 60, mouse_pos, mouse_clicked, font_btn):
                current_scene = "MENU"
                selected_pitch_idx = -1

            # --- Save Team ---
            status_color = (230, 190, 90) if team_dirty else (140, 200, 140)
            status_text = "Unsaved changes" if team_dirty else "All changes saved"
            status_surf = font_small.render(status_text, True, status_color)
            screen.blit(status_surf, (360, 645))

            if draw_button(screen, "Save Team", 360, 670, 300, 60, mouse_pos, mouse_clicked, font_btn):
                await game_state.save_team(user_starting_xi, user_inventory)
                await _publish_lobby()
                team_dirty = False

        elif current_scene == "PROFILE":
            title = font_large.render("MANAGER PROFILE", True, (255, 255, 255))
            screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0] / 2, 80)))

            avg_overall = round(sum(p.overall for p in user_starting_xi) / len(user_starting_xi)) if user_starting_xi else 0

            name_label = font_btn.render(f"Manager Name: {display_name}", True, (200, 200, 200))
            screen.blit(name_label, (440, 200))

            if _IS_EMSCRIPTEN:
                if draw_button(screen, "Edit Name", 800, 195, 180, 44, mouse_pos, mouse_clicked, font_small):
                    native_form.show(_RENAME_FORM_ID, _RENAME_FORM_HTML, _RENAME_FORM_WIRING_JS)
                    profile_rename_shown = True

                if profile_rename_shown:
                    submission = native_form.take_submission(_RENAME_FORM_ID)
                    if submission is not None:
                        native_form.hide(_RENAME_FORM_ID)
                        profile_rename_shown = False
                        if submission.get("action") == "save":
                            new_name = (submission.get("display_name") or "").strip()
                            if new_name and new_name != display_name:
                                display_name = new_name
                                await game_state.set_display_name(display_name)
                                await _publish_lobby()
            else:
                for event in events:
                    profile_name_input.handle_event(event)
                profile_name_input.draw(screen, font_btn)

                if draw_button(screen, "Save Name", 800, 260, 180, 44, mouse_pos, mouse_clicked, font_small):
                    new_name = profile_name_input.text.strip()
                    if new_name and new_name != display_name:
                        display_name = new_name
                        await game_state.set_display_name(display_name)
                        await _publish_lobby()

            stats_y = 340
            for line in (
                f"Squad Overall: {avg_overall}",
                f"Wins: {manager_wins}",
                f"Losses: {manager_losses}",
                f"Draws: {manager_draws}",
            ):
                surf = font_btn.render(line, True, (200, 200, 255))
                screen.blit(surf, (440, stats_y))
                stats_y += 50

            if draw_button(screen, "Back to Menu", 490, 650, 300, 60, mouse_pos, mouse_clicked, font_btn):
                native_form.hide(_RENAME_FORM_ID)
                profile_rename_shown = False
                current_scene = "MENU"

            if draw_button(screen, "Log Out / Switch Account", 490, 730, 300, 50, mouse_pos, mouse_clicked, font_small):
                # The only way back to the login screen: boot always tries a
                # silent resume first, so without this a device with a saved
                # session can never reach AUTH again to register or switch.
                native_form.hide(_RENAME_FORM_ID)
                profile_rename_shown = False
                firebase.sign_out()
                game_state = None
                auth_scene = AuthScene(firebase)
                current_scene = "AUTH"

        pygame.display.flip()
        clock.tick(FPS)
        
        # 3. CRITICAL: Yield control to the browser
        await asyncio.sleep(0) 

if __name__ == "__main__":
    asyncio.run(main())