# /// script
# dependencies = ["numpy"]
# ///

import asyncio
import pygame

from packEngine import PackManager, PACK_DATABASE
from gameEngine import game
from poc import build_player, get_tier_roster, PLAYER_CLASS_MAP

WINDOW_SIZE = (1280, 800)
FPS = 60

user_roster_rows = get_tier_roster("bronze")
user_starting_xi = [build_player(first, last, pos, tier) for first, last, pos, tier in user_roster_rows]
previous_5_scores = []

user_inventory = [] 

pack_manager = PackManager(PACK_DATABASE)

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

TIER_COLORS = {
    "bronze": (205, 127, 50),
    "silver": (192, 192, 192),
    "gold": (255, 215, 0),
    "platinum": (200, 240, 255),
    "diamond": (154, 197, 240),
    "special": (187, 68, 240),
    "icon": (240,240,240),
}

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

async def main():
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("Packed Football - Web Demo")
    clock = pygame.time.Clock()
    font_large = pygame.font.SysFont(None, 64)
    font_small = pygame.font.SysFont(None,22)
    font_btn = pygame.font.SysFont(None, 36)

    # --- Master State Machine ---
    current_scene = "MENU"
    user_credits = 100000
    match_engine = None
    selected_pitch_idx = -1

    # --- Animation State ---
    shop_state = "IDLE"
    pulled_cards = []
    current_card_idx = 0
    anim_timer = 0

    
    campaign_tiers = ["bronze", "silver", "gold", "platinum", "diamond", "special"]
    campaign_level = 0

    while True:
        dt = 1.0 / FPS
        mouse_pos = pygame.mouse.get_pos()
        mouse_clicked = False

        # Event Processing
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_clicked = True

        screen.fill((30, 30, 40))

        # Scene Routing
        if current_scene == "MENU":
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
                current_scene = "MATCH"

            vs_text = font_btn.render(f"vs {campaign_tiers[campaign_level].capitalize()} Team", True, (200, 200, 200))
            screen.blit(vs_text, (810, 365))

            if draw_button(screen, "Manage Team", 490, 430, 300, 60, mouse_pos, mouse_clicked, font_btn):
                current_scene = "TEAM"
                
            if draw_button(screen, "Open Shop", 490, 510, 300, 60, mouse_pos, mouse_clicked, font_btn):
                current_scene = "SHOP"
            

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
                    bot_score = match_engine.scores[0]

                    previous_5_scores.append(f"User {my_score} - {bot_score} {campaign_tiers[campaign_level].capitalize()}")
                    if len(previous_5_scores) > 5:
                        previous_5_scores.pop(0)

                    for i in range(len(match_engine.all_players)):
                        match_engine.all_players[i].match_played()
                    
                    if my_score > bot_score:
                        user_credits += 500  
                        if campaign_level < len(campaign_tiers) - 1:
                            campaign_level += 1
                    elif my_score == bot_score:
                        user_credits += 100  
                    else:
                        user_credits += 50  

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
                        
                


                # --- Inventory Swap List ---
                inv_title = font_btn.render("Available Replacements:", True, (255, 215, 0))
                screen.blit(inv_title, (880, 110)) 

                inv_y = 150
                replacements_found = False
                
                for inv_idx, inv_player in enumerate(user_inventory):
                    if inv_player.position == active_player.position:
                        replacements_found = True
                        btn_text = f"Swap {inv_player.fname} {inv_player.lname} (OVR ~{inv_player.overall})"

                        # Draw buttons safely in the right-hand column
                        if draw_button(screen, btn_text, 880, inv_y, 280, 40, mouse_pos, mouse_clicked, font_small):
                            # Swap the benched player onto the pitch and put the active player in inventory
                            user_inventory[inv_idx] = active_player
                            user_starting_xi[selected_pitch_idx] = inv_player
                            user_inventory.sort(key=lambda p: p.overall, reverse=True)
                            selected_pitch_idx = -1 
                            break 

                        inv_y += 50
                        
                if not replacements_found:
                    empty_text = font_small.render(f"No benched players for {active_player.position}.", True, (150, 150, 150))
                    screen.blit(empty_text, (880, 150))
                
            else:
                prompt = font_btn.render("Select a player on the pitch to view stats.", True, (150, 150, 150))
                screen.blit(prompt, prompt.get_rect(center=panel_rect.center))

            # Back Button
            if draw_button(screen, "Back to Menu", 20, 670, 300, 60, mouse_pos, mouse_clicked, font_btn):
                current_scene = "MENU"
                selected_pitch_idx = -1


        pygame.display.flip()
        clock.tick(FPS)
        
        # 3. CRITICAL: Yield control to the browser
        await asyncio.sleep(0) 

if __name__ == "__main__":
    asyncio.run(main())