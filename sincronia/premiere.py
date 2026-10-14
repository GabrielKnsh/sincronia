"""Exporta a linha do tempo como XML (formato Final Cut Pro 7 / xmeml),
que o Premiere Pro importa em Arquivo > Importar."""

from __future__ import annotations

import os
import urllib.parse
import xml.etree.ElementTree as ET

from .timeline import Placement, Timeline


def path_url(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):        # Windows: C:/... -> /C:/...
        p = "/" + p
    return "file://localhost" + urllib.parse.quote(p, safe="/")


def _sub(parent: ET.Element, tag: str, text=None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _rate(parent: ET.Element, tl: Timeline) -> None:
    rate = _sub(parent, "rate")
    _sub(rate, "timebase", tl.timebase)
    _sub(rate, "ntsc", "TRUE" if tl.ntsc else "FALSE")


def _timecode(parent: ET.Element, tl: Timeline) -> None:
    tc = _sub(parent, "timecode")
    _rate(tc, tl)
    _sub(tc, "string", "00:00:00:00")
    _sub(tc, "frame", 0)
    _sub(tc, "displayformat", "NDF")


def write_premiere_xml(tl: Timeline, out_path: str, sequence_name: str = "Sincronia") -> None:
    file_ids: dict[str, str] = {}
    defined: set[str] = set()
    for p in tl.placements:
        file_ids.setdefault(p.clip.path, f"file-{len(file_ids) + 1}")

    # ids e posição (índice dentro da trilha) de cada clipitem, para os <link>
    video_by_track: list[list[Placement]] = [[] for _ in range(tl.video_tracks)]
    audio_by_track: list[list[Placement]] = [[] for _ in range(tl.audio_tracks)]
    for p in tl.placements:
        if p.video_track is not None:
            video_by_track[p.video_track].append(p)
        if p.audio_track is not None:
            audio_by_track[p.audio_track].append(p)
    for lst in video_by_track + audio_by_track:
        lst.sort(key=lambda p: p.start)

    counter = iter(range(1, 1_000_000))
    vid_item: dict[int, tuple[str, int]] = {}
    aud_item: dict[int, tuple[str, int]] = {}
    for lst in video_by_track:
        for k, p in enumerate(lst, 1):
            vid_item[id(p)] = (f"clipitem-{next(counter)}", k)
    for lst in audio_by_track:
        for k, p in enumerate(lst, 1):
            aud_item[id(p)] = (f"clipitem-{next(counter)}", k)

    root = ET.Element("xmeml", version="4")
    seq = _sub(root, "sequence", None)
    seq.set("id", "sequence-1")
    _sub(seq, "name", sequence_name)
    total = max((tl.frames(p.start) + tl.frames(p.clip.duration) for p in tl.placements), default=0)
    _sub(seq, "duration", total)
    _rate(seq, tl)
    _timecode(seq, tl)
    media = _sub(seq, "media")

    def file_element(parent: ET.Element, p: Placement) -> None:
        fid = file_ids[p.clip.path]
        el = _sub(parent, "file")
        el.set("id", fid)
        if fid in defined:
            return
        defined.add(fid)
        _sub(el, "name", p.clip.name)
        _sub(el, "pathurl", path_url(p.clip.path))
        _rate(el, tl)
        _sub(el, "duration", tl.frames(p.clip.duration))
        _timecode(el, tl)
        fm = _sub(el, "media")
        if p.clip.has_video:
            sc = _sub(_sub(fm, "video"), "samplecharacteristics")
            _rate(sc, tl)
            _sub(sc, "width", p.clip.width)
            _sub(sc, "height", p.clip.height)
            _sub(sc, "anamorphic", "FALSE")
            _sub(sc, "pixelaspectratio", "square")
            _sub(sc, "fielddominance", "none")
        if p.clip.has_audio:
            au = _sub(fm, "audio")
            sc = _sub(au, "samplecharacteristics")
            _sub(sc, "depth", 16)
            _sub(sc, "samplerate", p.clip.sample_rate)
            _sub(au, "channelcount", p.clip.channels)

    def links(parent: ET.Element, p: Placement) -> None:
        if p.video_track is None or p.audio_track is None:
            return
        vid, vidx = vid_item[id(p)]
        aid, aidx = aud_item[id(p)]
        for ref, kind, track, idx in (
            (vid, "video", p.video_track + 1, vidx),
            (aid, "audio", p.audio_track + 1, aidx),
        ):
            link = _sub(parent, "link")
            _sub(link, "linkclipref", ref)
            _sub(link, "mediatype", kind)
            _sub(link, "trackindex", track)
            _sub(link, "clipindex", idx)
            if kind == "audio":
                _sub(link, "groupindex", 1)

    def clipitem(track_el: ET.Element, p: Placement, item_id: str, kind: str) -> None:
        item = _sub(track_el, "clipitem")
        item.set("id", item_id)
        _sub(item, "masterclipid", "master" + file_ids[p.clip.path])
        _sub(item, "name", p.clip.name)
        _sub(item, "enabled", "TRUE")
        dur = tl.frames(p.clip.duration)
        _sub(item, "duration", dur)
        _rate(item, tl)
        start = tl.frames(p.start)
        _sub(item, "start", start)
        _sub(item, "end", start + dur)
        _sub(item, "in", 0)
        _sub(item, "out", dur)
        file_element(item, p)
        if kind == "audio":
            src = _sub(item, "sourcetrack")
            _sub(src, "mediatype", "audio")
            _sub(src, "trackindex", 1)
        links(item, p)

    video = _sub(media, "video")
    fmt = _sub(_sub(video, "format"), "samplecharacteristics")
    _rate(fmt, tl)
    _sub(fmt, "width", tl.width)
    _sub(fmt, "height", tl.height)
    _sub(fmt, "anamorphic", "FALSE")
    _sub(fmt, "pixelaspectratio", "square")
    _sub(fmt, "fielddominance", "none")
    for lst in video_by_track:
        track = _sub(video, "track")
        for p in lst:
            clipitem(track, p, vid_item[id(p)][0], "video")
        _sub(track, "enabled", "TRUE")
        _sub(track, "locked", "FALSE")

    audio = _sub(media, "audio")
    _sub(audio, "numOutputChannels", 2)
    afmt = _sub(_sub(audio, "format"), "samplecharacteristics")
    _sub(afmt, "depth", 16)
    _sub(afmt, "samplerate", 48000)
    for lst in audio_by_track:
        track = _sub(audio, "track")
        stereo = any(p.clip.channels >= 2 for p in lst)
        track.set("premiereTrackType", "Stereo" if stereo else "Mono")
        for p in lst:
            clipitem(track, p, aud_item[id(p)][0], "audio")
        _sub(track, "enabled", "TRUE")
        _sub(track, "locked", "FALSE")

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        f.write(body)
        f.write("\n")
