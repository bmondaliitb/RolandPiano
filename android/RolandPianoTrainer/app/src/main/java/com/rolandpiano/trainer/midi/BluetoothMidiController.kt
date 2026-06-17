package com.rolandpiano.trainer.midi

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.Context
import android.media.midi.MidiDevice
import android.media.midi.MidiInputPort
import android.media.midi.MidiManager
import android.media.midi.MidiOutputPort
import android.media.midi.MidiReceiver
import android.os.Handler
import android.os.Looper
import java.io.Closeable
import java.util.concurrent.CopyOnWriteArraySet

data class BluetoothMidiDevice(val name: String, val address: String, internal val device: BluetoothDevice)

class BluetoothMidiController(context: Context) : Closeable {
    private val midiManager = context.getSystemService(MidiManager::class.java)
    private val bluetoothAdapter = context.getSystemService(BluetoothManager::class.java)?.adapter
    private val handler = Handler(Looper.getMainLooper())
    private val discoveredAddresses = CopyOnWriteArraySet<String>()
    private var midiDevice: MidiDevice? = null
    private var inputPort: MidiInputPort? = null
    private var outputPort: MidiOutputPort? = null

    var onDevicesChanged: (List<BluetoothMidiDevice>) -> Unit = {}
    var onConnectionChanged: (String?) -> Unit = {}
    var onNote: (note: Int, pressed: Boolean, velocity: Int) -> Unit = { _, _, _ -> }
    private val devices = mutableListOf<BluetoothMidiDevice>()

    private val receiver = object : MidiReceiver() {
        override fun onSend(data: ByteArray, offset: Int, count: Int, timestamp: Long) {
            var index = offset
            val end = offset + count
            while (index < end) {
                val status = data[index].toInt() and 0xff
                val kind = status and 0xf0
                if ((kind == 0x80 || kind == 0x90) && index + 2 < end) {
                    val note = data[index + 1].toInt() and 0x7f
                    val velocity = data[index + 2].toInt() and 0x7f
                    onNote(note, kind == 0x90 && velocity > 0, velocity)
                    index += 3
                } else {
                    index++
                }
            }
        }
    }

    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) = addDevice(result.device)
        override fun onBatchScanResults(results: MutableList<ScanResult>) = results.forEach { addDevice(it.device) }
    }

    @SuppressLint("MissingPermission")
    fun startScan() {
        devices.clear()
        discoveredAddresses.clear()
        onDevicesChanged(emptyList())
        bluetoothAdapter?.bluetoothLeScanner?.startScan(scanCallback)
        handler.postDelayed({ stopScan() }, 12_000)
    }

    @SuppressLint("MissingPermission")
    fun stopScan() {
        bluetoothAdapter?.bluetoothLeScanner?.stopScan(scanCallback)
    }

    @SuppressLint("MissingPermission")
    private fun addDevice(device: BluetoothDevice) {
        if (!discoveredAddresses.add(device.address)) return
        val name = device.name ?: "Bluetooth MIDI ${device.address.takeLast(5)}"
        synchronized(devices) {
            devices += BluetoothMidiDevice(name, device.address, device)
            onDevicesChanged(devices.sortedBy { it.name.lowercase() })
        }
    }

    @SuppressLint("MissingPermission")
    fun connect(target: BluetoothMidiDevice) {
        stopScan()
        disconnect()
        onConnectionChanged("Connecting to ${target.name}...")
        midiManager.openBluetoothDevice(target.device, { opened ->
            if (opened == null) {
                onConnectionChanged(null)
                return@openBluetoothDevice
            }
            midiDevice = opened
            inputPort = if (opened.info.inputPortCount > 0) opened.openInputPort(0) else null
            outputPort = if (opened.info.outputPortCount > 0) opened.openOutputPort(0) else null
            outputPort?.connect(receiver)
            onConnectionChanged(target.name)
        }, handler)
    }

    fun send(bytes: ByteArray, timestampNanos: Long = 0L) {
        inputPort?.send(bytes, 0, bytes.size, timestampNanos)
    }

    fun setRolandMasterVolume(volume: Int) {
        send(rolandWrite(byteArrayOf(0x01, 0x00, 0x03, 0x06), byteArrayOf(1)))
        send(rolandWrite(byteArrayOf(0x01, 0x00, 0x02, 0x13), byteArrayOf(volume.coerceIn(0, 100).toByte())))
    }

    private fun rolandWrite(address: ByteArray, data: ByteArray): ByteArray {
        val sum = address.sumOf { it.toInt() and 0xff } + data.sumOf { it.toInt() and 0xff }
        val checksum = ((128 - sum.mod(128)) and 0x7f).toByte()
        return byteArrayOf(
            0xf0.toByte(), 0x41, 0x10, 0x00, 0x00, 0x00, 0x28, 0x12,
            *address, *data, checksum, 0xf7.toByte(),
        )
    }

    fun disconnect() {
        outputPort?.disconnect(receiver)
        outputPort?.close()
        inputPort?.close()
        midiDevice?.close()
        outputPort = null
        inputPort = null
        midiDevice = null
        onConnectionChanged(null)
    }

    override fun close() {
        stopScan()
        disconnect()
    }
}
