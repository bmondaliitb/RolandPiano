package com.rolandpiano.trainer.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.rolandpiano.trainer.TrainerUiState
import com.rolandpiano.trainer.TrainerViewModel
import com.rolandpiano.trainer.model.NoteEvent
import com.rolandpiano.trainer.model.noteName
import com.rolandpiano.trainer.model.suggestFingering
import kotlin.math.floor

private val Ink = Color(0xff1d2526)
private val Paper = Color(0xfff4f5f2)
private val Teal = Color(0xff166a73)
private val Gold = Color(0xffd6a43b)
private val Green = Color(0xff2d8a62)
private val Red = Color(0xffc44d45)

@Composable
fun RolandTrainerApp(
    viewModel: TrainerViewModel,
    onOpenMidi: () -> Unit,
    onLoadProject: () -> Unit,
    onSaveProject: () -> Unit,
    onScanBluetooth: () -> Unit,
    onStartRecording: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var showBluetooth by remember { mutableStateOf(false) }

    LaunchedEffect(state.message) {
        state.message?.let {
            snackbar.showSnackbar(it)
            viewModel.showMessage(null)
        }
    }
    MaterialTheme(
        colorScheme = MaterialTheme.colorScheme.copy(
            primary = Teal,
            secondary = Gold,
            background = Paper,
            surface = Color.White,
            onSurface = Ink,
        ),
    ) {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                AppToolbar(
                    state = state,
                    onOpenMidi = onOpenMidi,
                    onLoadProject = onLoadProject,
                    onSaveProject = onSaveProject,
                    onBluetooth = { showBluetooth = true; onScanBluetooth() },
                    onRecord = { if (state.recording) viewModel.stopRecording() else onStartRecording() },
                )
            },
        ) { padding ->
            Column(
                Modifier.fillMaxSize().padding(padding).background(Paper),
            ) {
                Transport(state, viewModel)
                Visualizer(state, Modifier.fillMaxWidth().weight(1f))
                TargetStrip(state)
                PianoKeyboard(state, Modifier.fillMaxWidth().height(126.dp))
            }
        }
    }

    if (showBluetooth) {
        AlertDialog(
            onDismissRequest = { showBluetooth = false },
            title = { Text("Bluetooth MIDI") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(state.connectedDevice?.let { "Connected: $it" } ?: if (state.scanning) "Scanning..." else "Choose the FP-10")
                    state.bluetoothDevices.forEach { device ->
                        Button(
                            onClick = { viewModel.connect(device); showBluetooth = false },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(device.name) }
                    }
                }
            },
            confirmButton = { TextButton(onClick = onScanBluetooth) { Text("Scan again") } },
            dismissButton = {
                if (state.connectedDevice != null) TextButton(onClick = { viewModel.disconnect(); showBluetooth = false }) { Text("Disconnect") }
                else TextButton(onClick = { showBluetooth = false }) { Text("Close") }
            },
        )
    }
}

