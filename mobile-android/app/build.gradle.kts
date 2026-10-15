import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val firebaseConfig = file("google-services.json").isFile
if (firebaseConfig) apply(plugin = "com.google.gms.google-services")

// OneDrive can lock generated resource files while Gradle replaces them.
// Set this to a temporary local folder when building from a synced checkout.
System.getenv("DARSON_ANDROID_BUILD_DIR")?.takeIf { it.isNotBlank() }?.let {
    layout.buildDirectory.set(file(it))
}

val guardProperties = Properties().apply {
    val config = rootProject.file("guard.properties")
    if (config.isFile) config.inputStream().use { load(it) }
}
fun propertyString(name: String): String =
    providers.gradleProperty(name).orElse(guardProperties.getProperty(name, "")).get()
        .replace("\\", "\\\\").replace("\"", "\\\"")

android {
    namespace = "com.darson.guard"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.darson.guard"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        manifestPlaceholders["appAuthRedirectScheme"] = "com.darson.guard"
        buildConfigField("String", "API_BASE", "\"${propertyString("DARSON_API_BASE")}\"")
        buildConfigField("String", "OIDC_ISSUER", "\"${propertyString("DARSON_OIDC_ISSUER")}\"")
        buildConfigField("String", "OIDC_CLIENT_ID", "\"${propertyString("DARSON_OIDC_CLIENT_ID")}\"")
        buildConfigField("String", "OIDC_REDIRECT", "\"com.darson.guard:/oauth2redirect\"")
        buildConfigField("boolean", "FCM_CONFIGURED", firebaseConfig.toString())
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging { resources.excludes += "META-INF/*" }
}

dependencies {
    implementation("androidx.core:core:1.17.0")
    implementation("net.openid:appauth:0.11.1")
    implementation(platform("com.google.firebase:firebase-bom:34.19.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("com.google.firebase:firebase-installations")
}
