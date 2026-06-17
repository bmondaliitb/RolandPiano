package com.rolandpiano.trainer.midi

import com.rolandpiano.trainer.model.NoteEvent
import com.rolandpiano.trainer.model.PlaybackEvent
import com.rolandpiano.trainer.model.Song
import java.io.InputStream
import kotlin.math.max

class MidiFormatException(message: String) : IllegalArgumentException(message)

object MidiFileParser {
    private data class RawEvent(
        val tick: Long,
        val order: Int,
        val status: Int,
        val data1: Int,
        val data2: Int,
        val tempo: Int? = null,
    )

    fun parse(input: InputStream, uri: String, name: String): Song {
        val reader = Reader(input.readBytes())
        reader.expect("MThd")
        val headerLength = reader.int32()
        val format = reader.int16()
        val tracks = reader.int16()
        val division = reader.int16()
        if (format !in 0..1) throw MidiFormatException("MIDI format $format is not supported")
        if (division and 0x8000 != 0) throw MidiFormatException("SMPTE time division is not supported")
        if (headerLength > 6) reader.skip(headerLength - 6)

        val events = mutableListOf<RawEvent>()
        repeat(tracks) { trackIndex ->
            reader.expect("MTrk")
            val end = reader.position + reader.int32()
            var tick = 0L
            var runningStatus = 0
            var order = trackIndex shl 20
            while (reader.position < end) {
                tick += reader.variableLength()
                var status = reader.byte()
                if (status < 0x80) {
                    if (runningStatus == 0) throw MidiFormatException("Invalid running status")
                    reader.rewind()
                    status = runningStatus
                } else if (status < 0xf0) {
                    runningStatus = status
                }
                when {
                    status == 0xff -> {
                        val type = reader.byte()
                        val length = reader.variableLength().toInt()
                        if (type == 0x51 && length == 3) {
                            val tempo = (reader.byte() shl 16) or (reader.byte() shl 8) or reader.byte()
                            events += RawEvent(tick, order++, status, 0, 0, tempo)
                        } else {
                            reader.skip(length)
                        }
                    }
                    status == 0xf0 || status == 0xf7 -> reader.skip(reader.variableLength().toInt())
                    status and 0xf0 in setOf(0xc0, 0xd0) -> {
                        val data1 = reader.byte()
                        events += RawEvent(tick, order++, status, data1, 0)
                    }
                    status in 0x80..0xef -> {
                        val data1 = reader.byte()
                        val data2 = reader.byte()
                        events += RawEvent(tick, order++, status, data1, data2)
                    }
                    else -> throw MidiFormatException("Unsupported MIDI status 0x${status.toString(16)}")
                }
            }
            reader.position = end
        }

        val sorted = events.sortedWith(compareBy(RawEvent::tick, RawEvent::order))
        var currentTick = 0L
        var currentSeconds = 0.0
        var tempo = 500_000
        val timed = mutableListOf<Pair<Double, RawEvent>>()
        for (event in sorted) {
            currentSeconds += (event.tick - currentTick) * tempo / 1_000_000.0 / division
            currentTick = event.tick
            timed += currentSeconds to event
            event.tempo?.let { tempo = it }
        }

        val active = mutableMapOf<Pair<Int, Int>, ArrayDeque<Pair<Double, Int>>>()
        val notes = mutableListOf<NoteEvent>()
        val playback = mutableListOf<PlaybackEvent>()
        for ((seconds, event) in timed) {
            if (event.tempo != null) continue
            val kind = event.status and 0xf0
            val channel = event.status and 0x0f
            if (channel == 9) continue
            if (kind == 0x90 && event.data2 > 0) {
                active.getOrPut(channel to event.data1) { ArrayDeque() }.add(seconds to event.data2)
                playback += PlaybackEvent(seconds, byteArrayOf(event.status.toByte(), event.data1.toByte(), event.data2.toByte()))
            } else if (kind == 0x80 || kind == 0x90) {
                active[channel to event.data1]?.removeFirstOrNull()?.let { (start, velocity) ->
                    notes += NoteEvent(event.data1, start, max(start, seconds), velocity, channel)
                }
                playback += PlaybackEvent(seconds, byteArrayOf((0x80 or channel).toByte(), event.data1.toByte(), 0))
            } else if (kind == 0xb0 && event.data1 in setOf(64, 66, 67)) {
                playback += PlaybackEvent(seconds, byteArrayOf(event.status.toByte(), event.data1.toByte(), event.data2.toByte()))
            }
        }
        val end = timed.lastOrNull()?.first ?: 0.0
        active.forEach { (key, starts) ->
            starts.forEach { (start, velocity) ->
                notes += NoteEvent(key.second, start, end, velocity, key.first)
            }
        }
        val orderedNotes = notes.sortedWith(compareBy(NoteEvent::startSeconds, NoteEvent::note))
        return Song(uri, name, orderedNotes, playback.sortedBy(PlaybackEvent::timeSeconds), max(end, orderedNotes.maxOfOrNull { it.endSeconds } ?: 0.0))
    }

    private class Reader(private val data: ByteArray) {
        var position = 0

        fun byte(): Int {
            if (position >= data.size) throw MidiFormatException("Unexpected end of MIDI file")
            return data[position++].toInt() and 0xff
        }

        fun rewind() { position-- }
        fun skip(count: Int) {
            position += count
            if (position > data.size) throw MidiFormatException("Invalid MIDI chunk length")
        }

        fun int16() = (byte() shl 8) or byte()
        fun int32() = (byte() shl 24) or (byte() shl 16) or (byte() shl 8) or byte()

        fun variableLength(): Long {
            var value = 0L
            repeat(4) {
                val next = byte()
                value = (value shl 7) or (next and 0x7f).toLong()
                if (next and 0x80 == 0) return value
            }
            throw MidiFormatException("Invalid variable-length MIDI value")
        }

        fun expect(value: String) {
            val actual = ByteArray(4) { byte().toByte() }.decodeToString()
            if (actual != value) throw MidiFormatException("Expected $value, found $actual")
        }
    }
}
