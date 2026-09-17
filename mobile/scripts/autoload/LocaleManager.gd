extends Node

## Which language the UI speaks. Same shape as ThemeManager: one autoload
## that owns the choice, persists it in user://settings.cfg, and applies it
## to the engine -- here via TranslationServer.set_locale(), which is what
## every tr() call and every auto-translated scene Label/Button reads.
##
## Translations live in res://translations/ as gettext .po files, one per
## language, registered in project.godot's [internationalization] section.
## Keys are the English text itself (Godot's convention): a string with no
## entry in the current language's .po just shows as written, so a missing
## translation is never a blank label. messages.pot there is the master
## key list; a new language is a copy of it with the msgstrs filled in,
## plus one line in LANGUAGES below.
##
## Two things this can't reach: text the BACKEND composes (an HTTP error
## detail, a pack/deal name, a tournament tier name) arrives already
## worded and stays as sent; and a label a script filled with tr() before
## the locale changed keeps the old text until its screen is rebuilt --
## Settings reloads itself on a switch for exactly that reason.

signal language_changed

const SETTINGS_PATH := "user://settings.cfg"
const DEFAULT_LANGUAGE := "en"

## Locale code -> how the language names ITSELF in the Settings dropdown.
## Deliberately not translated: someone who can't read the current language
## has to be able to find their own in the list. Order is the dropdown's.
const LANGUAGES := {
	"en": "English",
	"tr": "Türkçe",
}

var language: String = DEFAULT_LANGUAGE


func _ready() -> void:
	language = _load_saved_language()
	TranslationServer.set_locale(language)


func codes() -> Array:
	return LANGUAGES.keys()


func set_language(code: String) -> void:
	if not LANGUAGES.has(code) or code == language:
		return
	language = code
	TranslationServer.set_locale(code)
	_save_language()
	language_changed.emit()


## The saved choice, else the device's own language when it's one we ship,
## else English. So a Turkish phone opens in Turkish the first time without
## anyone finding the setting.
func _load_saved_language() -> String:
	var config := ConfigFile.new()
	if config.load(SETTINGS_PATH) == OK:
		var saved = config.get_value("display", "language", "")
		if saved is String and LANGUAGES.has(saved):
			return saved
	var device := OS.get_locale_language()
	return device if LANGUAGES.has(device) else DEFAULT_LANGUAGE


func _save_language() -> void:
	var config := ConfigFile.new()
	config.load(SETTINGS_PATH)  # keep any other settings already in the file
	config.set_value("display", "language", language)
	config.save(SETTINGS_PATH)
