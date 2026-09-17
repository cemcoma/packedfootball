"""Display-name rules and what leaving a tournament group writes.

Pure functions only, same as test_tournament_rules: the Firestore halves
(the rename transaction, the deletion sweep) are thin wrappers over these.
"""

from __future__ import annotations

import pytest

import config
from services import account as a

CAP = config.TOURNAMENT_GROUP_CAPACITY


# -- names ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, stored",
    [
        ("Cem", "Cem"),
        ("  Cem   Tekcan ", "Cem Tekcan"),
        ("Çağla_07", "Çağla_07"),
        ("a.b-c", "a.b-c"),
        ("x" * config.DISPLAY_NAME_MAX_LENGTH, "x" * config.DISPLAY_NAME_MAX_LENGTH),
    ],
)
def test_valid_names_are_normalised_not_refused(raw, stored):
    assert a.validate_display_name(raw) == stored


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("ab", "too_short"),
        ("x" * (config.DISPLAY_NAME_MAX_LENGTH + 1), "too_long"),
        ("cem/tekcan", "characters"),
        ("cem!", "characters"),
        ("<b>cem</b>", "characters"),
    ],
)
def test_bad_names_say_why(raw, reason):
    with pytest.raises(a.DisplayNameError) as excinfo:
        a.validate_display_name(raw)
    assert excinfo.value.reason == reason


def test_keys_ignore_case_and_spacing():
    assert a.display_name_key("Cem Tekcan") == a.display_name_key("cem   tekcan") == a.display_name_key("CEM TEKCAN")
    assert a.display_name_key("Cem Tekcan") != a.display_name_key("CemTekcan")
    assert a.reservation_path("Cem Tekcan") == "display_names/cem tekcan"


def test_key_survives_turkish_dotted_i():
    # "İ" casefolds to "i̇" (i + combining dot), so "İrem" and "irem" are
    # different keys -- the point is only that it doesn't crash and is
    # stable, since Firestore ids are plain strings.
    assert a.display_name_key("İrem") == a.display_name_key("İREM")


# -- leaving a group ------------------------------------------------------------


def group(members, tier=3, settled=False, gid="t3-g0002"):
    doc = {"group_id": gid, "tier": tier, "member_uids": list(members), "member_count": len(members)}
    if settled:
        doc["settlement"] = {"status": "settled"}
    return doc


def test_leaver_comes_out_of_the_member_list():
    fields, desk = a.vacate_group(group(["a", "b", "c"]), {"open_group_id": None}, "b")
    assert fields == {"member_uids": ["a", "c"], "member_count": 2}


def test_gap_is_offered_when_the_desk_has_nowhere_else_to_send_people():
    _, desk = a.vacate_group(group(["a", "b", "c"]), {"open_group_id": None}, "b")
    assert desk == {"tier": 3, "open_group_id": "t3-g0002"}


def test_gap_is_not_offered_over_a_group_already_filling():
    """Pointing the desk back would strand the half-full newer group."""
    _, desk = a.vacate_group(group(["a", "b", "c"]), {"open_group_id": "t3-g0005"}, "b")
    assert desk is None


def test_leaving_a_full_group_reopens_it_when_the_desk_is_empty():
    full = group([f"u{i}" for i in range(CAP)])
    fields, desk = a.vacate_group(full, {"open_group_id": None}, "u0")
    assert fields["member_count"] == CAP - 1
    assert desk["open_group_id"] == "t3-g0002"


def test_settled_group_is_history_and_untouched():
    assert a.vacate_group(group(["a", "b"], settled=True), None, "a") == (None, None)


def test_not_a_member_writes_nothing():
    assert a.vacate_group(group(["a", "b"]), None, "zzz") == (None, None)
    assert a.vacate_group(None, None, "a") == (None, None)
