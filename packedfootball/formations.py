"""
Football Formations Registry
"""
from gameEngine import PITCH_HEIGHT,PITCH_WIDTH


def _mirror_formation(team_a_data):
    """
    Generates a full 22-player dictionary from 11 base positions.
    Returns: { index: {"pos": [x, y], "role": "ROLE_NAME"} }
    """
    formation = {}
    
    for i, data in enumerate(team_a_data):
        x, y = data["pos"]
        role = data["role"]
        
        # Team A (Indices 0-10)
        formation[i] = {
            "pos": [float(x), float(y)],
            "role": role
        }
        
        # Team B (Indices 11-21) - Mirrored across both axes
        formation[i + 11] = {
            "pos": [float(PITCH_WIDTH - x), float(PITCH_HEIGHT - y)],
            "role": role
        }
        
    return formation

# ---------------------------------------------------------
# Base Coordinates & Roles (Team A)
# ---------------------------------------------------------

_442_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [12.0, 20.0], "role": "LB"},
    {"pos": [27.0, 15.0], "role": "CB"},
    {"pos": [43.0, 15.0], "role": "CB"},
    {"pos": [58.0, 20.0], "role": "RB"},
    {"pos": [12.0, 40.0], "role": "CM"},
    {"pos": [27.0, 35.0], "role": "CM"},
    {"pos": [43.0, 35.0], "role": "CM"},
    {"pos": [58.0, 40.0], "role": "CM"},
    {"pos": [27.0, 47.0], "role": "ST"},
    {"pos": [43.0, 47.0], "role": "ST"},
]

_433_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [12.0, 20.0], "role": "LB"},
    {"pos": [27.0, 15.0], "role": "CB"},
    {"pos": [43.0, 15.0], "role": "CB"},
    {"pos": [58.0, 20.0], "role": "RB"},
    {"pos": [35.0, 23.0], "role": "CDM"}, 
    {"pos": [25.0, 30.0], "role": "CM"},
    {"pos": [45.0, 30.0], "role": "CM"},
    {"pos": [15.0, 44.0], "role": "LW"},
    {"pos": [55.0, 44.0], "role": "RW"},
    {"pos": [35.0, 47.0], "role": "ST"},
]

_352_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [18.0, 15.0], "role": "CB"},
    {"pos": [35.0, 12.0], "role": "CB"},
    {"pos": [52.0, 15.0], "role": "CB"},
    {"pos": [35.0, 22.0], "role": "CDM"},
    {"pos": [10.0, 32.0], "role": "WB"},
    {"pos": [25.0, 32.0], "role": "CM"},
    {"pos": [45.0, 32.0], "role": "CM"},
    {"pos": [60.0, 32.0], "role": "WB"},
    {"pos": [27.0, 47.0], "role": "ST"},
    {"pos": [43.0, 47.0], "role": "ST"},
]

_4231_base = [
    {"pos": [35.0, 5.0],  "role": "GK"},
    {"pos": [12.0, 20.0], "role": "LB"},
    {"pos": [27.0, 15.0], "role": "CB"},
    {"pos": [43.0, 15.0], "role": "CB"},
    {"pos": [58.0, 20.0], "role": "RB"},
    {"pos": [27.0, 28.0], "role": "CDM"},
    {"pos": [43.0, 28.0], "role": "CDM"},
    {"pos": [15.0, 38.0], "role": "LW"},
    {"pos": [35.0, 38.0], "role": "CAM"},
    {"pos": [55.0, 38.0], "role": "RW"},
    {"pos": [35.0, 47.0], "role": "ST"},
]

FORMATIONS = {
    "4-4-2": _mirror_formation(_442_base),
    "4-3-3": _mirror_formation(_433_base),
    "3-5-2": _mirror_formation(_352_base),
    "4-2-3-1": _mirror_formation(_4231_base),
}

def get_formation(name: str) -> dict:
    return FORMATIONS.get(name, FORMATIONS["4-4-2"])