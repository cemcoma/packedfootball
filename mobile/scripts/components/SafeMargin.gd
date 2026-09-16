extends MarginContainer

func _ready() -> void:
	_apply_safe_area()
	# Optional: Re-calculate if the player flips their phone around
	get_tree().get_root().size_changed.connect(_apply_safe_area)

func _apply_safe_area() -> void:
	# Get the safe bounds and the total screen size
	var safe_area := DisplayServer.get_display_safe_area()
	var window_size := DisplayServer.window_get_size()

	# Calculate how much space is obscured on each edge
	var m_left = safe_area.position.x
	var m_right = window_size.x - (safe_area.position.x + safe_area.size.x)


	# If you want to keep your existing base margins (e.g., 16px sides, 12px top/bottom),
	# just add them to the safe area calculations:
	add_theme_constant_override("margin_left", m_left)
	add_theme_constant_override("margin_right", m_right)
