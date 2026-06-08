# Roland Piano
Library for interfacing with Roland FP pianos over midi. Tested on both Mac and Linux.

# Installation
Run:
```bash
python3 -m pip install roland-piano
```

# How this started
I found the button only interface on my Roland FP-10 somewhat limiting. The app would give more insight, but was a bit too buggy IMO. Hence I decided to reverse engineer the Roland specific midi messages and create a Python API so that people can build their own interface. Feel free to contribute!

# Examples
Please look at the unit tests on how to use the library. The main difference is that the imports are handled as if you installed the library with Pip:

```python
from roland_piano import RolandPiano, discover, RolandAddressMap, Instruments
```

# Piano trainer app
This repository also includes a Fedora-friendly Python 3 desktop app that loads a piano song, converts it to MIDI when possible, and shows the keys to play on an 88-key keyboard display.

It works directly with MIDI files (`.mid`, `.midi`). Audio files (`.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`, and similar) need an external audio-to-MIDI converter. The app does not require a specific converter; set `AUDIO_TO_MIDI_COMMAND` to any command that writes a `.mid` or `.midi` file into `{output_dir}`.

```bash
sudo dnf install python3 python3-pip python3-tkinter alsa-lib-devel portaudio-devel
python3 -m pip install --user .
```

Optional audio converter hook:

```bash
export AUDIO_TO_MIDI_COMMAND='converter "{input}" "{output_dir}"'
```

If `basic-pitch` is already available on your `PATH`, the app can still use it automatically, but it is not required for MIDI files.

Run the app:

```bash
roland-piano-trainer
```

To practice in wait mode:

1. Connect the FP-10 to Fedora by USB and open a MIDI song.
2. Enable `Wait for keys`.
3. Press `Play`.
4. Play the blue target key or chord. The song remains stopped until the physically held keys exactly match the target.

Correct pressed keys turn green. Extra incorrect keys turn red. For chords, all chord notes must be held together before the song advances.

Enable `Show fingers` to display suggested finger labels on target keys and in the practice prompt. `L` and `R` mean left and right hand; fingers are numbered `1` for the thumb through `5` for the little finger. These suggestions are generated from note position and common chord shapes because ordinary MIDI files do not contain authoritative fingering.

Or open a song immediately:

```bash
roland-piano-trainer path/to/song.mid
roland-piano-trainer --send-to-piano path/to/song.mid
```

`--send-to-piano` sends the MIDI notes to the first MIDI output whose name starts with `Roland Digital Piano`. You can use the app without a connected FP-10; it will still show the falling notes and highlighted keys.

Audio transcription quality depends on the input recording and on the converter you choose. Clean solo piano audio works best; dense full-band recordings can produce noisy MIDI.

# Limitations
- Doesn't trigger events (e.g. volume changed) over midi when changing many of the piano settings. Connecting with the app enables this, so I  (or you😃) need to do some digging on how this is achieved. Contact me for more information on what I have tried so far.
- API is quite limited at the moment, but there is some low hanging fruit for more functionality.
