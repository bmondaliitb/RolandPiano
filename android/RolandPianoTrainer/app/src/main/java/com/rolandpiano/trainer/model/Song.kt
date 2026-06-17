package com.rolandpiano.trainer.model

data class NoteEvent(
    val note: Int,
    val startSeconds: Double,
    val endSeconds: Double,
    val velocity: Int,
    val channel: Int,
)

data class PlaybackEvent(
    val timeSeconds: Double,
    val bytes: ByteArray,
)

data class PracticeStep(
    val startSeconds: Double,
    val notes: Set<Int>,
)

data class FingerSuggestion(
    val note: Int,
    val hand: Char,
    val finger: Int,
) {
    val label: String get() = "$hand$finger"
}

data class Song(
    val uri: String,
    val name: String,
    val notes: List<NoteEvent>,
    val playbackEvents: List<PlaybackEvent>,
    val durationSeconds: Double,
) {
    val practiceSteps: List<PracticeStep> = buildPracticeSteps(notes)
}

fun noteName(note: Int): String {
    val names = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return "${names[note.mod(12)]}${note / 12 - 1}"
}

fun buildPracticeSteps(notes: List<NoteEvent>, toleranceSeconds: Double = 0.04): List<PracticeStep> {
    if (notes.isEmpty()) return emptyList()
    val result = mutableListOf<PracticeStep>()
    var start = notes.first().startSeconds
    var group = sortedSetOf<Int>()
    for (event in notes.sortedWith(compareBy(NoteEvent::startSeconds, NoteEvent::note))) {
        if (event.startSeconds - start > toleranceSeconds) {
            result += PracticeStep(start, group.toSet())
            start = event.startSeconds
            group = sortedSetOf()
        }
        group += event.note
    }
    result += PracticeStep(start, group.toSet())
    return result
}

fun suggestFingering(step: PracticeStep): List<FingerSuggestion> {
    val ordered = step.notes.sorted()
    val left = ordered.filter { it < 60 }
    val right = ordered.filter { it >= 60 }
    return fingerHand(left, 'L') + fingerHand(right, 'R')
}

private fun fingerHand(notes: List<Int>, hand: Char): List<FingerSuggestion> {
    if (notes.isEmpty()) return emptyList()
    if (notes.size == 1) {
        val right = intArrayOf(1, 2, 2, 3, 3, 1, 2, 2, 3, 3, 4, 4)
        val left = intArrayOf(1, 2, 2, 3, 3, 4, 4, 5, 4, 3, 2, 2)
        return listOf(FingerSuggestion(notes[0], hand, (if (hand == 'R') right else left)[notes[0].mod(12)]))
    }
    val pattern = when (notes.size) {
        2 -> listOf(1, 5)
        3 -> listOf(1, 3, 5)
        4 -> listOf(1, 2, 3, 5)
        else -> (1..notes.size).map { it.coerceAtMost(5) }
    }
    val fingers = if (hand == 'L') pattern.reversed() else pattern
    return notes.zip(fingers).map { (note, finger) -> FingerSuggestion(note, hand, finger) }
}
