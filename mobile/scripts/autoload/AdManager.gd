extends Node

## Rewarded ads, iOS. Consent first (Google UMP -- the GDPR message and,
## on iOS, the IDFA/ATT prompt, both configured in AdMob > Privacy &
## messaging), then the SDK, then one rewarded ad kept loaded.
##
## The reward itself is never claimed by this client. Each ad carries our
## uid and the track as server-side verification options; AdMob calls the
## backend's /ads/ssv when the viewer finishes, and that call pays. After
## on_user_earned_reward this polls /ads/status until the track's counter
## moves, so the shop can say "claimed" -- or "on its way" if AdMob is slow.

## status: "granted" | "pending" | "failed"
signal ad_reward_completed(track: String, status: String)

# Reward tracks, as custom_data on the ad and as keys in ad_counters.
const TRACK_BUCK := "buck_track"
const TRACK_ENERGY := "energy_track"

# Google's test unit ids -- what a debug build loads unless a test device is
# registered. A release export (OS.is_debug_build() == false) uses the live unit.
const REWARDED_TEST_ID_IOS := "ca-app-pub-3940256099942544/1712485313"
const REWARDED_ID_IOS := "ca-app-pub-1704438625576029/5444455793"

# How long to wait for AdMob's callback to land before calling it pending.
const GRANT_POLL_INTERVAL_SECONDS := 2.0
const GRANT_POLL_ATTEMPTS := 8

# Standard Reward Track Steps (credits, bucks) -- mirrors config.AD_REWARD_PATH
const REWARD_STEPS := [
	{"credits": 200, "bucks": 0},
	{"credits": 300, "bucks": 0},
	{"credits": 500, "bucks": 1},
]

var _current_track: String = ""
var _rewarded_ad: RewardedAd = null
var _is_ad_ready: bool = false
var _sdk_started: bool = false

var _full_screen_content_callback := FullScreenContentCallback.new()
var _user_earned_reward_listener := OnUserEarnedRewardListener.new()


static func test_mode() -> bool:
	return OS.is_debug_build()


static func ads_supported() -> bool:
	return OS.get_name() == "iOS"


func _get_unit_id() -> String:
	if OS.get_name() == "iOS":
		# A registered test device gets test creatives off the live unit, so SSV fires.
		if not FirebaseConfig.ADMOB_TEST_DEVICE_IDS.is_empty():
			return REWARDED_ID_IOS
		return REWARDED_TEST_ID_IOS if test_mode() else REWARDED_ID_IOS
	return ""  # Android: no live unit yet


func _ready() -> void:
	_full_screen_content_callback.on_ad_dismissed_full_screen_content = func() -> void:
		_is_ad_ready = false
		_create_and_load_ad()

	_full_screen_content_callback.on_ad_failed_to_show_full_screen_content = func(ad_error) -> void:
		print("on_ad_failed_to_show_full_screen_content: ", ad_error.message)
		_is_ad_ready = false
		if _current_track != "":
			var track := _current_track
			_current_track = ""
			ad_reward_completed.emit(track, "failed")

	_user_earned_reward_listener.on_user_earned_reward = func(rewarded_item) -> void:
		print("on_user_earned_reward, type: ", rewarded_item.type, ", amount: ", rewarded_item.amount)
		if _current_track != "":
			var track := _current_track
			_current_track = ""
			_await_backend_grant(track)

	if ads_supported():
		_gather_consent()


# -- Consent (UMP) -------------------------------------------------------------

func _gather_consent() -> void:
	var request := ConsentRequestParameters.new()
	request.tag_for_under_age_of_consent = false
	if test_mode():
		var debug := ConsentDebugSettings.new()
		debug.debug_geography = DebugGeography.Values.EEA  # exercise the form on a dev device
		request.consent_debug_settings = debug
	UserMessagingPlatform.consent_information.update(request, _on_consent_info_updated, _on_consent_failure)


func _on_consent_info_updated() -> void:
	var info := UserMessagingPlatform.consent_information
	if info.get_is_consent_form_available() and info.get_consent_status() == info.ConsentStatus.REQUIRED:
		UserMessagingPlatform.load_consent_form(
			func(form: ConsentForm) -> void: form.show(func(_error) -> void: _start_ads()),
			_on_consent_failure
		)
	else:
		_start_ads()


func _on_consent_failure(error) -> void:
	# A transient UMP error must not silently switch every ad off; the SDK
	# serves what the stored consent allows.
	if error:
		print("consent: ", error.message)
	_start_ads()


## Whether EEA users must be offered a way to change their choice (a
## Settings entry -- see Settings.gd).
func privacy_options_required() -> bool:
	if not ads_supported():
		return false
	var info := UserMessagingPlatform.consent_information
	return info.get_privacy_options_requirement_status() == info.PrivacyOptionsRequirementStatus.REQUIRED


func show_privacy_options() -> void:
	UserMessagingPlatform.show_privacy_options_form()


# -- SDK + ad loading ----------------------------------------------------------

func _start_ads() -> void:
	if _sdk_started:
		return
	_sdk_started = true
	# Must land before initialize() to cover the first request.
	if not FirebaseConfig.ADMOB_TEST_DEVICE_IDS.is_empty():
		var request_config := RequestConfiguration.new()
		request_config.test_device_ids = FirebaseConfig.ADMOB_TEST_DEVICE_IDS
		MobileAds.set_request_configuration(request_config)
	MobileAds.initialize()
	_create_and_load_ad()


