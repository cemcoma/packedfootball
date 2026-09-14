extends RefCounted
class_name RevenueCatConfigExample

## Copy this file to RevenueCatConfig.gd (gitignored) and fill in your own
## project's RevenueCat public API key -- same idea as FirebaseConfig.gd
## right next to it. This is RevenueCat's PUBLIC key (the `appl_...` one
## from their dashboard, meant to ship inside the client binary -- not
## their secret server key, which never belongs on the client at all) --
## gitignored anyway for consistency with how this project already treats
## every other client config value, not because this specific key is
## actually sensitive.

const REVENUECAT_IOS_API_KEY := "appl_your-ios-public-key"
const REVENUECAT_ANDROID_API_KEY := "goog_your-android-public-key"
