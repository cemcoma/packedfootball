extends Node

## Card and pack art that ships without an app update (backend/services/remote_art.py).
## The manifest rides on /account/bootstrap and /pack/list; each image is
## downloaded once per device into user://remote_art/ and checked by sha256.
## Kinds are the manifest's own keys: "cards" (by tier) and "packs" (by sprite_key).

signal art_ready(kind: String, key: String, texture: Texture2D)

const CACHE_DIR := "user://remote_art/"
const MANIFEST_PATH := CACHE_DIR + "manifest.json"
const CARD_SPRITE_DIR := "res://sprites/player_cards/"
const KINDS := ["cards", "packs"]
const MAX_DOWNLOADS := 2
const MAX_BYTES := 2_000_000
const DOWNLOAD_TIMEOUT := 20.0
## A failed download isn't retried sooner than this, so a bad URL can't hammer the bucket.
const RETRY_AFTER_MSEC := 60_000

var _manifest := {"cards": {}, "packs": {}}
var _textures := {}  # "<kind>/<key>" -> Texture2D
var _queue: Array[String] = []
var _active := {}  # "<kind>/<key>" -> true while downloading
var _failed_at := {}  # "<kind>/<key>" -> ticks msec
var _key_re := RegEx.create_from_string("^[A-Za-z0-9_-]+$")
var _sha_re := RegEx.create_from_string("^[0-9a-f]{64}$")


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(CACHE_DIR)
	if FileAccess.file_exists(MANIFEST_PATH):
		var saved = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST_PATH))
		if saved is Dictionary:
			_manifest = _sanitize(saved)


## From a backend reply's "art". Absent (older backend, failed call) keeps the saved copy.
func apply_manifest(raw) -> void:
	if not (raw is Dictionary):
		return
	var manifest := _sanitize(raw)
	if manifest == _manifest:
		return
	for kind in KINDS:
		for key in _manifest[kind]:
			if manifest[kind].get(key) != _manifest[kind][key]:
				_textures.erase(kind + "/" + key)
	_manifest = manifest
	var file := FileAccess.open(MANIFEST_PATH, FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(_manifest))
	_prune_files()


## Remote art once downloaded, else the bundled tier art, else the family's.
## A missing download is started; art_ready fires when it lands.
func card_texture(tier: String) -> Texture2D:
	var remote := _remote("cards", tier)
	if remote != null:
		return remote
	for path in [CARD_SPRITE_DIR + tier + ".png", CARD_SPRITE_DIR + PlayerCard.tier_family(tier) + ".png"]:
		if ResourceLoader.exists(path):
			return load(path)
	return null


## Null when there is no remote art for the key (or it is still downloading).
func pack_texture(sprite_key: String) -> Texture2D:
	return _remote("packs", sprite_key)


## The manifest's label colour for a tier, null for the theme default.
func text_color(tier: String) -> Variant:
	var hex: String = _manifest["cards"].get(tier, {}).get("text_color", "")
	return Color.html(hex) if Color.html_is_valid(hex) else null


## Starts downloads for whatever of these isn't on disk yet.
func prefetch(kind: String, keys: Array) -> void:
	for key in keys:
		var entry: Dictionary = _manifest[kind].get(key, {})
		if not entry.is_empty() and not FileAccess.file_exists(_path(kind, key, entry)):
			_request(kind, key)


## Waits until these are downloaded or the timeout passes, whichever is first.
func ensure(kind: String, keys: Array, timeout_s: float) -> void:
	prefetch(kind, keys)
	var deadline := Time.get_ticks_msec() + int(timeout_s * 1000.0)
	while Time.get_ticks_msec() < deadline and keys.any(func(key): return _is_pending(kind + "/" + str(key))):
		await get_tree().process_frame


func _remote(kind: String, key: String) -> Texture2D:
	var entry: Dictionary = _manifest[kind].get(key, {})
	if entry.is_empty():
		return null
	var id := kind + "/" + key
	if _textures.has(id):
		return _textures[id]
	var path := _path(kind, key, entry)
	if FileAccess.file_exists(path):
		var texture := _load(path)
		if texture != null:
			_textures[id] = texture
			return texture
		DirAccess.remove_absolute(path)  # corrupt on disk: fetch it again
	_request(kind, key)
	return null


