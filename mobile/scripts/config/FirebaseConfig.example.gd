extends RefCounted
class_name FirebaseConfigExample

## Copy this file to FirebaseConfig.gd (gitignored) and fill in your own
## project's values -- see packedfootball/firebase_config.example.py, same
## idea, same values, just also needed here since GDScript can't import a
## Python module.

const FIREBASE_API_KEY := "your-firebase-api-key"
const FIREBASE_PROJECT_ID := "your-firebase-project-id"
const BACKEND_URL := "https://your-cloud-run-service-url"

## AdMob test device ids -- the hash the GMA SDK prints on the first ad request
## (Xcode console / logcat), not the IDFA or GAID. Non-empty makes that
## platform's debug builds request the live unit.
const ADMOB_TEST_DEVICE_IDS_IOS: Array[String] = []
const ADMOB_TEST_DEVICE_IDS_ANDROID: Array[String] = []
