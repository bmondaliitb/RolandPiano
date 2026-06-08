#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "Error: activate the Roland Piano virtual environment first." >&2
    echo "Example: source /path/to/venv/bin/activate" >&2
    exit 1
fi

python_bin="${VIRTUAL_ENV}/bin/python"
if [[ ! -x "${python_bin}" ]]; then
    echo "Error: virtual environment Python not found: ${python_bin}" >&2
    exit 1
fi

if ! "${python_bin}" -c "import roland_piano.trainer_app" >/dev/null 2>&1; then
    echo "Error: roland_piano is not installed in ${VIRTUAL_ENV}." >&2
    echo "Run: python -m pip install -e ." >&2
    exit 1
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
applications_dir="${HOME}/.local/share/applications"
icons_dir="${HOME}/.local/share/icons/hicolor/256x256/apps"
desktop_file="${applications_dir}/roland-piano-trainer.desktop"
icon_file="${icons_dir}/roland-piano-trainer.png"

mkdir -p "${applications_dir}" "${icons_dir}"
cp "${project_dir}/assets/icons/hicolor/256x256/apps/roland-piano-trainer.png" "${icon_file}"

cat >"${desktop_file}" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Roland Piano Trainer
GenericName=Piano Learning App
Comment=Practice MIDI songs with guided keys, fingering, and wait mode
Exec=${python_bin} -m roland_piano.trainer_app
Path=${project_dir}
Icon=${icon_file}
Terminal=false
Categories=Education;Music;
Keywords=Piano;MIDI;Roland;Practice;Music;
StartupNotify=true
StartupWMClass=Roland FP-10 Piano Trainer
EOF

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "${desktop_file}"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${applications_dir}"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed ${desktop_file}"
echo "Using virtual environment: ${VIRTUAL_ENV}"
