package com.rolandpiano.trainer.audio

import android.content.Context
import android.media.MediaRecorder
import java.io.File

class PianoRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    var outputFile: File? = null
        private set

    fun start(): File {
        stop()
        val file = File(context.getExternalFilesDir("recordings"), "piano-${System.currentTimeMillis()}.m4a")
        file.parentFile?.mkdirs()
        @Suppress("DEPRECATION")
        val mediaRecorder = if (android.os.Build.VERSION.SDK_INT >= 31) MediaRecorder(context) else MediaRecorder()
        val source = if (android.os.Build.VERSION.SDK_INT >= 24) {
            MediaRecorder.AudioSource.UNPROCESSED
        } else {
            MediaRecorder.AudioSource.MIC
        }
        mediaRecorder.setAudioSource(source)
        mediaRecorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        mediaRecorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        mediaRecorder.setAudioEncodingBitRate(192_000)
        mediaRecorder.setAudioSamplingRate(48_000)
        mediaRecorder.setOutputFile(file.absolutePath)
        mediaRecorder.prepare()
        mediaRecorder.start()
        recorder = mediaRecorder
        outputFile = file
        return file
    }

    fun stop(): File? {
        val current = recorder ?: return outputFile
        runCatching { current.stop() }
        current.release()
        recorder = null
        return outputFile
    }
}
