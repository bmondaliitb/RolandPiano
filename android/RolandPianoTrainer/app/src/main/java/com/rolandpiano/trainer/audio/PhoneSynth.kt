package com.rolandpiano.trainer.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import java.io.Closeable
import java.util.concurrent.ConcurrentHashMap
import kotlin.concurrent.thread
import kotlin.math.PI
import kotlin.math.pow
import kotlin.math.sin

class PhoneSynth : Closeable {
    private val sampleRate = 44_100
    private val voices = ConcurrentHashMap<Int, Voice>()
    @Volatile private var running = true
    @Volatile var volume = 0.7f

    private val audioTrack = AudioTrack.Builder()
        .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
        .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_FLOAT).setSampleRate(sampleRate).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
        .setBufferSizeInBytes(sampleRate)
        .setTransferMode(AudioTrack.MODE_STREAM)
        .build()

    private val renderThread = thread(name = "piano-phone-synth", isDaemon = true) {
        val buffer = FloatArray(512)
        audioTrack.play()
        while (running) {
            for (i in buffer.indices) {
                var sample = 0.0
                val iterator = voices.entries.iterator()
                while (iterator.hasNext()) {
                    val (note, voice) = iterator.next()
                    val age = voice.samples++.toDouble() / sampleRate
                    val envelope = if (voice.released) {
                        voice.releaseLevel * (1.0 - (age - voice.releaseTime) / 0.35).coerceIn(0.0, 1.0)
                    } else {
                        (1.0 - age / 9.0).coerceAtLeast(0.08)
                    }
                    if (voice.released && age - voice.releaseTime > 0.35) {
                        voices.remove(note, voice)
                        continue
                    }
                    val phase = 2.0 * PI * voice.frequency * age
                    sample += envelope * voice.velocity * (
                        sin(phase) + 0.42 * sin(phase * 2.01) + 0.16 * sin(phase * 3.98)
                    )
                }
                buffer[i] = (sample * 0.18 * volume).coerceIn(-1.0, 1.0).toFloat()
            }
            audioTrack.write(buffer, 0, buffer.size, AudioTrack.WRITE_BLOCKING)
        }
    }

    fun noteOn(note: Int, velocity: Int) {
        voices[note] = Voice(
            frequency = 440.0 * 2.0.pow((note - 69) / 12.0),
            velocity = velocity.coerceIn(1, 127) / 127.0,
        )
    }

    fun noteOff(note: Int) {
        voices[note]?.let {
            it.released = true
            it.releaseTime = it.samples.toDouble() / sampleRate
            it.releaseLevel = (1.0 - it.releaseTime / 9.0).coerceAtLeast(0.08)
        }
    }

    fun allNotesOff() = voices.clear()

    override fun close() {
        running = false
        renderThread.join(500)
        audioTrack.stop()
        audioTrack.release()
    }

    private data class Voice(
        val frequency: Double,
        val velocity: Double,
        var samples: Long = 0,
        var released: Boolean = false,
        var releaseTime: Double = 0.0,
        var releaseLevel: Double = 1.0,
    )
}
