"""Definitional fields for the Deals tab's timed offers -- the DB-based
counterpart to packEngine.py's PACK_DATABASE, same relationship: this dict
is the code-side source of truth for what a deal *is*, pushed into existing
Firestore deals/{deal_id} docs by backend/scripts/sync_deal_definitions.py.
Operational state (active/expires_at/visible/available_at/times_redeemed)
only ever lives in Firestore, never here -- see sync_deal_definitions.py's
own docstring for why (an admin flipping a deal off, or a real redemption
count, must never get clobbered back to a code default on the next sync).

backend/main.py never imports this module directly -- its /deals/list and
/deals/redeem endpoints only ever read the live Firestore doc, the same
boundary PACK_DATABASE already has with main.py's pack endpoints. This
keeps "what's live right now" strictly a Firestore question, answerable
without redeploying, exactly like packs.

Deal ids are descriptive string slugs, the same arrangement PACK_DATABASE
moved to: easier for an admin to recognize in the Firestore console than an
arbitrary number, and the console lists them in a meaningful order.

Reward scope for now is currency only (reward_credits/reward_bucks) --
granting a free pack/card as part of a deal is a reasonable future
extension, not built here.
"""

DEAL_DATABASE = {
    "1": {
        "name": "Welcome Bundle",
        "description": "A one-time thank-you for new managers -- extra credits for a small bucks spend.",
        "cost_currency": "bucks",
        "cost_amount": 5,
        "reward_credits": 1500,
        "reward_bucks": 0,
    },
    "2": {
        "name": "Midweek Credits Boost",
        "description": "A limited-run credits top-up at a better rate than the standard Exchange tab.",
        "cost_currency": "bucks",
        "cost_amount": 50,
        "reward_credits": 6000,
        "reward_bucks": 0,
    },
}
