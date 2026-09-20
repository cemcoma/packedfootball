extends Node

signal ad_reward_completed(track: String, success: bool)

### SUPER IMPORTANT ### DUPER IPORTANT ###
#
#  Change test mode before relase!
#

const TEST_MODE: bool = true

# Google's official Test IDs for Rewarded Video Ads
const REWARDED_TEST_ID_ANDROID := "ca-app-pub-3940256099942544/5224354917"
const REWARDED_TEST_ID_IOS := "ca-app-pub-3940256099942544/1712485313"

const REWARDED_ID_ANDROID := "yok"
const REWARDED_ID_IOS := "ca-app-pub-1704438625576029/5444455793"

func _get_unit_id() -> String:
	if OS.get_name() == "iOS":
		return REWARDED_TEST_ID_IOS if TEST_MODE else REWARDED_ID_IOS
	elif OS.get_name() == "Android":
		return REWARDED_TEST_ID_ANDROID if TEST_MODE else REWARDED_ID_ANDROID
	return ""

# Standard Reward Track Steps (credits, bucks)
const REWARD_STEPS := [
	{"credits": 200, "bucks": 0},
	{"credits": 300, "bucks": 0},
	{"credits": 500, "bucks": 1},
]

# Ad tracking state
var reward_ads_watched: int = 0
var reward_ads_max: int = 3
var energy_ads_watched: int = 0
var energy_ads_max: int = 3

var _current_track: String = ""
var _rewarded_ad: RewardedAd = null
var _is_ad_ready: bool = false

var _full_screen_content_callback := FullScreenContentCallback.new()
var _user_earned_reward_listener := OnUserEarnedRewardListener.new()


func _ready() -> void:
	MobileAds.initialize()

	_full_screen_content_callback.on_ad_dismissed_full_screen_content = func() -> void:
		print("on_ad_dismissed_full_screen_content")
		_is_ad_ready = false
		_create_and_load_ad()

	_full_screen_content_callback.on_ad_failed_to_show_full_screen_content = func(ad_error) -> void:
		print("on_ad_failed_to_show_full_screen_content: ", ad_error.message)
		_is_ad_ready = false
		if _current_track != "":
			ad_reward_completed.emit(_current_track, false)
			_current_track = ""

	_user_earned_reward_listener.on_user_earned_reward = func(rewarded_item) -> void:
		print("on_user_earned_reward, type: ", rewarded_item.type, ", amount: ", rewarded_item.amount)
		if _current_track != "":
			var track := _current_track
			_current_track = ""
			_claim_backend_reward(track)

	if OS.get_name() in ["Android", "iOS"]:
		_create_and_load_ad()


func _create_and_load_ad() -> void:
	_is_ad_ready = false

	if _rewarded_ad:
		_rewarded_ad.destroy()
		_rewarded_ad = null
		

	var unit_id = REWARDED_TEST_ID_IOS if OS.get_name() == "iOS" else REWARDED_TEST_ID_ANDROID

	var rewarded_ad_load_callback := RewardedAdLoadCallback.new()
	rewarded_ad_load_callback.on_ad_failed_to_load = func(adError) -> void:
		_is_ad_ready = false
		print("AD ERROR: ", adError.message)
		if _current_track != "":
			ad_reward_completed.emit(_current_track, false)
			_current_track = ""

	rewarded_ad_load_callback.on_ad_loaded = func(rewarded_ad : RewardedAd) -> void:
		print("rewarded ad loaded: ", rewarded_ad._uid)
		_rewarded_ad = rewarded_ad
		_rewarded_ad.full_screen_content_callback = _full_screen_content_callback
		_is_ad_ready = true

	RewardedAdLoader.new().load(unit_id, AdRequest.new(), rewarded_ad_load_callback)


