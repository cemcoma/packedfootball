extends RefCounted
class_name FirebaseConfigExample

## Copy this file to FirebaseConfig.gd (gitignored) and fill in your own
## project's values -- see packedfootball/firebase_config.example.py, same
## idea, same values, just also needed here since GDScript can't import a
## Python module.

const FIREBASE_API_KEY := "your-firebase-api-key"
const FIREBASE_PROJECT_ID := "your-firebase-project-id"
const BACKEND_URL := "https://your-cloud-run-service-url"