@Composable
private fun AppToolbar(
    state: TrainerUiState,
    onOpenMidi: () -> Unit,
    onLoadProject: () -> Unit,
    onSaveProject: () -> Unit,
    onBluetooth: () -> Unit,
    onRecord: () -> Unit,
) {
    Surface(shadowElevation = 2.dp) {
        Row(
            Modifier.fillMaxWidth().height(58.dp).padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                state.song?.name ?: "Roland Piano Trainer",
                modifier = Modifier.weight(1f),
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
            )
            ToolIcon("Open MIDI", Icons.Default.FolderOpen, onOpenMidi)
            ToolIcon("Load project", Icons.Default.RestartAlt, onLoadProject)
            ToolIcon("Save project", Icons.Default.Save, onSaveProject, enabled = state.song != null)
            ToolIcon(
                state.connectedDevice ?: "Connect Bluetooth MIDI",
                Icons.Default.Bluetooth,
                onBluetooth,
                tint = if (state.connectedDevice != null) Green else Ink,
            )
            ToolIcon(
                if (state.recording) "Stop audio recording" else "Record piano audio",
                if (state.recording) Icons.Default.Stop else Icons.Default.FiberManualRecord,
                onRecord,
                tint = if (state.recording) Red else Ink,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ToolIcon(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, action: () -> Unit, enabled: Boolean = true, tint: Color = Ink) {
    TooltipBox(positionProvider = TooltipDefaults.rememberPlainTooltipPositionProvider(), tooltip = { Surface { Text(label, Modifier.padding(8.dp)) } }, state = rememberTooltipState()) {
        IconButton(onClick = action, enabled = enabled) { Icon(icon, label, tint = tint) }
    }
}

@Composable
private fun Transport(state: TrainerUiState, vm: TrainerViewModel) {
    Column(Modifier.fillMaxWidth().background(Color.White).padding(horizontal = 10.dp, vertical = 6.dp)) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            IconButton(onClick = vm::togglePlayback, enabled = state.song != null) {
                Icon(if (state.playing) Icons.Default.Pause else Icons.Default.PlayArrow, "Play or pause")
            }
            IconButton(onClick = vm::restart, enabled = state.song != null) { Icon(Icons.Default.RestartAlt, "Restart") }
            Text(timeText(state.position), fontWeight = FontWeight.Medium)
            Slider(
                value = state.position.toFloat(),
                onValueChange = { vm.seek(it.toDouble()) },
                valueRange = 0f..(state.song?.durationSeconds?.toFloat()?.coerceAtLeast(0.01f) ?: 0.01f),
                modifier = Modifier.width(220.dp),
            )
            ViewSelector(state.viewMode, vm::setViewMode)
            Toggle("Wait for keys", state.waitForKeys, vm::setWaitForKeys)
            Toggle("Fingers", state.showFingers, vm::setShowFingers)
            Toggle("Send to piano", state.sendToPiano, vm::setSendToPiano)
            Toggle("Play on phone", state.playOnPhone, vm::setPlayOnPhone)
        }
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ValueSlider("Tempo", "${(state.tempo * 100).toInt()}%", state.tempo, 0.4f..1.5f, vm::setTempo)
            ValueSlider("Dynamics", "${state.dynamics}%", state.dynamics.toFloat(), 50f..110f) { vm.setDynamics(it.toInt()) }
            ValueSlider("Piano volume", "${state.pianoVolume}", state.pianoVolume.toFloat(), 0f..100f) { vm.setPianoVolume(it.toInt()) }
            Button(onClick = vm::setLoopStart, contentPadding = ButtonDefaults.ContentPadding) { Text("Set A") }
            Button(onClick = vm::setLoopEnd, contentPadding = ButtonDefaults.ContentPadding) { Text("Set B") }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(state.loopEnabled, vm::setLoopEnabled)
                Text("Loop")
            }
            TextButton(onClick = vm::clearLoop) { Text("Clear") }
            Text("A ${timeText(state.loopStart)}  B ${state.loopEnd?.let(::timeText) ?: "--:--"}")
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun ViewSelector(value: String, change: (String) -> Unit) {
    SingleChoiceSegmentedButtonRow {
        listOf("roll" to "Roll", "sheet" to "Sheet").forEachIndexed { index, item ->
            SegmentedButton(
                selected = value == item.first,
                onClick = { change(item.first) },
                shape = SegmentedButtonDefaults.itemShape(index, 2),
            ) { Text(item.second) }
        }
    }
}

@Composable
private fun Toggle(label: String, checked: Boolean, change: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked, change, modifier = Modifier.size(width = 46.dp, height = 30.dp))
        Spacer(Modifier.width(5.dp))
        Text(label, fontSize = 13.sp)
    }
}

