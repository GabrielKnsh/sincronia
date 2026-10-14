"""Cenários de casamento: gravações longas, deriva de relógio, muitos clipes."""

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_test_media import camera_mic, speech_like  # noqa: E402
from sincronia.media import ANALYSIS_RATE, MediaInfo  # noqa: E402
from sincronia.sync import synchronize  # noqa: E402

SR = ANALYSIS_RATE


def fake(name, device, audio, video=True):
    return MediaInfo(path=name, duration=len(audio) / SR, has_video=video, has_audio=True,
                     width=1920, height=1080, fps=29.97, channels=2, device=device,
                     audio=(np.clip(audio, -1, 1) * 20000).astype(np.int16))


def stretch(x, rate):
    """Simula um relógio que anda `rate` mais rápido (ex.: 50e-6 = 50 ppm)."""
    t = np.arange(int(len(x) / (1 + rate))) * (1 + rate)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


@pytest.fixture(scope="module")
def ceremony():
    return speech_like(95 * 60, seed=3)[::6]   # 95 min a 8 kHz


def test_drift_is_measured_and_split(ceremony):
    start, length, ppm = 300.0, 40 * 60, 60e-6
    seg = ceremony[int(start * SR):int((start + length) * SR)]
    clips = [fake("rec.wav", "Gravador", ceremony, video=False),
             fake("tripe.mp4", "Camera", camera_mic(stretch(seg, ppm), seed=1))]
    result = synchronize(clips)
    m = result.accepted[0]
    # 60 ppm em 40 min = 144 ms de desvio de uma ponta à outra
    assert m.drift_ms == pytest.approx(144, abs=10)
    # posicionado pelo meio: o erro em cada ponta fica em ~metade
    pos = dict(result.groups[0])[1]
    assert abs(pos - start) < 0.080


def test_wedding_scale(ceremony):
    rng = np.random.default_rng(5)
    clips = [fake("ZOOM0001.wav", "Gravador", ceremony, video=False)]
    truth = {}

    seg = ceremony[int(120 * SR):int(3720 * SR)]
    clips.append(fake("TRIPE.mp4", "Camera C", camera_mic(seg, seed=0)))
    truth["TRIPE.mp4"] = 120.0

    t = 60.0
    for k in range(30):   # câmera principal: clipes de 1 a 3 min
        length = rng.uniform(60, 180)
        seg = ceremony[int(t * SR):int((t + length) * SR)]
        clips.append(fake(f"A{k:03d}.mp4", "Camera A", camera_mic(seg, seed=100 + k)))
        truth[f"A{k:03d}.mp4"] = t
        t += length + rng.uniform(5, 40)
        if t > 90 * 60:
            break

    t = 30.0
    for k in range(40):   # segunda câmera: clipes curtos de 10 a 30 s
        length = rng.uniform(10, 30)
        seg = ceremony[int(t * SR):int((t + length) * SR)]
        clips.append(fake(f"B{k:03d}.mp4", "Camera B", camera_mic(seg, seed=200 + k)))
        truth[f"B{k:03d}.mp4"] = t
        t += length + rng.uniform(30, 100)

    began = time.perf_counter()
    result = synchronize(clips)
    elapsed = time.perf_counter() - began
    print(f"\n{len(clips)} clipes, {len(result.matches)} pares, {elapsed:.1f} s")

    assert result.unmatched == []
    assert len(result.groups) == 1
    positions = {clips[i].name: p for i, p in result.groups[0]}
    errors = {n: abs(positions[n] - s) for n, s in truth.items()}
    worst = max(errors, key=errors.get)
    assert errors[worst] < 0.005, (worst, errors[worst])


def test_repeated_music_is_not_forced():
    """Um trecho de música que se repete não deve gerar sincronização falsa."""
    rng = np.random.default_rng(9)
    beat = speech_like(4.0, seed=11)[::6]
    loop = np.tile(beat, 30)                       # 2 min de um padrão de 4 s em loop
    rec = loop + 0.01 * rng.standard_normal(len(loop)).astype(np.float32)
    clip = camera_mic(loop[int(41.3 * SR):int(61.3 * SR)], seed=2)
    clips = [fake("rec.wav", "Gravador", rec, video=False), fake("cam.mp4", "Camera", clip)]
    result = synchronize(clips)
    assert result.groups == []          # ambíguo: melhor não sincronizar do que errar
