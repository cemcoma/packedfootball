"""Seeded reproduction must survive a restart of the program.

A pack seed used to produce different cards on every run: packEngine rolled
one RNG value per name in _TENDENCY_STAT_NAMES, which was a set, and Python
randomises string hashing per process -- so iteration order, and therefore
which random number landed on which attribute, changed every time.

This matters well beyond tests. A reported match is only reproducible from
its stored seed if the same seed rebuilds the same cards, which is exactly
what the engine_version + seed stamp on games/{id} is for.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, %r)
    from packEngine import PACK_DATABASE, PackManager
    pm = PackManager(PACK_DATABASE, seed=1234)
    cards = pm.open_pack(3)
    from dataclasses import asdict
    for c in cards:
        print(c.position, sorted(asdict(c.attributes).items()))
    """
) % str(ROOT / "packedfootball")


def _run_in_fresh_process(hash_seed: str | None):
    """Runs card generation in a brand new interpreter.

    PYTHONHASHSEED must differ between runs for this to be a real test --
    with it pinned, the old bug is invisible.
    """
    import os

    env = dict(os.environ)
    if hash_seed is None:
        env.pop("PYTHONHASHSEED", None)
    else:
        env["PYTHONHASHSEED"] = hash_seed
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_same_seed_gives_same_cards_across_processes():
    """The regression: different hash seeds must still yield identical cards."""
    a = _run_in_fresh_process("0")
    b = _run_in_fresh_process("1")
    c = _run_in_fresh_process("12345")
    assert a == b == c, "pack generation still depends on hash randomisation"


def test_tendency_stat_order_is_stable():
    from packEngine import _TENDENCY_STAT_NAMES

    assert isinstance(_TENDENCY_STAT_NAMES, tuple), "must be ordered, not a set"
    assert list(_TENDENCY_STAT_NAMES) == sorted(_TENDENCY_STAT_NAMES)


def test_skill_and_tendency_names_do_not_overlap():
    from packEngine import _SKILL_STAT_NAMES, _TENDENCY_STAT_NAMES

    assert not (set(_SKILL_STAT_NAMES) & set(_TENDENCY_STAT_NAMES))


def test_every_attribute_is_generated():
    """No Attributes field may be silently dropped from generation.

    Skills and tendencies are rolled from their own name lists; PHYSICAL_FIELDS
    (height) is rolled separately by _roll_height, because it must not scale
    with card tier. Between them they have to cover the whole dataclass.
    """
    from packEngine import _SKILL_STAT_NAMES, _TENDENCY_STAT_NAMES
    from player.player import PHYSICAL_FIELDS, Attributes

    covered = set(_SKILL_STAT_NAMES) | set(_TENDENCY_STAT_NAMES) | set(PHYSICAL_FIELDS)
    assert covered == set(Attributes.__dataclass_fields__)