@Composable
private fun ValueSlider(label: String, valueLabel: String, value: Float, range: ClosedFloatingPointRange<Float>, change: (Float) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("$label $valueLabel", fontSize = 12.sp)
        Slider(value, change, valueRange = range, modifier = Modifier.width(125.dp))
    }
}

@Composable
private fun Visualizer(state: TrainerUiState, modifier: Modifier) {
    val song = state.song
    if (song == null) {
        Box(modifier.background(Color(0xffe7eae5)), contentAlignment = Alignment.Center) {
            Text(if (state.loading) "Loading MIDI..." else "Open a MIDI file", color = Color(0xff5c6665))
        }
        return
    }
    if (state.viewMode == "sheet") SheetMusic(state, modifier) else PianoRoll(state, modifier)
}

@Composable
private fun PianoRoll(state: TrainerUiState, modifier: Modifier) {
    Canvas(modifier.background(Color(0xff171b1c))) {
        val pixelsPerSecond = size.height / 4.5f
        val keyWidth = size.width / 88f
        state.song!!.notes.forEach { note ->
            if (note.endSeconds < state.position || note.startSeconds > state.position + 4.5) return@forEach
            val x = (note.note - 21) * keyWidth
            val top = size.height - ((note.endSeconds - state.position) * pixelsPerSecond).toFloat()
            val bottom = size.height - ((note.startSeconds - state.position) * pixelsPerSecond).toFloat()
            val color = if (note.startSeconds <= state.position && note.endSeconds >= state.position) Gold else if (isBlack(note.note)) Color(0xff4e9aa0) else Teal
            drawRect(color, Offset(x + 1, top), Size((keyWidth - 2).coerceAtLeast(2f), (bottom - top).coerceAtLeast(3f)))
        }
        drawLine(Color.White.copy(alpha = .75f), Offset(0f, size.height - 2), Offset(size.width, size.height - 2), 3f)
        loopMarker(state.loopStart, state.position, pixelsPerSecond, size.height, Green)
        state.loopEnd?.let { loopMarker(it, state.position, pixelsPerSecond, size.height, Red) }
    }
}

private fun DrawScope.loopMarker(time: Double, position: Double, scale: Float, height: Float, color: Color) {
    val y = height - ((time - position) * scale).toFloat()
    if (y in 0f..height) drawLine(color, Offset(0f, y), Offset(size.width, y), 3f)
}

@Composable
private fun SheetMusic(state: TrainerUiState, modifier: Modifier) {
    val text = rememberTextMeasurer()
    Canvas(modifier.background(Color(0xfffbfaf5))) {
        val centerX = size.width * .34f
        val spacing = (size.height / 18f).coerceIn(9f, 18f)
        val trebleY = size.height * .28f
        val bassY = size.height * .64f
        for (line in 0..4) {
            drawLine(Ink, Offset(20f, trebleY + line * spacing), Offset(size.width - 12f, trebleY + line * spacing), 1.5f)
            drawLine(Ink, Offset(20f, bassY + line * spacing), Offset(size.width - 12f, bassY + line * spacing), 1.5f)
        }
        drawText(text, "𝄞", Offset(28f, trebleY - spacing * 1.7f), style = TextStyle(Ink, (spacing * 3.2f).sp))
        drawText(text, "𝄢", Offset(28f, bassY - spacing * .7f), style = TextStyle(Ink, (spacing * 2.4f).sp))
        drawLine(Gold, Offset(centerX, 12f), Offset(centerX, size.height - 12f), 3f)
        state.song!!.notes.forEach { note ->
            val delta = note.startSeconds - state.position
            if (delta !in -1.0..5.0) return@forEach
            val x = centerX + (delta * size.width / 6.0).toFloat()
            val treble = note.note >= 60
            val baseY = if (treble) trebleY + spacing * 4 else bassY + spacing * 4
            val reference = if (treble) 64 else 43
            val steps = diatonicSteps(note.note) - diatonicSteps(reference)
            val y = baseY - steps * spacing / 2f
            val highlighted = note.startSeconds <= state.position && note.endSeconds >= state.position
            drawOval(if (highlighted) Gold else Ink, Offset(x - spacing * .65f, y - spacing * .42f), Size(spacing * 1.3f, spacing * .84f))
            drawLine(if (highlighted) Gold else Ink, Offset(x + spacing * .6f, y), Offset(x + spacing * .6f, y - spacing * 3), 2f)
            if (isBlack(note.note)) drawText(text, "♯", Offset(x - spacing * 1.5f, y - spacing), style = TextStyle(Ink, (spacing * 1.3f).sp))
        }
    }
}

