"""Gera o aplicativo para o sistema atual (Windows: pasta com Sincronia.exe; Mac: Sincronia.app).

Uso: python build.py
"""

import os
import platform
import shutil
import subprocess
import sys

import PyInstaller.__main__

from sincronia import __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

args = [
    "run_sincronia.py",
    "--name", "Sincronia",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--collect-data", "imageio_ffmpeg",   # o FFmpeg vai junto dentro do aplicativo
    "--add-data", f"sincronia/resources{os.pathsep}sincronia/resources",
    "--icon", "sincronia/resources/icon.png",   # convertido para .ico/.icns pelo Pillow
    "--exclude-module", "tkinter",
    "--exclude-module", "pytest",
]
if sys.platform == "darwin":
    args += ["--osx-bundle-identifier", "app.sincronia.Sincronia"]

PyInstaller.__main__.run(args)

if sys.platform == "darwin":
    # o FFmpeg precisa de permissão de execução dentro do .app
    for folder, _, names in os.walk(os.path.join("dist", "Sincronia.app")):
        for n in names:
            if n.startswith("ffmpeg"):
                os.chmod(os.path.join(folder, n), 0o755)
    chip = "apple-silicon" if platform.machine() == "arm64" else "intel"
    archive = f"Sincronia-{__version__}-mac-{chip}"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", "dist/Sincronia.app",
                    f"dist/{archive}.zip"], check=True)
else:
    archive = f"Sincronia-{__version__}-windows"
    shutil.make_archive(os.path.join("dist", archive), "zip", "dist", "Sincronia")
print(f"\nPronto: dist/{archive}.zip")
