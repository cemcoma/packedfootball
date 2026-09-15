class_name SquadOptimizer
extends RefCounted

## Picks the strongest possible XI for a formation out of the cards an
## account owns -- the "Auto" button on the Squad screen.
##
## This is NOT greedy, and that is the whole point. Filling slots one at a
## time, best-first, gets the wrong answer routinely: a 78 CB who is also
## eligible at LB gets taken by whichever slot is considered first, and if
## that is LB the CB slot is left to a 61. Greedy has no way to see that
## moving him back and giving LB the 74 LB-proper is worth more overall.
##
## So the assignment is solved properly, as a maximum-weight bipartite
## matching (the Hungarian/Jonker-Volgenant shortest-augmenting-path
## method). 11 slots against at most ~111 cards is nothing -- a few thousand
## operations -- and it is provably optimal rather than "usually fine".
##
## Ratings come from effective_overall(), which mirrors what the match
## engine actually does to an out-of-position player (gameEngine.py's
## OUT_OF_POSITION_PENALTY), so the number this maximises is the number the
## squad will really field.

## What the engine multiplies every non-tendency attribute by when a player
## fills a slot whose role isn't their own position. Because overall() is a
## weighted mean over exactly the fields that get scaled (tendencies and
## physicals are excluded from both), scaling them all by 0.9 scales the
## overall by 0.9 too -- so this can be applied to the overall directly
## instead of rebuilding the attribute set.
##
## Keep in lockstep with packedfootball/gameEngine.py's OUT_OF_POSITION_PENALTY.
const OUT_OF_POSITION_FACTOR := 0.9

## The cost charged for pairing a slot with a player who can't fill it.
## Large enough that the solver will always prefer ANY legal assignment over
## one blocked edge -- eleven slots times a 100 overall is 1100, so at a
## million the two can never trade against each other. The effect is
## lexicographic and deliberate: fill as many slots as possible FIRST, then
## maximise the rating of what's filled.
const BLOCKED_COST := 1000000.0

const _INF := 1.0e18


## What a card is actually worth in a given slot -- the card's own overall
## when it's their position, and the engine's 0.9x otherwise.
##
## Deliberately does NOT check eligibility: it answers "what would this be
## worth", and the engine applies its penalty on any mismatch at all (see
## gameEngine.py:186). is_eligible() is the separate question of whether the
## UI would let you do it in the first place.
static func effective_overall(card: PlayerCard, role: String) -> int:
	if card.position == role:
		return card.overall()
	return int(round(float(card.overall()) * OUT_OF_POSITION_FACTOR))


## Whether a card may fill this slot at all -- their exact position, or one
## Formations calls similar. Same rule the Squad screen's picker enforces,
## so Auto can never produce a lineup you couldn't have built by hand.
static func is_eligible(card: PlayerCard, role: String) -> bool:
	return card.position == role or Formations.is_similar_position(card.position, role)


## The average effective overall of an assignment -- the "Squad Overall"
## number. Slots left empty are skipped rather than counted as zero, so a
## half-built lineup reads as the strength of what's in it.
##
## `slot_ids` is a slot-indexed array of player ids (GameProfile's
## slot_assignment), `cards` the id -> PlayerCard map.
static func squad_overall(formation_name: String, slot_ids: Array, cards: Dictionary) -> int:
	var slots := Formations.get_formation(formation_name)
	var total := 0
	var count := 0
	for i in range(mini(slot_ids.size(), slots.size())):
		var player_id: String = slot_ids[i]
		if player_id == "" or not cards.has(player_id):
			continue
		total += effective_overall(cards[player_id], slots[i]["role"])
		count += 1
	if count == 0:
		return 0
	return int(round(float(total) / float(count)))


## The best XI available: returns a slot-indexed Array of player ids, with
## "" in any slot no eligible card was left for.
##
## `candidate_ids` is every card that may be used -- normally the whole
## collection, since Auto reassigns the XI as well as the bench. Order is
## irrelevant to the result except as a tiebreak between equal-rated cards.
static func best_assignment(formation_name: String, candidate_ids: Array, cards: Dictionary) -> Array:
	var slots := Formations.get_formation(formation_name)
	var n: int = slots.size()

	var result: Array = []
	result.resize(n)
	result.fill("")

	# Only cards we actually hold can be placed; a dangling id in the roster
	# would otherwise index into `cards` and crash the solver.
	var usable: Array = []
	for player_id in candidate_ids:
		if cards.has(player_id):
			usable.append(player_id)
	if usable.is_empty():
		return result

	# The solver needs at least as many columns as rows. Padding with
	# all-blocked columns is what lets a squad with only 7 eligible players
	# still produce a valid partial answer instead of failing.
	var real_columns: int = usable.size()
	var m: int = maxi(n, real_columns)

	var cost: Array = []
	for i in range(n):
		var role: String = slots[i]["role"]
		var row: Array = []
		row.resize(m)
		row.fill(BLOCKED_COST)
		for j in range(real_columns):
			var card: PlayerCard = cards[usable[j]]
			if is_eligible(card, role):
				# Negated: the solver minimises, we want the best squad.
				row[j] = -float(effective_overall(card, role))
		cost.append(row)

	var matching := _solve(cost, n, m)
	for i in range(n):
		var j: int = matching[i]
		# A slot matched to a padding column, or to a real card it isn't
		# allowed to field, means nothing eligible was left for it.
		if j >= 0 and j < real_columns and cost[i][j] < BLOCKED_COST:
			result[i] = usable[j]
	return result


## Rectangular assignment by the shortest-augmenting-path method, minimising
## total cost. `a` is n x m (n <= m), zero-indexed. Returns an n-length array
## of row -> column, or -1 for an unmatched row.
##
## Kept as the textbook 1-indexed formulation with a sentinel row 0, because
## that is the form the algorithm is actually published in and a "tidied up"
## zero-indexed rewrite is exactly how the potentials get subtly wrong. The
## +1 offsets on every access into `a` are the price of that.
static func _solve(a: Array, n: int, m: int) -> Array:
	var u: Array = []
	u.resize(n + 1)
	u.fill(0.0)
	var v: Array = []
	v.resize(m + 1)
	v.fill(0.0)
	var p: Array = []  # column -> row currently matched to it (0 = free)
	p.resize(m + 1)
	p.fill(0)
	var way: Array = []  # column -> the column we reached it from
	way.resize(m + 1)
	way.fill(0)

	for i in range(1, n + 1):
		p[0] = i
		var j0: int = 0
		var minv: Array = []
		minv.resize(m + 1)
		minv.fill(_INF)
		var used: Array = []
		used.resize(m + 1)
		used.fill(false)

		while true:
			used[j0] = true
			var i0: int = p[j0]
			var delta: float = _INF
			var j1: int = -1
			for j in range(1, m + 1):
				if used[j]:
					continue
				var cur: float = a[i0 - 1][j - 1] - u[i0] - v[j]
				if cur < minv[j]:
					minv[j] = cur
					way[j] = j0
				if minv[j] < delta:
					delta = minv[j]
					j1 = j
			for j in range(m + 1):
				if used[j]:
					u[p[j]] += delta
					v[j] -= delta
				else:
					minv[j] -= delta
			j0 = j1
			if p[j0] == 0:
				break

		# Walk the augmenting path back, flipping each edge along it.
		while j0 != 0:
			var j1: int = way[j0]
			p[j0] = p[j1]
			j0 = j1

	var result: Array = []
	result.resize(n)
	result.fill(-1)
	for j in range(1, m + 1):
		if p[j] != 0:
			result[p[j] - 1] = j - 1
	return result
