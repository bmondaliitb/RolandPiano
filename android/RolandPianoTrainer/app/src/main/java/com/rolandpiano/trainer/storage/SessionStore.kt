package com.rolandpiano.trainer.storage

import android.content.Context
import org.json.JSONObject

data class SavedSession(
    val songUri: String? = null,
    val position: Double = 0.0,
    val tempo: Float = 1f,
    val dynamics: Int = 85,
    val pianoVolume: Int = 50,
    val waitForKeys: Boolean = false,
    val showFingers: Boolean = false,
    val sendToPiano: Boolean = false,
    val playOnPhone: Boolean = false,
    val viewMode: String = "roll",
    val loopStart: Double = 0.0,
    val loopEnd: Double? = null,
    val loopEnabled: Boolean = false,
) {
    fun toJson(project: Boolean = false): JSONObject = JSONObject().apply {
        if (project) {
            put("type", "roland-piano-project")
            put("version", 1)
        }
        put("songUri", songUri)
        put("position", position)
        put("tempo", tempo)
        put("dynamics", dynamics)
        put("pianoVolume", pianoVolume)
        put("waitForKeys", waitForKeys)
        put("showFingers", showFingers)
        put("sendToPiano", sendToPiano)
        put("playOnPhone", playOnPhone)
        put("viewMode", viewMode)
        put("loopStart", loopStart)
        put("loopEnd", loopEnd)
        put("loopEnabled", loopEnabled)
    }

    companion object {
        fun fromJson(json: JSONObject, requireProject: Boolean = false): SavedSession? {
            if (requireProject && (json.optString("type") != "roland-piano-project" || json.optInt("version") != 1)) return null
            return SavedSession(
                songUri = json.optString("songUri").takeIf { it.isNotBlank() && it != "null" },
                position = json.optDouble("position", 0.0),
                tempo = json.optDouble("tempo", 1.0).toFloat().coerceIn(0.4f, 1.5f),
                dynamics = json.optInt("dynamics", 85).coerceIn(50, 110),
                pianoVolume = json.optInt("pianoVolume", 50).coerceIn(0, 100),
                waitForKeys = json.optBoolean("waitForKeys"),
                showFingers = json.optBoolean("showFingers"),
                sendToPiano = json.optBoolean("sendToPiano"),
                playOnPhone = json.optBoolean("playOnPhone"),
                viewMode = json.optString("viewMode", "roll").takeIf { it in setOf("roll", "sheet") } ?: "roll",
                loopStart = json.optDouble("loopStart", 0.0),
                loopEnd = if (json.isNull("loopEnd")) null else json.optDouble("loopEnd"),
                loopEnabled = json.optBoolean("loopEnabled"),
            )
        }
    }
}

class SessionStore(context: Context) {
    private val preferences = context.getSharedPreferences("trainer-state", Context.MODE_PRIVATE)

    fun load(): SavedSession? = runCatching {
        preferences.getString("session", null)?.let { SavedSession.fromJson(JSONObject(it)) }
    }.getOrNull()

    fun save(session: SavedSession) {
        preferences.edit().putString("session", session.toJson().toString()).apply()
    }
}