func show_ad_for_track(track: String) -> bool:
	# PC Testing Bypass so you can test rewards in the editor
	if OS.get_name() not in ["Android", "iOS"]:
		print("PC Editor Detected: Mocking a successful ad view for track: ", track)
		_current_track = track
		_claim_backend_reward(track)
		return true

	if _is_ad_ready and _rewarded_ad != null:
		_current_track = track
		_rewarded_ad.show(_user_earned_reward_listener)
		return true
		
	print("Ad not ready yet!")
	return false


# -- Catalog & State -----------------------------------------------------------

## Builds AdData items consumed by CurrencyPanel's Free tab
func get_ad_deals() -> Array:
	var list: Array = []

	var reward_ad := AdData.new()
	reward_ad.track = "reward"
	reward_ad.title = tr("Free Reward")
	reward_ad.description = tr("Watch an ad to progress along your daily reward track.")
	reward_ad.step_current = GameProfile.reward_ads_watched
	reward_ad.step_max = GameProfile.reward_ads_max

	if GameProfile.reward_ads_watched >= GameProfile.reward_ads_max:
		reward_ad.available = false
		reward_ad.unavailable_reason = tr("Limit reached for today")
	else:
		var step_index := mini(GameProfile.reward_ads_watched, REWARD_STEPS.size() - 1)
		var reward: Dictionary = REWARD_STEPS[step_index]
		reward_ad.reward_credits = int(reward.get("credits", 0))
		reward_ad.reward_bucks = int(reward.get("bucks", 0))
		reward_ad.available = true
	list.append(reward_ad)

	var energy_ad := AdData.new()
	energy_ad.track = "energy"
	energy_ad.title = tr("Free Energy")
	energy_ad.description = tr("Watch an ad to instantly recover 1 match energy.")
	energy_ad.step_current = GameProfile.energy_ads_watched
	energy_ad.step_max = GameProfile.energy_ads_max
	energy_ad.reward_energy = 1

	var cur_energy: int = int(GameProfile.energy.get("energy", 0)) if GameProfile.energy is Dictionary else 0
	var max_energy: int = int(GameProfile.energy.get("max", 10)) if GameProfile.energy is Dictionary and GameProfile.energy.has("max") else 10

	if GameProfile.energy_ads_watched >= GameProfile.energy_ads_max:
		energy_ad.available = false
		energy_ad.unavailable_reason = tr("Limit reached for today")
	elif cur_energy >= max_energy:
		energy_ad.available = false
		energy_ad.unavailable_reason = tr("Energy is full")
	else:
		energy_ad.available = true
	list.append(energy_ad)

	return list


func claim_ad_reward(track: String) -> Dictionary:
	var res: Dictionary = await Backend.call_endpoint(
		HTTPClient.METHOD_POST, "/ads/reward", {"track": track}
	)

	if res.get("ok", false):
		var data: Dictionary = res.get("data", {})
		if track == "reward":
			GameProfile.reward_ads_watched = _int(data, "reward_ads_watched", GameProfile.reward_ads_watched)
			GameProfile.reward_ads_max = _int(data, "reward_ads_max", GameProfile.reward_ads_max)
			GameProfile.apply_currency_balances(
				data.get("credits_remaining"),
				data.get("bucks_remaining")
			)
		elif track == "energy":
			GameProfile.energy_ads_watched = _int(data, "energy_ads_watched", GameProfile.energy_ads_watched)
			GameProfile.energy_ads_max = _int(data, "energy_ads_max", GameProfile.energy_ads_max)
			await GameProfile.refresh_energy()

	return res


func reset() -> void:
	reward_ads_watched = 0
	reward_ads_max = 3
	energy_ads_watched = 0
	energy_ads_max = 3


func _claim_backend_reward(track: String) -> void:
	var res: Dictionary = await claim_ad_reward(track)
	var ok: bool = res.get("ok", false)
	ad_reward_completed.emit(track, ok)


static func _int(doc: Dictionary, key: String, default_val: int = 0) -> int:
	var val = doc.get(key)
	return int(val) if typeof(val) in [TYPE_INT, TYPE_FLOAT] else default_val
