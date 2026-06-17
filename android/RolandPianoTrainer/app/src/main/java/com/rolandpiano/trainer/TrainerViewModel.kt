package com.rolandpiano.trainer

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.rolandpiano.trainer.audio.PhoneSynth
import com.rolandpiano.trainer.audio.PianoRecorder
import com.rolandpiano.trainer.midi.BluetoothMidiController
import com.rolandpiano.trainer.midi.BluetoothMidiDevice
import com.rolandpiano.trainer.midi.MidiFileParser
import com.rolandpiano.trainer.model.PracticeStep
import com.rolandpiano.trainer.model.Song
import com.rolandpiano.trainer.storage.SavedSession
import com.rolandpiano.trainer.storage.SessionStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import kotlin.math.abs

data class TrainerUiState(
    val song: Song? = null,
    val loading: Boolean = false,
    val playing: Boolean = false,
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
    val pressedNotes: Set<Int> = emptySet(),
    val practiceIndex: Int = 0,
    val bluetoothDevices: List<BluetoothMidiDevice> = emptyList(),
    val connectedDevice: String? = null,
    val scanning: Boolean = false,
    val recording: Boolean = false,
    val recordingPath: String? = null,
    val message: String? = null,
) {
    val targetStep: PracticeStep?
        get() = song?.practiceSteps?.getOrNull(practiceIndex)
}

class TrainerViewModel(application: Application) : AndroidViewModel(application) {
    private val store = SessionStore(application)
    private val bluetooth = BluetoothMidiController(application)
    private var synth: PhoneSynth? = null
    private val recorder = PianoRecorder(application)
    private val _state = MutableStateFlow(TrainerUiState())
    val state: StateFlow<TrainerUiState> = _state.asStateFlow()
    private var ticker: Job? = null
    private var eventIndex = 0
    private var lastNanos = 0L
    private var restoredSession: SavedSession? = store.load()

    init {
        restoredSession?.let { applySession(it, loadSong = true) }
        bluetooth.onDevicesChanged = { devices -> _state.value = _state.value.copy(bluetoothDevices = devices) }
        bluetooth.onConnectionChanged = { name ->
            _state.value = _state.value.copy(connectedDevice = name, scanning = false)
        }
        bluetooth.onNote = { note, pressed, velocity ->
            val current = _state.value.pressedNotes.toMutableSet()
            if (pressed) current += note else current -= note
            _state.value = _state.value.copy(pressedNotes = current)
            if (_state.value.playOnPhone) {
                if (pressed) phoneSynth().noteOn(note, velocity) else synth?.noteOff(note)
            }
            completePracticeStepIfMatched()
        }
    }

