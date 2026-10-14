import json
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_test_media import camera_mic, main as make_media, speech_like  # noqa: E402
from sincronia.cli import collect  # noqa: E402
from sincronia.media import ANALYSIS_RATE, MediaInfo, probe  # noqa: E402
from sincronia.premiere import write_premiere_xml  # noqa: E402
from sincronia.sync import synchronize  # noqa: E402
from sincronia.timeline import build_timeline  # noqa: E402


@pytest.fixture(scope="session")
def shoot(tmp_path_factory):
    folder = tmp_path_factory.mktemp("filmagem")
    make_media(str(folder))
    with open(folder / "truth.json") as f:
        truth = json.load(f)
    clips = [probe(p) for p in collect([str(folder / d) for d in ("Gravador", "CameraA", "CameraB")])]
    return clips, truth, synchronize(clips)


def test_offsets_match_truth(shoot):
    clips, truth, result = shoot
    assert len(result.groups) == 1
    positions = {clips[i].name: pos for i, pos in result.groups[0]}
    expected = {k: v for k, v in truth.items() if v is not None}
    assert set(positions) == set(expected)
    for name, start in expected.items():
        assert positions[name] == pytest.approx(start, abs=0.002), name


def test_unrelated_clip_is_not_synced(shoot):
    clips, _, result = shoot
    assert [clips[i].name for i in result.unmatched] == ["B002.mp4"]


def test_premiere_xml(shoot, tmp_path):
    clips, _, result = shoot
    timeline = build_timeline(clips, result)
    out = tmp_path / "seq.xml"
    write_premiere_xml(timeline, str(out))

    root = ET.parse(out).getroot()
    assert root.tag == "xmeml"
    seq = root.find("sequence")
    assert seq.findtext("rate/timebase") == "30" and seq.findtext("rate/ntsc") == "TRUE"
    video_tracks = seq.findall("media/video/track")
    audio_tracks = seq.findall("media/audio/track")
    # CameraA (2 clipes em sequência) e CameraB (B001 e B002 não se sobrepõem)
    assert len(video_tracks) == 2
    # gravador + áudio de cada trilha de câmera
    assert len(audio_tracks) == 3

    names_v1 = [ci.findtext("name") for ci in video_tracks[0].findall("clipitem")]
    assert names_v1 == ["A001.mp4", "A002.mp4"]

    items = {ci.findtext("name"): ci for ci in seq.iter("clipitem")
             if ci.find("sourcetrack") is None}
    fps = 30000 / 1001
    assert int(items["A001.mp4"].findtext("start")) == round(12.345 * fps)
    assert int(items["B001.mp4"].findtext("start")) == round(3.21 * fps)

    # cada arquivo é descrito por completo uma única vez
    full = [f for f in seq.iter("file") if f.find("pathurl") is not None]
    assert len(full) == len({f.get("id") for f in seq.iter("file")}) == 5


def _fake_clip(name, device, audio, video=True):
    return MediaInfo(path=name, duration=len(audio) / ANALYSIS_RATE, has_video=video,
                     has_audio=True, width=1920, height=1080, fps=25.0, channels=2,
                     device=device, audio=(audio * 20000).astype(np.int16))


def test_short_clips_and_long_recording():
    """Gravador de 20 min com clipes de 8 s espalhados."""
    sr = ANALYSIS_RATE
    source = speech_like(20 * 60, seed=7)[::6]   # 48 kHz -> 8 kHz
    clips = [_fake_clip("rec.wav", "Gravador", source, video=False)]
    starts = [30.0, 401.37, 777.7, 1100.05]
    for k, s in enumerate(starts):
        seg = camera_mic(source[int(s * sr):int((s + 8) * sr)], seed=k)
        clips.append(_fake_clip(f"C{k}.mp4", "Camera", seg))

    result = synchronize(clips)
    assert result.unmatched == []
    positions = {clips[i].name: pos for i, pos in result.groups[0]}
    for k, s in enumerate(starts):
        assert positions[f"C{k}.mp4"] == pytest.approx(s, abs=0.002)
