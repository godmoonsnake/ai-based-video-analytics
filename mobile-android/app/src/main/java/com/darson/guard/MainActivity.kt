package com.darson.guard

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.VideoView
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.installations.FirebaseInstallations
import net.openid.appauth.AuthState
import net.openid.appauth.AuthorizationException
import net.openid.appauth.AuthorizationRequest
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import net.openid.appauth.AuthorizationServiceConfiguration
import net.openid.appauth.ResponseTypeValues
import org.json.JSONArray
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date

class MainActivity : Activity() {
    private val background = Color.rgb(14, 20, 30)
    private val panel = Color.rgb(25, 33, 45)
    private val ink = Color.rgb(240, 244, 250)
    private val muted = Color.rgb(160, 174, 190)
    private val accent = Color.rgb(78, 177, 245)
    private val warning = Color.rgb(255, 190, 92)
    private lateinit var root: LinearLayout
    private lateinit var authStore: AuthStore
    private lateinit var authService: AuthorizationService
    private var authState = AuthState()
    private var api: GuardApi? = null
    private var actorName = "Guard"
    private var siteName = ""
    private var activeTaskId: String? = null
    private var pendingTaskId: String? = null
    private var pushMessage = ""
    private var busy = false
    private var accountVerified = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The unconfigured preview contains synthetic data and can be captured for demos.
        // Any build connected to a real API keeps task details out of screenshots.
        if (configured()) window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        authStore = AuthStore(this)
        authService = AuthorizationService(this)
        authStore.read()?.let { saved ->
            try { authState = AuthState.jsonDeserialize(saved) } catch (_: Exception) { authStore.clear() }
        }
        pendingTaskId = intent.getStringExtra("task_id")
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(22), dp(20), dp(20))
            setBackgroundColor(this@MainActivity.background)
        }
        setContentView(ScrollView(this).apply { isFillViewport = true; addView(root) })
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("darson_alerts", "Guard alerts", NotificationManager.IMPORTANCE_HIGH)
        )
        if (!configured()) renderSetup() else if (authState.isAuthorized) verifyAccount() else renderLogin()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pendingTaskId = intent.getStringExtra("task_id")
        if (api != null && pendingTaskId != null) {
            val id = pendingTaskId!!
            pendingTaskId = null
            loadDetail(id)
        }
    }

    override fun onResume() {
        super.onResume()
        if (!accountVerified || !BuildConfig.FCM_CONFIGURED) return
        val prefs = getSharedPreferences("guard_device", MODE_PRIVATE)
        val uploaded = prefs.getString("uploaded_installation_id", null)
        val allowed = Build.VERSION.SDK_INT < 33 ||
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (!allowed && uploaded != null) {
            api?.json("DELETE", "/api/v1/pilot/mobile-device",
                JSONObject().put("installation_id", uploaded)) { _, error ->
                if (error == null) {
                    prefs.edit().remove("uploaded_installation_id").apply()
                    pushMessage = "Notifications are off; this phone was removed from alerts."
                } else pushMessage = "Notifications are off; ask the desk to remove this phone."
                if (activeTaskId == null) loadTasks()
            }
        } else if (allowed && prefs.getString("installation_id", null) != uploaded) {
            preparePush()
        }
    }

    private fun configured() = BuildConfig.API_BASE.startsWith("https://") &&
        BuildConfig.OIDC_ISSUER.startsWith("https://") && BuildConfig.OIDC_CLIENT_ID.isNotBlank()

    private fun renderSetup() {
        clear("SETUP REQUIRED")
        heading("DARSON Guard")
        body("This APK needs a public HTTPS DARSON API address and an OIDC mobile client before guards can sign in.")
        body("Add DARSON_API_BASE, DARSON_OIDC_ISSUER and DARSON_OIDC_CLIENT_ID to Gradle properties, then rebuild the APK.")
        body("No security alerts can be delivered to this unconfigured build.", warning)
        if (BuildConfig.DEBUG) {
            spacer(18)
            button("Preview simulated guard flow", panel) { renderDemoList("open") }
        }
    }

    private fun renderDemoList(state: String) {
        clear("SIMULATED · NO LIVE ALERTS")
        heading("Your tasks")
        body("Preview guard · Demo site", muted)
        spacer(14)
        card {
            title("Gate 3 / Entry")
            body("HIGH · Camera gate_3", warning)
            body("${state.replace('_', ' ')} · Synthetic event")
            button("Review sample task", accent) { renderDemoTask(state) }
        }
        button("Back to setup", panel) { renderSetup() }
    }

    private fun renderDemoTask(state: String) {
        clear("SIMULATED · NO LIVE ALERTS")
        button("← Sample tasks", panel) { renderDemoList(state) }
        spacer(14)
        heading("Gate 3 / Entry")
        body("HIGH · $state", warning)
        body("Camera gate_3 · Synthetic event")
        card {
            title("What to do")
            body("Check the gate and report what you observe.", ink)
        }
        root.addView(ImageView(this).apply {
            setImageResource(R.drawable.demo_snapshot)
            adjustViewBounds = true
            scaleType = ImageView.ScaleType.FIT_CENTER
            contentDescription = "Synthetic example evidence; no real camera footage"
        }, LinearLayout.LayoutParams(-1, -2))
        spacer(14)
        if (state == "open") {
            button("Acknowledge · I am responding", accent) { renderDemoTask("acknowledged") }
        } else if (state != "resolved") {
            title("Report your outcome")
            val note = EditText(this).apply {
                hint = "What did you observe? (required)"
                setTextColor(ink)
                setHintTextColor(muted)
                setBackgroundColor(panel)
                setPadding(dp(12), dp(10), dp(12), dp(10))
            }
            root.addView(note, LinearLayout.LayoutParams(-1, -2))
            val submit: (String) -> Unit = { outcome ->
                if (note.text.toString().trim().length < 3) note.error = "Write at least three characters"
                else renderDemoTask(if (outcome == "need_help") "need_help" else "resolved")
            }
            button("Real incident", accent) { submit("real_incident") }
            button("False alarm", panel) { submit("false_alarm") }
            button("Need help now", Color.rgb(160, 61, 52)) { submit("need_help") }
        } else body("Sample task resolved. Nothing was sent to DARSON.", accent)
    }

    private fun renderLogin(error: String = "") {
        api = null
        clear("GUARD RESPONSE")
        heading("Stay ready. Respond clearly.")
        body("Sign in with your organization account to see only tasks assigned to you.")
        if (error.isNotBlank()) body(error, warning)
        spacer(20)
        button("Sign in", accent) { startLogin() }
        spacer(20)
        body("Your phone needs internet access for alerts and responses. If the connection fails, contact the security desk or use the site's radio procedure.", muted)
    }

    private fun startLogin() {
        if (busy) return
        busy = true
        renderLoading("Opening organization sign in…")
        AuthorizationServiceConfiguration.fetchFromIssuer(Uri.parse(BuildConfig.OIDC_ISSUER)) { config, error ->
            runOnUiThread {
                busy = false
                if (error != null || config == null) {
                    renderLogin("Could not reach the sign-in service."); return@runOnUiThread
                }
                val request = AuthorizationRequest.Builder(
                    config, BuildConfig.OIDC_CLIENT_ID, ResponseTypeValues.CODE,
                    Uri.parse(BuildConfig.OIDC_REDIRECT)
                ).setScope("openid profile offline_access").build()
                startActivityForResult(authService.getAuthorizationRequestIntent(request), 41)
            }
        }
    }

    @Deprecated("AppAuth returns its authorization result through the activity result intent")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 41 || data == null) return
        val response = AuthorizationResponse.fromIntent(data)
        val error = AuthorizationException.fromIntent(data)
        authState.update(response, error)
        if (response == null) { renderLogin("Sign in was cancelled or failed."); return }
        renderLoading("Finishing sign in…")
        authService.performTokenRequest(response.createTokenExchangeRequest()) { tokenResponse, tokenError ->
            runOnUiThread {
                authState.update(tokenResponse, tokenError)
                if (tokenResponse == null || tokenError != null) {
                    renderLogin("The sign-in service did not issue a usable session.")
                } else {
                    authStore.save(authState.jsonSerializeString())
                    verifyAccount()
                }
            }
        }
    }

    private fun withToken(done: (String?, Exception?) -> Unit) {
        if (!authState.isAuthorized) { done(null, ApiFailure(401, "Sign in again")); return }
        authState.performActionWithFreshTokens(authService) { accessToken, _, error ->
            runOnUiThread {
                if (error != null || accessToken == null) {
                    done(null, error ?: ApiFailure(401, "Sign in again"))
                } else {
                    authStore.save(authState.jsonSerializeString())
                    done(accessToken, null)
                }
            }
        }
    }

    private fun verifyAccount() {
        renderLoading("Checking your assignment…")
        api = try { GuardApi(::withToken) } catch (_: Exception) { renderSetup(); return }
        api?.json("GET", "/api/v1/auth/me") { me, error ->
            if (error != null || me == null) {
                if (error is ApiFailure && error.status in listOf(401, 403)) {
                    accountVerified = false; authStore.clear(); authState = AuthState(); renderLogin("Your session or site access has expired.")
                } else renderConnectionError(error)
                return@json
            }
            if (me.optString("role") != "responder") {
                accountVerified = false
                authStore.clear(); authState = AuthState()
                renderLogin("This app is for assigned guards. Use the desk screen for supervisor work.")
                return@json
            }
            actorName = me.optString("display_name", "Guard")
            siteName = me.optString("site_id", "")
            accountVerified = true
            preparePush()
            val target = pendingTaskId
            pendingTaskId = null
            if (target != null) loadDetail(target) else loadTasks()
        }
    }

    private fun preparePush() {
        if (!BuildConfig.FCM_CONFIGURED) {
            pushMessage = "Phone alerts are not configured in this APK."
            return
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            pushMessage = "Allow notifications before this phone can receive alerts."
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 42)
            return
        }
        FirebaseMessaging.getInstance().register().addOnSuccessListener {
            FirebaseInstallations.getInstance().id.addOnSuccessListener { installationId ->
                val prefs = getSharedPreferences("guard_device", MODE_PRIVATE)
                prefs.edit().putString("installation_id", installationId).apply()
                api?.json("PUT", "/api/v1/pilot/mobile-device",
                    JSONObject().put("installation_id", installationId)) { _, error ->
                    if (error == null) prefs.edit().putString("uploaded_installation_id", installationId).apply()
                    pushMessage = if (error == null) "Phone registered for assigned alerts."
                        else "Phone alerts are not registered: ${friendly(error)}"
                    if (activeTaskId == null) loadTasks()
                }
            }.addOnFailureListener { pushMessage = "Could not identify this phone for alerts." }
        }.addOnFailureListener { pushMessage = "Could not register this phone for alerts." }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 42) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) preparePush()
            else { pushMessage = "Notifications denied. Ask the desk to use another alert method."; loadTasks() }
        }
    }

    private fun loadTasks() {
        activeTaskId = null
        renderLoading("Loading assigned tasks…")
        api?.array("/api/v1/pilot/tasks") { tasks, error ->
            if (error != null || tasks == null) { renderConnectionError(error); return@array }
            renderTasks(tasks)
        }
    }

    private fun renderTasks(tasks: JSONArray) {
        clear("ON DUTY · $siteName")
        heading("Your tasks")
        body(actorName, muted)
        if (pushMessage.isNotBlank()) body(pushMessage, if (pushMessage.startsWith("Phone registered")) accent else warning)
        spacer(12)
        button("Refresh tasks", panel) { loadTasks() }
        spacer(14)
        if (tasks.length() == 0) {
            card {
                title("No active tasks")
                body("The security desk remains your fallback if the phone loses internet access.")
            }
        }
        for (index in 0 until tasks.length()) {
            val task = tasks.optJSONObject(index) ?: continue
            val id = task.optString("id")
            card {
                title(task.optString("zone_name", "Security task"))
                body("${task.optString("priority", "high").uppercase()} · Camera ${task.optString("camera_id", "—")}", warning)
                body("${task.optString("state", "open").replace('_', ' ')} · ${time(task.optDouble("created_at"))}")
                button("Review task", accent) { loadDetail(id) }
            }
        }
        spacer(14)
        button("Sign out and unregister phone", panel) { unregisterAndLogout() }
    }

    private fun loadDetail(id: String) {
        activeTaskId = id
        renderLoading("Loading task…")
        api?.json("GET", "/api/v1/pilot/tasks/${Uri.encode(id)}") { task, error ->
            if (error != null || task == null) {
                if (error is ApiFailure && error.status == 404) {
                    activeTaskId = null; loadTasks()
                } else renderConnectionError(error)
                return@json
            }
            renderDetail(task)
        }
    }

    private fun renderDetail(task: JSONObject) {
        clear("ASSIGNED INCIDENT")
        button("← All tasks", panel) { loadTasks() }
        spacer(14)
        heading(task.optString("zone_name", "Security task"))
        body("${task.optString("priority", "high").uppercase()} · ${task.optString("state").replace('_', ' ')}", warning)
        body("Camera ${task.optString("camera_id", "—")} · ${time(task.optDouble("observed_at"))}")
        spacer(12)
        card {
            title("What to do")
            body(task.optString("instruction", "Follow the site response procedure."), ink)
        }
        val evidence = task.optJSONArray("evidence") ?: JSONArray()
        val snapshot = (0 until evidence.length()).mapNotNull { evidence.optJSONObject(it) }
            .firstOrNull { it.optString("kind") == "snapshot" && it.optString("content_url").startsWith("/api/v1/evidence/") }
        val clip = (0 until evidence.length()).mapNotNull { evidence.optJSONObject(it) }
            .firstOrNull { it.optString("kind") == "clip" && it.optString("content_url").startsWith("/api/v1/evidence/") }
        if (snapshot != null) showSnapshot(snapshot.optString("content_url"))
        else body("Snapshot not available yet. You can still acknowledge this task.", muted)
        if (clip != null) button("Play short clip", panel) { playClip(clip.optString("content_url")) }
        spacer(14)
        val id = task.getString("id")
        val version = task.getInt("version")
        if (task.optString("state") == "open") {
            button("Acknowledge · I am responding", accent) { act(id, version, "acknowledge") }
        } else if (task.optString("state") != "resolved") {
            title("Report your outcome")
            val note = EditText(this).apply {
                hint = "What did you observe? (required)"
                setTextColor(ink)
                setHintTextColor(muted)
                setBackgroundColor(panel)
                setPadding(dp(12), dp(10), dp(12), dp(10))
                minLines = 2
            }
            root.addView(note, LinearLayout.LayoutParams(-1, -2))
            spacer(10)
            button("Real incident", accent) { outcome(id, version, "real_incident", note) }
            button("False alarm", panel) { outcome(id, version, "false_alarm", note) }
            button("Need help now", Color.rgb(160, 61, 52)) { outcome(id, version, "need_help", note) }
        } else body("This task is resolved.", accent)
    }

    private fun showSnapshot(path: String) {
        val image = ImageView(this).apply {
            adjustViewBounds = true
            scaleType = ImageView.ScaleType.FIT_CENTER
            setBackgroundColor(panel)
            minimumHeight = dp(160)
        }
        root.addView(image, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) })
        api?.bytes(path) { bytes, error ->
            if (bytes != null && error == null && bytes.isNotEmpty()) {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                val options = BitmapFactory.Options().apply {
                    inSampleSize = (maxOf(bounds.outWidth, bounds.outHeight) / 1400).coerceAtLeast(1)
                }
                image.setImageBitmap(BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options))
            } else body("Snapshot could not be loaded.", warning)
        }
    }

    private fun playClip(path: String) {
        withToken { token, error ->
            if (error != null || token == null) { body("Sign in again to play this clip.", warning); return@withToken }
            val video = VideoView(this).apply {
                setBackgroundColor(panel)
                setVideoURI(Uri.parse(BuildConfig.API_BASE.trimEnd('/') + path),
                    mapOf("Authorization" to "Bearer $token"))
                setOnPreparedListener { start() }
                setOnErrorListener { _, _, _ -> body("Clip playback failed. Review it at the desk.", warning); true }
            }
            root.addView(video, LinearLayout.LayoutParams(-1, dp(230)))
        }
    }

    private fun outcome(id: String, version: Int, value: String, note: EditText) {
        val observation = note.text.toString().trim()
        if (observation.length < 3) { note.error = "Write at least three characters"; return }
        act(id, version, "outcome", value, observation)
    }

    private fun act(id: String, version: Int, action: String, outcome: String? = null, note: String = "") {
        if (busy) return
        busy = true
        val body = JSONObject().put("action", action).put("expected_version", version)
            .put("note", note)
        if (outcome != null) body.put("outcome", outcome)
        api?.json("POST", "/api/v1/pilot/tasks/${Uri.encode(id)}/actions", body) { _, error ->
            busy = false
            if (error != null) {
                if (error is ApiFailure && error.status == 409) loadDetail(id)
                else { renderConnectionError(error) }
            } else if (outcome == "real_incident" || outcome == "false_alarm") loadTasks()
            else loadDetail(id)
        }
    }

    private fun unregisterAndLogout() {
        val installationId = getSharedPreferences("guard_device", MODE_PRIVATE)
            .getString("uploaded_installation_id", null)
        if (installationId == null || !BuildConfig.FCM_CONFIGURED) { finishLogout(); return }
        renderLoading("Removing this phone from alerts…")
        api?.json("DELETE", "/api/v1/pilot/mobile-device", JSONObject().put("installation_id", installationId)) { _, error ->
            if (error != null) {
                renderTasks(JSONArray())
                body("Could not unregister this phone. Retry when connected or ask a supervisor to remove it.", warning)
            } else finishLogout()
        }
    }

    private fun finishLogout() {
        accountVerified = false
        authStore.clear()
        authState = AuthState()
        api = null
        activeTaskId = null
        getSharedPreferences("guard_device", MODE_PRIVATE).edit().clear().apply()
        renderLogin("Signed out. This phone will no longer receive assigned alerts.")
    }

    private fun renderConnectionError(error: Exception?) {
        clear("CONNECTION PROBLEM")
        heading("Cannot confirm the task")
        body(friendly(error), warning)
        body("Do not assume a response was saved. Contact the desk or use the site radio procedure.")
        button("Retry", accent) { if (activeTaskId != null) loadDetail(activeTaskId!!) else verifyAccount() }
    }

    private fun friendly(error: Exception?) = when (error) {
        is ApiFailure -> error.message ?: "Server rejected the request"
        else -> "No secure connection to the DARSON server."
    }

    private fun renderLoading(message: String) { clear("DARSON GUARD"); body(message) }
    private fun clear(kicker: String) {
        root.removeAllViews()
        body(kicker, accent, 12f, Typeface.BOLD)
        spacer(12)
    }
    private fun card(content: MainActivity.() -> Unit) {
        val outer = root
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(14))
            setBackgroundColor(panel)
        }
        outer.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(12) })
        root = card
        content()
        root = outer
    }
    private fun heading(value: String) = body(value, ink, 28f, Typeface.BOLD)
    private fun title(value: String) = body(value, ink, 20f, Typeface.BOLD)
    private fun body(value: String, color: Int = muted, size: Float = 15f, weight: Int = Typeface.NORMAL) {
        root.addView(TextView(this).apply {
            text = value
            setTextColor(color)
            textSize = size
            setTypeface(typeface, weight)
            setPadding(0, dp(3), 0, dp(3))
        })
    }
    private fun button(label: String, color: Int, click: () -> Unit) {
        root.addView(Button(this).apply {
            text = label
            isAllCaps = false
            textSize = 16f
            setTextColor(if (color == accent) this@MainActivity.background else ink)
            backgroundTintList = android.content.res.ColorStateList.valueOf(color)
            minHeight = dp(54)
            setOnClickListener { click() }
        }, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(7) })
    }
    private fun spacer(height: Int) { root.addView(View(this), LinearLayout.LayoutParams(1, dp(height))) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun time(seconds: Double): String = if (seconds <= 0) "Time unknown"
        else DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date((seconds * 1000).toLong()))

    override fun onDestroy() { super.onDestroy(); authService.dispose() }
}
