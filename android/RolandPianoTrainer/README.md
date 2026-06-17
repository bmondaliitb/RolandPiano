# Roland Piano Trainer for Android

This is a separate Android implementation of the Fedora trainer. It targets Android 6.0+ and uses Android's native Bluetooth Low Energy MIDI support for the Roland FP-10.

## Features

- Loads Standard MIDI files through Android's document picker.
- Piano-roll and grand-staff views with live note highlighting.
- 88-key keyboard display.
- Flowkey-style `Wait for keys` mode. Playback advances only when the exact target note or chord is held on the FP-10.
- Optional generated left/right-hand finger suggestions.
- Manual A/B loop practice.
- Tempo and MIDI dynamics controls.
- MIDI playback to the FP-10 over Bluetooth.
- Low-overhead synthesized playback on the phone.
- Roland FP master-volume control over SysEx.
- Actual piano-audio recording through the phone microphone.
- Automatic session restoration.
- Save/load `.roland-project.json` project files.

Audio recordings such as MP3 or WAV are not transcribed on-device. This matches the desktop app's converter-dependent behavior: convert audio to MIDI externally, then open the MIDI file.

## Build

1. Install Android Studio and Android SDK 36.
2. Open the `android/RolandPianoTrainer` folder in Android Studio.
3. Select JDK 17 for Gradle.
4. Let Android Studio sync the included Gradle wrapper.
5. Run the `app` configuration on a physical Android device.

This workstation currently has no Android SDK and only JDK 25, so the project cannot be assembled here until Android Studio's JDK 17 and SDK are available.

## Connect the FP-10

1. Enable Bluetooth MIDI pairing mode on the FP-10.
2. Open the app and tap the Bluetooth icon.
3. Allow the Nearby Devices permission.
4. Select the piano from the scan results.

The FP-10 Bluetooth connection is MIDI, not Bluetooth audio. Phone playback uses the Android device's speakers/headphones. Audio recording uses the Android device microphone, so placing the phone near the piano gives the cleanest result.

## Permissions

- `Nearby devices`: scans for and communicates with the Bluetooth MIDI piano.
- `Location` on Android 11 and older: required by Android for BLE scanning.
- `Microphone`: records the piano's actual sound.

MIDI and project files are accessed with Android's Storage Access Framework; no broad storage permission is requested.
