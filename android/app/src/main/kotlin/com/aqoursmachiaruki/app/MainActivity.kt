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
            // Runs only once the launch intent has actually gone out, so rotating
            // (and finishing) here can't race the disabled-alias task-teardown issue.
            rotateIcon()
            finish()
        }
    }

    override fun onDestroy() {
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