func _path(kind: String, key: String, entry: Dictionary) -> String:
	return CACHE_DIR + "%s_%s.%s.webp" % [kind, key, str(entry["sha256"]).left(12)]


func _load(path: String) -> Texture2D:
	var image := Image.new()
	if image.load_webp_from_buffer(FileAccess.get_file_as_bytes(path)) != OK:
		return null
	return ImageTexture.create_from_image(image)


func _is_pending(id: String) -> bool:
	return _active.has(id) or _queue.has(id)


func _request(kind: String, key: String) -> void:
	var id := kind + "/" + key
	if _is_pending(id) or Time.get_ticks_msec() - _failed_at.get(id, -RETRY_AFTER_MSEC) < RETRY_AFTER_MSEC:
		return
	_queue.append(id)
	_pump()


func _pump() -> void:
	while _active.size() < MAX_DOWNLOADS and not _queue.is_empty():
		var id: String = _queue.pop_front()
		_active[id] = true
		_download(id)


func _download(id: String) -> void:
	var kind := id.get_slice("/", 0)
	var key := id.get_slice("/", 1)
	var entry: Dictionary = _manifest[kind].get(key, {})
	var texture: Texture2D = null
	if not entry.is_empty():
		texture = await _fetch(kind, key, entry)
	_active.erase(id)
	if _manifest[kind].get(key, {}) != entry:
		_request(kind, key)  # the art changed mid-download
	elif texture != null:
		_textures[id] = texture
		_failed_at.erase(id)
		art_ready.emit(kind, key, texture)
	else:
		_failed_at[id] = Time.get_ticks_msec()
	_pump()


## Downloads to a .part file and only keeps it if the sha256 matches the manifest.
func _fetch(kind: String, key: String, entry: Dictionary) -> Texture2D:
	var path := _path(kind, key, entry)
	var part := path + ".part"
	var http := HTTPRequest.new()
	http.download_file = part
	http.body_size_limit = MAX_BYTES
	http.timeout = DOWNLOAD_TIMEOUT
	add_child(http)
	var result: Array = [HTTPRequest.RESULT_CANT_CONNECT, 0]
	if http.request(entry["url"]) == OK:
		result = await http.request_completed
	http.queue_free()
	if result[0] != HTTPRequest.RESULT_SUCCESS or result[1] != 200 or FileAccess.get_sha256(part) != entry["sha256"]:
		push_warning("Remote art %s/%s failed (result %d, HTTP %d)" % [kind, key, result[0], result[1]])
		DirAccess.remove_absolute(part)
		return null
	DirAccess.remove_absolute(path)
	DirAccess.rename_absolute(part, path)
	return _load(path)


## Deletes cached files the manifest no longer points at (replaced art, old .part files).
func _prune_files() -> void:
	var keep := {MANIFEST_PATH.get_file(): true}
	for kind in KINDS:
		for key in _manifest[kind]:
			keep[_path(kind, key, _manifest[kind][key]).get_file()] = true
			keep[_path(kind, key, _manifest[kind][key]).get_file() + ".part"] = true
	for file in DirAccess.get_files_at(CACHE_DIR):
		if not keep.has(file):
			DirAccess.remove_absolute(CACHE_DIR + file)


## Only entries with a safe key, an http(s) url and a sha256 survive.
func _sanitize(raw: Dictionary) -> Dictionary:
	var out := {}
	for kind in KINDS:
		out[kind] = {}
		var entries = raw.get(kind)
		if not (entries is Dictionary):
			continue
		for key in entries:
			var entry = entries[key]
			if not (key is String and entry is Dictionary and _key_re.search(key)):
				continue
			var url = entry.get("url")
			var sha = entry.get("sha256")
			if not (url is String and url.begins_with("http") and sha is String and _sha_re.search(sha)):
				continue
			var clean := {"url": url, "sha256": sha}
			if entry.get("text_color") is String:
				clean["text_color"] = entry["text_color"]
			out[kind][key] = clean
	return out
