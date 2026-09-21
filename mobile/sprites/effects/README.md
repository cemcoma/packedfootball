# Pack-open effect art

Drop PNGs here to replace the procedural effects PackWalkoutStage.gd draws
for the pack opening. Nothing is required -- every slot has a code-drawn
fallback, and a missing file just means that fallback keeps being used.

Naming, most specific first (the first file that exists wins):

    <slot>_<tier>.png     aura_special_champ.png   -- one pack edition
    <slot>_<family>.png   aura_special.png         -- every special
    <slot>.png            aura.png                 -- every tier

Slots:

| slot    | what it is                                   | drawn at   | fallback              |
|---------|----------------------------------------------|------------|-----------------------|
| `aura`  | the glow swelling out of the pack             | 340x340    | soft radial gradient  |
| `rays`  | god-rays spinning behind the pack             | 420x420    | flat spinning wedges  |
| `beam`  | the column of light a card walks out of       | 220x360    | soft radial gradient  |
| `spark` | one particle, both the leak and the burst     | 16x16      | soft radial dot       |

Every one of them is tinted with the best card's tier colour
(PlayerCard.TIER_COLORS) on top of whatever colour the PNG itself has, so
draw them **white** unless you want a tier's art to ignore that colour.
Icon cycles its hue instead of using a fixed one -- that is the holo.

How loud each tier's opening is (charge length, shake, ray strength, spark
count, holo on/off) is the `FLARE` table at the top of
`scripts/components/PackWalkoutStage.gd`.
