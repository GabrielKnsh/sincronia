"""Leitura de arquivos de mídia com FFmpeg: metadados e extração de áudio."""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np

# Taxa usada na análise. 8 kHz basta para achar o alinhamento e mantém
# arquivos longos leves na memória (1 hora ≈ 57 MB).
ANALYSIS_RATE = 8000

MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".mxf", ".avi", ".mkv", ".mpg",
    ".mpeg", ".wmv", ".3gp", ".insv",
    ".wav", ".mp3", ".m4a", ".aac", ".aif", ".aiff", ".flac", ".ogg", ".bwf",
}


class MediaError(Exception):
    pass


@dataclass
class MediaInfo:
    path: str
    duration: float                  # segundos
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0
    sample_rate: int = 48000
    channels: int = 2
    device: str = ""                 # câmera/gravador (por padrão, a pasta)
    audio: np.ndarray | None = field(default=None, repr=False)
    peaks: np.ndarray | None = field(default=None, repr=False)   # forma de onda resumida

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


def _hidden_window_flags() -> int:
    # Evita que uma janela preta de console pisque no Windows.
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _allow_on_mac(exe: str) -> None:
    # Arquivos baixados da internet ganham a marca de "quarentena" do macOS, que
    # pode impedir o FFmpeg interno de rodar mesmo depois de o usuário liberar o app.
    try:
        os.chmod(exe, 0o755)
        subprocess.run(["xattr", "-d", "com.apple.quarantine", exe], capture_output=True)
    except OSError:
        pass


@functools.lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg   # FFmpeg embutido no aplicativo
        bundled = os.path.join(os.path.dirname(imageio_ffmpeg.__file__), "binaries")
        for name in sorted(os.listdir(bundled)):
            if name.startswith("ffmpeg"):
                exe = os.path.join(bundled, name)
                if sys.platform == "darwin":
                    _allow_on_mac(exe)
                return exe
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise MediaError("FFmpeg não foi encontrado.")


def is_media_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STREAM_RE = re.compile(r"^\s*Stream #\d+:\d+.*?: (Video|Audio): (.*)$", re.MULTILINE)
_SIZE_RE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_FPS_RE = re.compile(r"([\d.]+) fps")
_TBR_RE = re.compile(r"([\d.]+)k? tbr")
_HZ_RE = re.compile(r"(\d+) Hz")
_CHANNELS_RE = re.compile(r"(\d+) channels")


def probe(path: str) -> MediaInfo:
    """Lê duração, resolução, fps e formato de áudio a partir do `ffmpeg -i`."""
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-nostdin", "-i", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_hidden_window_flags(),
    )
    text = proc.stderr

    m = _DURATION_RE.search(text)
    if not m:
        raise MediaError(f"Não consegui ler o arquivo: {os.path.basename(path)}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    info = MediaInfo(path=path, duration=duration, has_video=False, has_audio=False,
                     device=os.path.basename(os.path.dirname(path)) or "Mídia")

    for kind, desc in _STREAM_RE.findall(text):
        if kind == "Video" and not info.has_video:
            if "attached pic" in desc:   # capa de álbum em mp3/m4a
                continue
            info.has_video = True
            size = _SIZE_RE.search(desc)
            if size:
                info.width, info.height = int(size.group(1)), int(size.group(2))
            fps = _FPS_RE.search(desc) or _TBR_RE.search(desc)
            if fps:
                info.fps = float(fps.group(1))
        elif kind == "Audio" and not info.has_audio:
            info.has_audio = True
            hz = _HZ_RE.search(desc)
            if hz:
                info.sample_rate = int(hz.group(1))
            ch = _CHANNELS_RE.search(desc)
            if ch:
                info.channels = int(ch.group(1))
            elif "mono" in desc:
                info.channels = 1
            elif "stereo" in desc:
                info.channels = 2
            elif "5.1" in desc:
                info.channels = 6
    return info


def load_audio(info: MediaInfo) -> np.ndarray:
    """Extrai o áudio em mono, 8 kHz, como int16 (metade da memória de float32)."""
    if not info.has_audio:
        raise MediaError(f"O arquivo não tem áudio: {info.name}")
    proc = subprocess.run(
        [ffmpeg_path(), "-nostdin", "-v", "error", "-i", info.path,
         "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(ANALYSIS_RATE),
         "-f", "s16le", "-"],
        capture_output=True, creationflags=_hidden_window_flags(),
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise MediaError(f"Falha ao extrair áudio de {info.name}: {err[-1] if err else ''}")
    samples = np.frombuffer(proc.stdout, dtype=np.int16)
    info.audio = samples
    info.peaks = waveform_peaks(samples)
    return samples


PEAKS_PER_SECOND = 20


def waveform_peaks(samples: np.ndarray) -> np.ndarray:
    """Forma de onda resumida (20 valores por segundo, de 0 a 1) para desenhar na tela."""
    block = ANALYSIS_RATE // PEAKS_PER_SECOND
    n = len(samples) // block
    if n == 0:
        return np.zeros(0, np.float32)
    peaks = np.abs(samples[:n * block].reshape(n, block).astype(np.float32)).max(axis=1)
    ref = np.percentile(peaks, 99) or 1.0
    return np.sqrt(np.clip(peaks / ref, 0, 1)).astype(np.float32)
