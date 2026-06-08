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

The application icon source and Fedora/GNOME-compatible PNG sizes are available under `assets/icons/`. The packaged app also uses the icon in its window and task switcher.

When using a virtual environment, install the GNOME desktop launcher while that environment is active:

```bash
source /path/to/venv/bin/activate
python -m pip install -e .
./packaging/install-desktop-launcher.sh
```

The installer writes `~/.local/share/applications/roland-piano-trainer.desktop` with the virtual environment's absolute Python path. Run it again after replacing or moving the virtual environment.

To practice in wait mode:

1. Connect the FP-10 to Fedora by USB and open a MIDI song.
2. Enable `Wait for keys`.
3. Press `Play`.
4. Play the blue target key or chord. The song remains stopped until the physically held keys exactly match the target.

Correct pressed keys turn green. Extra incorrect keys turn red. For chords, all chord notes must be held together before the song advances.

Enable `Show fingers` to display suggested finger labels on target keys and in the practice prompt. `L` and `R` mean left and right hand; fingers are numbered `1` for the thumb through `5` for the little finger. These suggestions are generated from note position and common chord shapes because ordinary MIDI files do not contain authoritative fingering.

To repeat a short section, use the `Position` slider to move the playhead to the beginning and press `Set A`, then move it to the end and press `Set B`. Setting B enables `Loop` automatically. The section repeats in normal playback and in `Wait for keys` mode. Use `Clear` to remove the loop.

Or open a song immediately:

```bash
roland-piano-trainer path/to/song.mid
roland-piano-trainer --send-to-piano path/to/song.mid
```

`--send-to-piano` sends the MIDI notes to the first MIDI output whose name starts with `Roland Digital Piano`. You can use the app without a connected FP-10; it will still show the falling notes and highlighted keys.

When sending MIDI to the Roland, use `Dynamics` to adjust output velocity. The default `85%` softens aggressive MIDI files while preserving their quiet notes and accents. Playback also preserves sustain, sostenuto, and soft-pedal messages, handles repeated pitches independently, and ignores the standard MIDI percussion channel. Piano-only MIDI files will sound cleaner than dense arrangements containing several instrumental parts.

Use `Piano volume` to adjust the FP-10 master volume from the app. This is independent of `Dynamics`: master volume changes overall loudness, while Dynamics changes how softly or strongly MIDI notes are played.

The app saves its window size, last song, playhead position, controls, practice options, and loop selection when it closes. The next launch restores that state while remaining paused. State is stored at `$XDG_CONFIG_HOME/roland-piano/trainer-state.json`, or `~/.config/roland-piano/trainer-state.json` when `XDG_CONFIG_HOME` is not set.

Use `Save Project` to store the current song, playhead, controls, practice options, and loop in a named `.roland-project.json` file. `Load Project` restores it later while remaining paused. When the project and MIDI file are kept in the same folder, the song path is saved relatively so the folder can be moved together.

Audio transcription quality depends on the input recording and on the converter you choose. Clean solo piano audio works best; dense full-band recordings can produce noisy MIDI.

# Limitations
- Doesn't trigger events (e.g. volume changed) over midi when changing many of the piano settings. Connecting with the app enables this, so I  (or you😃) need to do some digging on how this is achieved. Contact me for more information on what I have tried so far.
- API is quite limited at the moment, but there is some low hanging fruit for more functionality.
