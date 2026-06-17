package com.rolandpiano.trainer

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.rolandpiano.trainer.ui.RolandTrainerApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val trainer: TrainerViewModel = viewModel()
            var pendingProject by remember { mutableStateOf<String?>(null) }
            var pendingBluetoothAction by remember { mutableStateOf<(() -> Unit)?>(null) }
            var pendingRecordAction by remember { mutableStateOf<(() -> Unit)?>(null) }

            val openMidi = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
                uri?.let {
                    runCatching {
                        contentResolver.takePersistableUriPermission(it, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    trainer.loadSong(it)
                }
            }
            val openProject = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
                uri?.let {
                    contentResolver.openInputStream(it)?.bufferedReader()?.use { reader -> trainer.loadProject(reader.readText()) }
                }
            }
            val saveProject = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
                val json = pendingProject
                if (uri != null && json != null) {
                    contentResolver.openOutputStream(uri, "wt")?.bufferedWriter()?.use { it.write(json) }
                }
                pendingProject = null
            }
            val bluetoothPermissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
                if (result.values.all { it }) pendingBluetoothAction?.invoke()
                else trainer.showMessage("Nearby devices permission is required for Bluetooth MIDI")
                pendingBluetoothAction = null
            }
            val recordPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                if (granted) pendingRecordAction?.invoke()
                else trainer.showMessage("Microphone permission is required to record the piano")
                pendingRecordAction = null
            }

            fun withBluetoothPermission(action: () -> Unit) {
                val required = if (Build.VERSION.SDK_INT >= 31) {
                    arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
                } else {
                    arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
                }
                val missing = required.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
                if (missing.isEmpty()) action() else {
                    pendingBluetoothAction = action
                    bluetoothPermissions.launch(missing.toTypedArray())
                }
            }

            fun withRecordPermission(action: () -> Unit) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    action()
                } else {
                    pendingRecordAction = action
                    recordPermission.launch(Manifest.permission.RECORD_AUDIO)
                }
            }

            RolandTrainerApp(
                viewModel = trainer,
                onOpenMidi = { openMidi.launch(arrayOf("audio/midi", "audio/x-midi", "application/octet-stream")) },
                onLoadProject = { openProject.launch(arrayOf("application/json")) },
                onSaveProject = {
                    pendingProject = trainer.projectJson()
                    saveProject.launch("${trainer.state.value.song?.name?.substringBeforeLast('.') ?: "piano"}.roland-project.json")
                },
                onScanBluetooth = { withBluetoothPermission(trainer::scanBluetooth) },
                onStartRecording = { withRecordPermission(trainer::startRecording) },
            )
        }
    }

    override fun onPause() {
        (androidx.lifecycle.ViewModelProvider(this)[TrainerViewModel::class.java]).saveState()
        super.onPause()
    }
}
