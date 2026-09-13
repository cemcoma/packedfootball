extends Control

## Full-screen modal: a scrim + rotating spinner + status label, reusable
## anywhere a screen needs to say "working on it" while awaiting something --
## Play.gd's matchmaking, MatchResult.gd's/MatchPlayback.gd's post-match
## squad refresh (see mobile/README.md's "Player card stats after a match"
## section). Deliberately dumb: just a settable status label plus the
## inherited `visible` -- callers own their own show/hide timing and any
## staged-status logic of their own (e.g. Play.gd's "Finding..." ->
## "Simulating..." narrative over a timer is Play.gd's concern, not this
## component's).

@onready var _status_label: Label = %StatusLabel


func set_status(status: String) -> void:
	_status_label.text = status
