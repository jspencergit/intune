package com.analogintuition.intune

/**
 * How aggressively the UI hides bow-attack / transition mess.
 *
 * Detector still runs at full rate; this only changes display + in-tune coloring.
 *
 * - [Steady] — practice default: blank attack window, stronger smoothing; judge the note body
 * - [Live] — show pitch promptly, including attack wiggles (still light display smoothing)
 */
enum class ResponseMode {
    Steady,
    Live,
    ;

    val label: String
        get() = when (this) {
            Steady -> "Steady"
            Live -> "Live"
        }

    companion object {
        fun fromStorage(name: String?): ResponseMode =
            entries.firstOrNull { it.name.equals(name, ignoreCase = true) } ?: Steady
    }
}