func _create_and_load_ad() -> void:
	_is_ad_ready = false
	if _rewarded_ad:
		_rewarded_ad.destroy()
		_rewarded_ad = null

	var unit_id := _get_unit_id()
	if unit_id == "":
		return

	var rewarded_ad_load_callback := RewardedAdLoadCallback.new()
	rewarded_ad_load_callback.on_ad_failed_to_load = func(ad_error) -> void:
		_is_ad_ready = false
		print("AD ERROR: ", ad_error.message)
		if _current_track != "":
			var track := _current_track
			_current_track = ""
			ad_reward_completed.emit(track, "failed")

	rewarded_ad_load_callback.on_ad_loaded = func(rewarded_ad: RewardedAd) -> void:
		_rewarded_ad = rewarded_ad
		_rewarded_ad.full_screen_content_callback = _full_screen_content_callback
		_is_ad_ready = true

	RewardedAdLoader.new().load(unit_id, AdRequest.new(), rewarded_ad_load_callback)


func show_ad_for_track(track: String) -> bool:
	if not ads_supported():
		# No SDK here: nothing is granted (the backend only pays on AdMob's
		# callback), but the shop's flow can still be walked through.
		print("No ads on ", OS.get_name(), ": pretending the ad ran for track ", track)
		_current_track = ""
		call_deferred("emit_signal", "ad_reward_completed", track, "pending")
		return true

	if _is_ad_ready and _rewarded_ad != null:
		# What AdMob hands back to /ads/ssv, under Google's signature.
		var ssv := ServerSideVerificationOptions.new()
		ssv.user_id = FirebaseAuth.uid
		ssv.custom_data = track
		_rewarded_ad.set_server_side_verification_options(ssv)
		_current_track = track
		_rewarded_ad.show(_user_earned_reward_listener)
		return true

	print("Ad not ready yet!")
	return false


# -- Catalog & State -----------------------------------------------------------

## Builds AdData items consumed by CurrencyPanel's Free tab
func get_ad_deals() -> Array:
	var list: Array = []

	var buck_watched := GameProfile.ad_watched(TRACK_BUCK)
	var buck_max := GameProfile.ad_max(TRACK_BUCK)

	var reward_ad := AdData.new()
	reward_ad.track = TRACK_BUCK
	reward_ad.title = tr("Free Reward")
	reward_ad.description = tr("Watch an ad to progress along your daily reward track.")
	reward_ad.step_current = buck_watched
	reward_ad.step_max = buck_max
	reward_ad.steps = REWARD_STEPS.slice(0, buck_max)

	if buck_watched >= buck_max:
		reward_ad.available = false
		reward_ad.unavailable_reason = tr("Limit reached for today")
	else:
		var step_index := mini(buck_watched, REWARD_STEPS.size() - 1)
		var reward: Dictionary = REWARD_STEPS[step_index]
		reward_ad.reward_credits = int(reward.get("credits", 0))
		reward_ad.reward_bucks = int(reward.get("bucks", 0))
		reward_ad.available = true
	list.append(reward_ad)

	var energy_watched := GameProfile.ad_watched(TRACK_ENERGY)
	var energy_ad_max := GameProfile.ad_max(TRACK_ENERGY)

	var energy_ad := AdData.new()
	energy_ad.track = TRACK_ENERGY
	energy_ad.title = tr("Free Energy")
	energy_ad.description = tr("Watch an ad to instantly recover 1 match energy.")
	energy_ad.step_current = energy_watched
	energy_ad.step_max = energy_ad_max
	energy_ad.reward_energy = 1
	energy_ad.steps = []
	for _i in energy_ad_max:
		energy_ad.steps.append({"energy": 1})

	var cur_energy: int = int(GameProfile.energy.get("energy", 0)) if GameProfile.energy is Dictionary else 0
	var max_energy: int = int(GameProfile.energy.get("max", 10)) if GameProfile.energy is Dictionary and GameProfile.energy.has("max") else 10

	if energy_watched >= energy_ad_max:
		energy_ad.available = false
		energy_ad.unavailable_reason = tr("Limit reached for today")
	elif cur_energy >= max_energy:
		energy_ad.available = false
		energy_ad.unavailable_reason = tr("Energy is full")
	else:
		energy_ad.available = true
	list.append(energy_ad)

	return list


# -- The grant, as seen from here ----------------------------------------------

## Polls /ads/status until AdMob's callback has moved this track's counter,
## applying the balances it reports. "pending" after GRANT_POLL_ATTEMPTS:
## the reward still lands, and the next profile load shows it.
func _await_backend_grant(track: String) -> void:
	var before := GameProfile.ad_watched(track)
	for attempt in GRANT_POLL_ATTEMPTS:
		var res: Dictionary = await Backend.call_endpoint(HTTPClient.METHOD_GET, "/ads/status")
		if res.get("ok", false):
			var data: Dictionary = res.get("data", {})
			var now := GameProfile.ad_counter_field(data.get("ad_counters"), track, "watched", before)
			if now > before:
				_apply_status(data)
				ad_reward_completed.emit(track, "granted")
				return
		await get_tree().create_timer(GRANT_POLL_INTERVAL_SECONDS).timeout
	ad_reward_completed.emit(track, "pending")


func _apply_status(data: Dictionary) -> void:
	var counters = data.get("ad_counters")
	if counters is Dictionary:
		GameProfile.ad_counters = counters
	GameProfile.apply_currency_balances(data.get("credits_remaining"), data.get("bucks_remaining"))
	GameProfile.apply_energy(data.get("energy"))
