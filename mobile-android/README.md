# DARSON Guard for Android

Native Android guard response client. It shows only tasks assigned to the signed-in guard, opens protected evidence, acknowledges a task, and submits Real incident, False alarm or Need help with an observation. The on-site desk remains the local fallback.

For a quick UI review, download [DARSON-Guard-preview.apk](DARSON-Guard-preview.apk). This is a debug build with the **SIMULATED** task preview; it has no Firebase or site sign-in configuration and will not receive real alerts. Rebuild with the settings below for a connected pilot.

## Build a test APK

1. Install JDK 17, Android SDK API 36, Android Build Tools 35, and Gradle 8.13 (or open this folder in Android Studio and let it install the required SDK). The Gradle wrapper is included.
2. Copy `guard.properties.example` to `guard.properties`. Set the actual **HTTPS** API base, exact OIDC issuer and mobile public client ID. The client must allow redirect URI `com.darson.guard:/oauth2redirect`, authorization code with PKCE, and an access token whose audience and tenant/site claims match the DARSON backend configuration. Do not put a client secret in the app.
3. Create an Android app with package `com.darson.guard` in the Firebase project used by the backend. Put its `google-services.json` in `app/`. Without this file the APK builds, but phone push registration is disabled.
4. On Windows run `.\build-apk.ps1`. It uses the Gradle wrapper, builds outside the OneDrive folder, and copies the installable APK to `DARSON-Guard-preview.apk`. On another OS run `./gradlew :app:assembleDebug`; the APK is `app/build/outputs/apk/debug/app-debug.apk`.

The debug APK is signed with an Android development key. Build a separately signed release for a real pilot; retain that signing key so updates install over the previous version. Do not commit `guard.properties`, `google-services.json`, signing keys or service-account JSON.

If the server and identity provider have not been configured, the debug APK offers a clearly marked **SIMULATED** task preview. Its buttons change only local sample UI state; no alert is sent and no response reaches the server.

Emulator captures of the simulated flow: [task list](demo/demo-task-list.png), [task detail](demo/demo-task-detail.png), and [outcome form](demo/demo-outcome.png).

## Server setup for phone alerts

- Set `DARSON_NOTIFICATION_PROVIDER=fcm` and mount a Google service-account JSON file read-only into **both** the backend and worker containers. The [Compose example](../deploy/mobile-fcm.compose.example.yml) shows the mount and in-container path. The worker needs outbound HTTPS to Google's OAuth and FCM endpoints. Grant the service account permission to send FCM messages for the selected Firebase project. Never place the service-account JSON in the Android app.
- Give each guard an OIDC account and a responder grant for the correct tenant/site. Schedule that guard at the camera's assigned post. On sign-in the phone replaces that guard's existing Telegram/WhatsApp contact with its Firebase Installation ID; one phone per guard/site is supported in this first version. Supervisors may retain Telegram/WhatsApp contacts for escalation.
- Publish the DARSON API on an authenticated **HTTPS** address reachable from guards' mobile internet. A private site LAN address will not work on cellular data without a VPN. The app will not send a bearer token over HTTP.
- Test a real assigned task end to end. Server acceptance by FCM is not phone delivery or guard acknowledgement. Keep the desk alarm and acknowledgement deadline escalation active.

## Phone behavior and limits

- FCM sends a data-only, high-priority message to the phone's Firebase Installation ID (FID), containing only a task ID. The phone displays a generic lock-screen notice and fetches details from DARSON after authentication. Notification permission is required on Android 13+.
- The app stores its authorization state using an Android Keystore key, blocks screenshots in configured builds, and does not request location, camera or contact access. The unconfigured synthetic preview allows screenshots for demos. Protected images are kept in memory; clips are streamed through the authenticated endpoint.
- The app has no offline push path. If internet, Google Play services, notification permission, or the site API is unavailable, the guard must use the desk/radio process. These failure cases need testing on the actual guard phones.
- A sign-out removes the current phone registration from DARSON before clearing the local session. If removal fails, the app keeps the session so the guard can retry or ask a supervisor to replace the contact.

## Still required for a real pilot

Firebase project and service-account setup, an OIDC mobile client, public HTTPS routing or VPN, guard roster and supervisor contact, camera access, a signed release key, and staged tests on the actual phones and network are not supplied by this repository.