private fun diatonicSteps(note: Int): Int {
    val letters = intArrayOf(0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)
    return (note / 12 - 1) * 7 + letters[note.mod(12)]
}

@Composable
private fun TargetStrip(state: TrainerUiState) {
    val step = state.targetStep
    val text = when {
        !state.waitForKeys -> "Playback ${timeText(state.position)}"
        step == null -> "Practice complete"
        else -> {
            val notes = step.notes.sorted().joinToString(" + ") { noteName(it) }
            val fingers = if (state.showFingers) suggestFingering(step).joinToString("  ") { "${noteName(it.note)} ${it.label}" } else ""
            "Play $notes${if (fingers.isNotEmpty()) "   $fingers" else ""}"
        }
    }
    Surface(color = if (state.waitForKeys) Color(0xffdceef0) else Color.White) {
        Text(text, Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), fontWeight = FontWeight.Medium, maxLines = 1)
    }
}

@Composable
private fun PianoKeyboard(state: TrainerUiState, modifier: Modifier) {
    val text = rememberTextMeasurer()
    val expected = if (state.waitForKeys) state.targetStep?.notes.orEmpty() else emptySet()
    val fingerLabels = if (state.showFingers && state.targetStep != null) suggestFingering(state.targetStep!!).associate { it.note to it.label } else emptyMap()
    Canvas(modifier.background(Color(0xffd7d9d4))) {
        val whiteNotes = (21..108).filterNot(::isBlack)
        val whiteWidth = size.width / whiteNotes.size
        whiteNotes.forEachIndexed { index, note ->
            val active = note in state.pressedNotes
            val target = note in expected
            val color = when {
                active && target -> Green
                active -> Red
                target -> Color(0xff7fc3ca)
                else -> Color.White
            }
            drawRect(color, Offset(index * whiteWidth, 0f), Size(whiteWidth - 1f, size.height), style = androidx.compose.ui.graphics.drawscope.Fill)
            drawRect(Ink, Offset(index * whiteWidth, 0f), Size(whiteWidth, size.height), style = Stroke(1f))
            fingerLabels[note]?.let { drawText(text, it, Offset(index * whiteWidth + 2f, size.height - 23f), style = TextStyle(Ink, 11.sp, FontWeight.Bold)) }
        }
        for (note in 22..107) {
            if (!isBlack(note)) continue
            val whitesBefore = (21 until note).count { !isBlack(it) }
            val x = whitesBefore * whiteWidth - whiteWidth * .34f
            val active = note in state.pressedNotes
            val target = note in expected
            drawRect(when { active && target -> Green; active -> Red; target -> Color(0xff4e9aa0); else -> Ink }, Offset(x, 0f), Size(whiteWidth * .68f, size.height * .62f))
            fingerLabels[note]?.let { drawText(text, it, Offset(x + 1f, size.height * .62f - 19f), style = TextStyle(Color.White, 10.sp, FontWeight.Bold)) }
        }
    }
}

private fun isBlack(note: Int) = note.mod(12) in setOf(1, 3, 6, 8, 10)
private fun timeText(seconds: Double): String = "${floor(seconds / 60).toInt()}:${(seconds.toInt() % 60).toString().padStart(2, '0')}"
