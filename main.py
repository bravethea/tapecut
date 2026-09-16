# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import sys
import subprocess
import shutil
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow


def check_dependencies():
    missing = []
    if not shutil.which("ffmpeg"):
        missing.append("ffmpeg (brew install ffmpeg)")
    try:
        import sounddevice  # noqa: F401
    except OSError:
        missing.append("portaudio (brew install portaudio)")
    return missing


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tapecut")
    app.setOrganizationName("tapecut")

    missing = check_dependencies()
    if missing:
        msg = QMessageBox()
        msg.setWindowTitle("Missing dependencies")
        msg.setText(
            "Tapecut requires the following system dependencies:\n\n"
            + "\n".join(f"  • {m}" for m in missing)
            + "\n\nInstall them and restart."
        )
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()
        sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
