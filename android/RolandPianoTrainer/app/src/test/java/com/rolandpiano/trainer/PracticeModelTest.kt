package com.rolandpiano.trainer

import com.rolandpiano.trainer.model.NoteEvent
import com.rolandpiano.trainer.model.buildPracticeSteps
import com.rolandpiano.trainer.model.noteName
import com.rolandpiano.trainer.model.suggestFingering
import org.junit.Assert.assertEquals
import org.junit.Test

class PracticeModelTest {
    @Test
    fun groupsNotesWithinChordTolerance() {
        val notes = listOf(
            NoteEvent(60, 0.0, 1.0, 90, 0),
            NoteEvent(64, 0.02, 1.0, 90, 0),
            NoteEvent(67, 0.03, 1.0, 90, 0),
            NoteEvent(69, 0.20, 1.0, 90, 0),
        )
        val steps = buildPracticeSteps(notes)
        assertEquals(setOf(60, 64, 67), steps[0].notes)
        assertEquals(setOf(69), steps[1].notes)
    }

    @Test
    fun suggestsCommonTriadFingers() {
        val step = buildPracticeSteps(
            listOf(
                NoteEvent(60, 0.0, 1.0, 90, 0),
                NoteEvent(64, 0.0, 1.0, 90, 0),
                NoteEvent(67, 0.0, 1.0, 90, 0),
            ),
        ).single()
        assertEquals(listOf("R1", "R3", "R5"), suggestFingering(step).map { it.label })
        assertEquals("C4", noteName(60))
    }
}
