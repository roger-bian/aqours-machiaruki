import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val keystoreProperties = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "com.aqoursmachiaruki.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.aqoursmachiaruki.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    // Signed with a dedicated keystore (not the auto-generated debug one) so the
    // app's signing fingerprint stays stable across machines/reinstalls — Trusted
    // Web Activity's fullscreen mode depends on this fingerprint matching what's
    // published in the site's assetlinks.json.
    if (keystoreProperties.getProperty("storeFile") != null) {
        signingConfigs {
            create("release") {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
        buildTypes {
            release {
                isMinifyEnabled = false
                signingConfig = signingConfigs.getByName("release")
            }
            debug {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    } else {
        buildTypes {
            release {
                isMinifyEnabled = false
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.browser:browser:1.8.0")
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.5.0")
}
