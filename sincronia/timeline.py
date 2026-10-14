"""Monta a linha do tempo: onde cada clipe começa e em qual trilha fica."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from .media import MediaInfo
from .sync import SyncResult

GROUP_GAP = 2.0   # segundos de espaço entre um grupo sincronizado e o próximo


@dataclass
class Placement:
    clip: MediaInfo
    start: float                 # segundos desde o início da sequência
    group: int                   # -1 = não sincronizado
    video_track: int | None = None
    audio_track: int | None = None


@dataclass
class Timeline:
    placements: list[Placement]
    video_tracks: int
    audio_tracks: int
    timebase: int
    ntsc: bool
    width: int
    height: int

    @property
    def fps(self) -> float:
        return self.timebase * 1000 / 1001 if self.ntsc else float(self.timebase)

    def frames(self, seconds: float) -> int:
        return int(round(seconds * self.fps))


def rate_from_fps(fps: float) -> tuple[int, bool]:
    for nominal in (24, 30, 48, 60, 120):
        if abs(fps - nominal * 1000 / 1001) < 0.01:
            return nominal, True
    return max(1, int(round(fps))), False


def _pack(items: list[Placement]) -> list[int]:
    """Distribui clipes em faixas sem sobreposição; retorna a faixa de cada um."""
    lane_end: list[float] = []
    lanes = []
    for p in items:
        for k, end in enumerate(lane_end):
            if end <= p.start + 1e-3:
                lane_end[k] = p.start + p.clip.duration
                lanes.append(k)
                break
        else:
            lane_end.append(p.start + p.clip.duration)
            lanes.append(len(lane_end) - 1)
    return lanes


def build_timeline(clips: Sequence[MediaInfo], result: SyncResult,
                   include_unmatched: bool = True) -> Timeline:
    placements: list[Placement] = []
    t = 0.0
    for g, group in enumerate(result.groups):
        end = 0.0
        for idx, pos in group:
            placements.append(Placement(clips[idx], t + pos, g))
            end = max(end, pos + clips[idx].duration)
        t += end + GROUP_GAP
    if include_unmatched:
        for idx in result.unmatched:
            if clips[idx].has_video or clips[idx].has_audio:
                placements.append(Placement(clips[idx], t, -1))
                t += clips[idx].duration + GROUP_GAP

    # Cada câmera/gravador ganha suas próprias trilhas, em ordem alfabética.
    def lanes_by_device(items):
        devices: dict[str, list[Placement]] = {}
        for p in items:
            devices.setdefault(p.clip.device, []).append(p)
        result_lanes = []
        for _, device_items in sorted(devices.items(), key=lambda kv: kv[0].lower()):
            device_items.sort(key=lambda p: p.start)
            result_lanes.append((device_items, _pack(device_items)))
        return result_lanes

    video_items = [p for p in placements if p.clip.has_video]
    audio_only = [p for p in placements if not p.clip.has_video and p.clip.has_audio]

    video_tracks = 0
    for items, lanes in lanes_by_device(video_items):
        for p, lane in zip(items, lanes):
            p.video_track = video_tracks + lane
        video_tracks += max(lanes) + 1

    # Áudio: primeiro os gravadores externos (som principal), depois o som das câmeras.
    audio_tracks = 0
    for items, lanes in lanes_by_device(audio_only):
        for p, lane in zip(items, lanes):
            p.audio_track = audio_tracks + lane
        audio_tracks += max(lanes) + 1
    camera_audio = {}
    for p in video_items:
        if p.clip.has_audio:
            if p.video_track not in camera_audio:
                camera_audio[p.video_track] = None
    for k, track in enumerate(sorted(camera_audio)):
        camera_audio[track] = audio_tracks + k
    audio_tracks += len(camera_audio)
    for p in video_items:
        if p.clip.has_audio:
            p.audio_track = camera_audio[p.video_track]

    videos = [c for c in clips if c.has_video and c.fps > 0]
    if videos:
        timebase, ntsc = Counter(rate_from_fps(c.fps) for c in videos).most_common(1)[0][0]
        width, height = Counter((c.width, c.height) for c in videos).most_common(1)[0][0]
    else:
        timebase, ntsc, width, height = 30, True, 1920, 1080

    placements.sort(key=lambda p: (p.start, p.clip.name))
    return Timeline(placements, video_tracks, audio_tracks, timebase, ntsc, width, height)
