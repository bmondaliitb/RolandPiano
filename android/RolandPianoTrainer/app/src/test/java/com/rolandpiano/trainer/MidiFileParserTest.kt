package com.rolandpiano.trainer

import com.rolandpiano.trainer.midi.MidiFileParser
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.ByteArrayInputStream

class MidiFileParserTest {
    @Test
    fun parsesSingleNoteAndTempo() {
        val bytes = byteArrayOf(
            0x4d, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 0, 0, 1, 0x01, 0xE0.toByte(),
            0x4d, 0x54, 0x72, 0x6b, 0, 0, 0, 20,
            0, 0xff.toByte(), 0x51, 3, 0x07, 0xA1.toByte(), 0x20,
            0, 0x90.toByte(), 60, 100,
            0x83.toByte(), 0x60, 0x80.toByte(), 60, 0,
            0, 0xff.toByte(), 0x2f, 0,
        )
        val song = MidiFileParser.parse(ByteArrayInputStream(bytes), "test", "test.mid")
        assertEquals(1, song.notes.size)
        assertEquals(60, song.notes.single().note)
        assertEquals(0.5, song.notes.single().endSeconds, 0.0001)
    }
}
