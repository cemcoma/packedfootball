# Item sprites

One PNG per buffable stat, named exactly as the stat is
(`packedfootball/items.py`'s OUTFIELD_STATS / KEEPER_STATS, plus `slots` for
the slot extender). ItemView draws it in the middle of the card, where a
player card draws its portrait:

    accuracy   agility   ballcontrol   defending   dribbling   heading
    passing    power     shooting      slots       speed       stamina
    tackling   vision

The card BACK is not here -- an item reuses `sprites/player_cards/<rarity>.png`,
the same art a player of that rarity gets, because items and cards share one
rarity scale.

Each lookup is `ResourceLoader.exists()`-guarded: a stat with no file here
falls back to the first three letters of its name, so these can land one at a
time without breaking anything.

Draw them square and transparent; they are scaled to fit (`stretch_mode = 5`,
keep-aspect-centred) into roughly 98x70 at full card size and 40x30 compact.

Preview them all at once, no account or backend needed:

    Godot --path mobile res://scenes/dev/ItemPreview.tscn