    fun loadSong(uri: Uri, restoredPosition: Double? = null) {
        _state.value = _state.value.copy(loading = true, playing = false, message = null)
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val resolver = getApplication<Application>().contentResolver
                    val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                        if (it.moveToFirst()) it.getString(0) else "song.mid"
                    } ?: "song.mid"
                    resolver.openInputStream(uri)!!.use { MidiFileParser.parse(it, uri.toString(), name) }
                }
            }.onSuccess { song ->
                val position = (restoredPosition ?: 0.0).coerceIn(0.0, song.durationSeconds)
                _state.value = _state.value.copy(song = song, loading = false, position = position)
                seek(position)
            }.onFailure {
                _state.value = _state.value.copy(loading = false, message = it.message ?: "Could not open MIDI file")
            }
        }
    }

    fun togglePlayback() {
        if (_state.value.song == null) return
        if (_state.value.playing) pause() else play()
    }

    fun play() {
        if (_state.value.song == null || _state.value.playing) return
        lastNanos = System.nanoTime()
        _state.value = _state.value.copy(playing = true)
        ticker = viewModelScope.launch {
            while (isActive && _state.value.playing) {
                tick()
                delay(33)
            }
        }
    }

    fun pause() {
        _state.value = _state.value.copy(playing = false)
        ticker?.cancel()
        allNotesOff()
        saveState()
    }

    fun restart() = seek(if (loopActive()) _state.value.loopStart else 0.0)

    fun seek(position: Double) {
        val song = _state.value.song ?: return
        val target = position.coerceIn(0.0, song.durationSeconds)
        allNotesOff()
        eventIndex = song.playbackEvents.indexOfFirst { it.timeSeconds >= target }.let { if (it < 0) song.playbackEvents.size else it }
        val practice = song.practiceSteps.indexOfFirst { it.startSeconds >= target - 0.04 }
            .let { if (it < 0) song.practiceSteps.lastIndex.coerceAtLeast(0) else it }
        _state.value = _state.value.copy(position = target, practiceIndex = practice)
        lastNanos = System.nanoTime()
    }

    private fun tick() {
        val current = _state.value
        val song = current.song ?: return
        val nowNanos = System.nanoTime()
        val delta = (nowNanos - lastNanos) / 1_000_000_000.0 * current.tempo
        lastNanos = nowNanos
        var position = current.position + delta

        if (current.waitForKeys) {
            val step = current.targetStep
            if (step != null && position >= step.startSeconds) position = step.startSeconds
        }
        if (loopActive() && position >= current.loopEnd!!) {
            seek(current.loopStart)
            return
        }
        if (position >= song.durationSeconds) {
            pause()
            _state.value = _state.value.copy(position = song.durationSeconds)
            return
        }
        sendEventsThrough(position)
        _state.value = _state.value.copy(position = position)
    }

    private fun sendEventsThrough(position: Double) {
        val current = _state.value
        val events = current.song?.playbackEvents ?: return
        while (eventIndex < events.size && events[eventIndex].timeSeconds <= position) {
            val raw = events[eventIndex++].bytes.copyOf()
            val kind = raw[0].toInt() and 0xf0
            if (kind == 0x90 && raw.size >= 3) {
                raw[2] = ((raw[2].toInt() and 0x7f) * current.dynamics / 100).coerceIn(1, 127).toByte()
            }
            if (current.sendToPiano) bluetooth.send(raw)
            if (current.playOnPhone && raw.size >= 3) {
                val note = raw[1].toInt() and 0x7f
                val velocity = raw[2].toInt() and 0x7f
                if (kind == 0x90 && velocity > 0) phoneSynth().noteOn(note, velocity)
                if (kind == 0x80 || (kind == 0x90 && velocity == 0)) synth?.noteOff(note)
            }
        }
    }

    private fun completePracticeStepIfMatched() {
        val current = _state.value
        if (!current.waitForKeys || !current.playing) return
        val step = current.targetStep ?: return
        if (abs(current.position - step.startSeconds) > 0.08 || current.pressedNotes != step.notes) return
        val next = current.practiceIndex + 1
        if (next >= (current.song?.practiceSteps?.size ?: 0)) {
            if (loopActive()) seek(current.loopStart) else pause()
        } else {
            _state.value = current.copy(practiceIndex = next, position = step.startSeconds + 0.001)
            lastNanos = System.nanoTime()
        }
    }

    fun setTempo(value: Float) { _state.value = _state.value.copy(tempo = value.coerceIn(0.4f, 1.5f)) }
    fun setDynamics(value: Int) { _state.value = _state.value.copy(dynamics = value.coerceIn(50, 110)) }
    fun setPianoVolume(value: Int) {
        _state.value = _state.value.copy(pianoVolume = value.coerceIn(0, 100))
        if (_state.value.connectedDevice != null) bluetooth.setRolandMasterVolume(value)
    }
    fun setWaitForKeys(value: Boolean) { _state.value = _state.value.copy(waitForKeys = value); seek(_state.value.position) }
    fun setShowFingers(value: Boolean) { _state.value = _state.value.copy(showFingers = value) }
    fun setSendToPiano(value: Boolean) { _state.value = _state.value.copy(sendToPiano = value) }
    fun setPlayOnPhone(value: Boolean) {
        _state.value = _state.value.copy(playOnPhone = value)
        if (!value) synth?.allNotesOff()
    }
    fun setViewMode(value: String) { _state.value = _state.value.copy(viewMode = value) }
    fun setLoopStart() { _state.value = _state.value.copy(loopStart = _state.value.position, loopEnabled = false) }
    fun setLoopEnd() {
        val current = _state.value
        if (current.position <= current.loopStart + 0.05) {
            showMessage("Loop end B must be after loop start A")
        } else {
            _state.value = current.copy(loopEnd = current.position, loopEnabled = true)
        }
    }
    fun setLoopEnabled(value: Boolean) {
        if (value && _state.value.loopEnd == null) showMessage("Set loop A and B first")
        else _state.value = _state.value.copy(loopEnabled = value)
    }
    fun clearLoop() { _state.value = _state.value.copy(loopStart = 0.0, loopEnd = null, loopEnabled = false) }
    private fun loopActive() = _state.value.loopEnabled && _state.value.loopEnd != null

    fun scanBluetooth() { _state.value = _state.value.copy(scanning = true); bluetooth.startScan() }
    fun connect(device: BluetoothMidiDevice) = bluetooth.connect(device)
    fun disconnect() = bluetooth.disconnect()

    fun startRecording() {
        runCatching { recorder.start() }
            .onSuccess { _state.value = _state.value.copy(recording = true, recordingPath = it.absolutePath) }
            .onFailure { showMessage(it.message ?: "Could not start recording") }
    }
    fun stopRecording() {
        val file = recorder.stop()
        _state.value = _state.value.copy(recording = false, recordingPath = file?.absolutePath)
    }

    fun projectJson(): String = session().toJson(project = true).toString(2)

    fun loadProject(json: String) {
        val session = runCatching { SavedSession.fromJson(JSONObject(json), requireProject = true) }.getOrNull()
        if (session == null) showMessage("This is not a Roland Piano Trainer project")
        else applySession(session, loadSong = true)
    }

    private fun applySession(session: SavedSession, loadSong: Boolean) {
        _state.value = _state.value.copy(
            tempo = session.tempo,
            dynamics = session.dynamics,
            pianoVolume = session.pianoVolume,
            waitForKeys = session.waitForKeys,
            showFingers = session.showFingers,
            sendToPiano = session.sendToPiano,
            playOnPhone = session.playOnPhone,
            viewMode = session.viewMode,
            loopStart = session.loopStart,
            loopEnd = session.loopEnd,
            loopEnabled = session.loopEnabled,
        )
        if (loadSong && session.songUri != null) loadSong(Uri.parse(session.songUri), session.position)
    }

    fun showMessage(message: String?) { _state.value = _state.value.copy(message = message) }

    private fun session() = SavedSession(
        songUri = _state.value.song?.uri,
        position = _state.value.position,
        tempo = _state.value.tempo,
        dynamics = _state.value.dynamics,
        pianoVolume = _state.value.pianoVolume,
        waitForKeys = _state.value.waitForKeys,
        showFingers = _state.value.showFingers,
        sendToPiano = _state.value.sendToPiano,
        playOnPhone = _state.value.playOnPhone,
        viewMode = _state.value.viewMode,
        loopStart = _state.value.loopStart,
        loopEnd = _state.value.loopEnd,
        loopEnabled = _state.value.loopEnabled,
    )

    fun saveState() = store.save(session())

    private fun allNotesOff() {
        synth?.allNotesOff()
        repeat(16) { channel -> bluetooth.send(byteArrayOf((0xb0 or channel).toByte(), 123, 0)) }
    }

    override fun onCleared() {
        saveState()
        recorder.stop()
        bluetooth.close()
        synth?.close()
        super.onCleared()
    }

    private fun phoneSynth(): PhoneSynth = synth ?: PhoneSynth().also { synth = it }
}
