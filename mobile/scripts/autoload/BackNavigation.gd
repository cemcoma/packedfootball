extends Node

## Android's back button/gesture presses the current screen's %BackButton,
## exactly as a tap would; screens without one (Menu, a match) ignore it.
## Needs application/config/quit_on_go_back off, or back quits the app.

# LoadingPopup joins this; one showing swallows back like it swallows taps.
const LOADING_POPUP_GROUP := "loading_popup"


func _notification(what: int) -> void:
	if what != NOTIFICATION_WM_GO_BACK_REQUEST:
		return
	for popup in get_tree().get_nodes_in_group(LOADING_POPUP_GROUP):
		if popup.is_visible_in_tree():
			return
	var screen := get_tree().current_scene
	if screen == null:
		return
	var back_button := screen.get_node_or_null("%BackButton") as BaseButton
	if back_button != null and back_button.is_visible_in_tree() and not back_button.disabled:
		# Deferred: the root is mid-propagation here, so a scene change now errors.
		back_button.pressed.emit.call_deferred()
