"""Gera uma filmagem de teste: um gravador e duas câmeras com atrasos conhecidos.

Uso: python tests/make_test_media.py PASTA_DE_SAIDA
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sincronia.media import ffmpeg_path  # noqa: E402

SR = 48000


def speech_like(duration: float, seed: int) -> np.ndarray:
    """Sílabas sintéticas: tons harmônicos com ruído e pausas irregulares."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(duration * SR), np.float32)
    t = 0.0
    while t < duration - 0.5:
        t += rng.uniform(0.05, 0.6)
        length = rng.uniform(0.08, 0.35)
        tt = np.arange(int(length * SR)) / SR
        f0 = rng.uniform(100, 250)
        tone = sum(np.sin(2 * np.pi * k * f0 * tt) / k for k in range(1, 9))
        sig = (tone + 0.3 * rng.standard_normal(len(tt))) * np.sin(np.pi * tt / length) ** 2
        s = int(t * SR)
        out[s:s + len(sig)] += rng.uniform(0.05, 0.25) * sig[:len(out) - s]
        t += length
    return out


def camera_mic(x: np.ndarray, seed: int) -> np.ndarray:
    """Simula o microfone da câmera: abafado, com eco da sala e chiado."""
    rng = np.random.default_rng(seed)
    y = np.convolve(x, np.ones(6) / 6, mode="same")
    echo = int(0.03 * SR)
    y[echo:] += 0.4 * y[:-echo]
    y = 0.6 * y + 0.02 * rng.standard_normal(len(y))
    return y.astype(np.float32)


def write_wav(path: str, x: np.ndarray) -> None:
    data = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def make_video(path: str, audio_wav: str, fps: str, duration: float) -> None:
    subprocess.run(
        [ffmpeg_path(), "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc=size=320x180:rate={fps}:duration={duration}",
         "-i", audio_wav, "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-ac", "2", "-shortest", path],
        check=True,
    )


def main(out_dir: str) -> None:
    source = speech_like(200.0, seed=1)
    tmp = os.path.join(out_dir, "_tmp")
    for d in ("Gravador", "CameraA", "CameraB", tmp):
        os.makedirs(os.path.join(out_dir, d) if d != tmp else d, exist_ok=True)

    write_wav(os.path.join(out_dir, "Gravador", "ZOOM0001.wav"), source)
    truth = {"ZOOM0001.wav": 0.0}

    cameras = [  # (pasta, nome, início no gravador, duração, fps)
        ("CameraA", "A001.mp4", 12.345, 60.0, "30000/1001"),
        ("CameraA", "A002.mp4", 95.0, 85.0, "30000/1001"),
        ("CameraB", "B001.mp4", 3.21, 140.0, "25"),
    ]
    for k, (folder, name, start, dur, fps) in enumerate(cameras):
        seg = source[int(start * SR):int((start + dur) * SR)]
        wav = os.path.join(tmp, name + ".wav")
        write_wav(wav, camera_mic(seg, seed=10 + k))
        make_video(os.path.join(out_dir, folder, name), wav, fps, dur)
        truth[name] = start

    # um clipe de outra filmagem, que não deve ser sincronizado
    wav = os.path.join(tmp, "B002.wav")
    write_wav(wav, camera_mic(speech_like(40.0, seed=99), seed=50))
    make_video(os.path.join(out_dir, "CameraB", "B002.mp4"), wav, "25", 40.0)
    truth["B002.mp4"] = None

    with open(os.path.join(out_dir, "truth.json"), "w") as f:
        json.dump(truth, f, indent=2)


if __name__ == "__main__":
    main(sys.argv[1])
