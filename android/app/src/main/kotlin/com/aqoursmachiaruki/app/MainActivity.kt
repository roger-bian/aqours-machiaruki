package com.aqoursmachiaruki.app

import android.app.Activity
import android.content.ComponentName
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import androidx.browser.customtabs.CustomTabsCallback
import androidx.browser.trusted.TrustedWebActivityIntentBuilder
import com.google.androidbrowserhelper.trusted.TwaLauncher
import kotlin.random.Random

private const val TARGET_URL = "https://aqours-machiaruki-web.onrender.com/"

private val ICON_ALIASES = listOf(
    "Chika", "You", "Riko", "Kanan", "Daiya", "Yoshiko", "Hanamaru", "Mari", "Ruby",
)

class MainActivity : Activity() {
    private lateinit var twaLauncher: TwaLauncher
    private var browserWasLaunched = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        twaLauncher = TwaLauncher(this)
        // Falls back to a plain Custom Tab automatically if the domain isn't (yet)
        // verified via assetlinks.json, or no TWA-capable browser is available.
        twaLauncher.launch(
            TrustedWebActivityIntentBuilder(Uri.parse(TARGET_URL)),
            CustomTabsCallback(),
            null,
        ) {
            browserWasLaunched = true
        }
    }

    // The TWA is pushed onto this same task, on top of this activity, so we must NOT
    // finish() right after launching (that races with the browser activity still
    // attaching to the task and either aborts the launch or crashes on cleanup).
    // Instead, stay alive underneath and only finish once the user backs out of the
    // browser and control actually returns here — mirroring Google's own reference
    // TWA LauncherActivity, which uses this exact onRestart pattern.
    override fun onRestart() {
        super.onRestart()
        if (browserWasLaunched) {
            finish()
        }
    }

    // Disabling the alias that launched the CURRENT task closes that entire task
    // (both this activity and the TWA/Custom Tab riding on top of it) immediately,
    // regardless of DONT_KILL_APP — confirmed via logcat: right after disabling the
    // origin alias, WindowManager issues a CLOSE transition for the whole task,
    // killing Chrome's page-render process before the site ever displays. So the
    // rotation must only happen once the task is already being torn down for real.
    override fun onDestroy() {
        rotateIcon()
        twaLauncher.destroy()
        super.onDestroy()
    }

    private fun rotateIcon() {
        val components = ICON_ALIASES.map { ComponentName(this, "$packageName.Icon$it") }
        val currentIndex = components.indexOfFirst {
            packageManager.getComponentEnabledSetting(it) != PackageManager.COMPONENT_ENABLED_STATE_DISABLED
        }
        val nextIndex = if (components.size <= 1) {
            0
        } else {
            var candidate = Random.nextInt(components.size)
            while (candidate == currentIndex) candidate = Random.nextInt(components.size)
            candidate
        }
        if (nextIndex == currentIndex) return

        packageManager.setComponentEnabledSetting(
            components[nextIndex],
            PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
            PackageManager.DONT_KILL_APP,
        )
        if (currentIndex >= 0) {
            packageManager.setComponentEnabledSetting(
                components[currentIndex],
                PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                PackageManager.DONT_KILL_APP,
            )
        }
    }
}
