"""Exporta a linha do tempo como XML (formato Final Cut Pro 7 / xmeml),
que o Premiere Pro importa em Arquivo > Importar.

O Premiere descreve áudio estéreo "explodido": cada canal numa trilha de XML
própria, as duas marcadas como par (currentExplodedTrackIndex 0 e 1). Um estéreo
numa trilha só, sem essa marcação, é descartado na importação e a sequência
chega sem som. Por isso cada trilha lógica de áudio vira uma trilha de XML por
canal, e cada clipe de áudio vira um clipitem por canal.
"""

from __future__ import annotations

import os
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .timeline import Placement, Timeline

# "premiere": estéreo explodido como o próprio Premiere exporta (padrão)
# "fcp7": uma trilha mono por canal, sem atributos do Premiere (formato clássico do FCP 7)
STYLES = ("premiere", "fcp7")


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


@dataclass
class _Item:
    """Um clipitem no XML: o lugar dele (tipo, trilha de XML 1-based, índice na trilha)."""
    id: str
    kind: str          # "video" ou "audio"
    track: int
    index: int
    channel: int = 1   # canal da fonte (sourcetrack) para áudio


def write_premiere_xml(tl: Timeline, out_path: str, sequence_name: str = "Sincronia",
                       style: str = "premiere") -> None:
    if style not in STYLES:
        raise ValueError(f"estilo desconhecido: {style}")

    file_ids: dict[str, str] = {}
    defined: set[str] = set()
    for p in tl.placements:
        file_ids.setdefault(p.clip.path, f"file-{len(file_ids) + 1}")

    video_by_track: list[list[Placement]] = [[] for _ in range(tl.video_tracks)]
    audio_by_track: list[list[Placement]] = [[] for _ in range(tl.audio_tracks)]
    for p in tl.placements:
        if p.video_track is not None:
            video_by_track[p.video_track].append(p)
        if p.audio_track is not None:
            audio_by_track[p.audio_track].append(p)
    for lst in video_by_track + audio_by_track:
        lst.sort(key=lambda p: p.start)

    # Cada trilha lógica de áudio ocupa 1 (mono) ou 2 (estéreo) trilhas de XML.
    lane_channels = [2 if any(p.clip.channels >= 2 for p in lst) else 1 for lst in audio_by_track]
    lane_first_xml_track = []
    n = 1
    for ch in lane_channels:
        lane_first_xml_track.append(n)
        n += ch

    counter = iter(range(1, 1_000_000))
    items: dict[int, list[_Item]] = {}     # id(placement) -> clipitems dele
    for t, lst in enumerate(video_by_track):
        for k, p in enumerate(lst, 1):
            items.setdefault(id(p), []).append(_Item(f"clipitem-{next(counter)}", "video", t + 1, k))
    for t, lst in enumerate(audio_by_track):
        for ch in range(1, lane_channels[t] + 1):
            for k, p in enumerate(lst, 1):
                if ch <= max(1, min(p.clip.channels, 2)):
                    items.setdefault(id(p), []).append(
                        _Item(f"clipitem-{next(counter)}", "audio", lane_first_xml_track[t] + ch - 1, k, ch))

    root = ET.Element("xmeml", version="4")
    seq = _sub(root, "sequence")
    seq.set("id", "sequence-1")
    if style == "premiere":
        seq.set("explodedTracks", "true")
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
        group = items[id(p)]
        if len(group) < 2:
            return
        for it in group:
            link = _sub(parent, "link")
            _sub(link, "linkclipref", it.id)
            _sub(link, "mediatype", it.kind)
            _sub(link, "trackindex", it.track)
            _sub(link, "clipindex", it.index)
            if it.kind == "audio":
                _sub(link, "groupindex", 1)

    def clipitem(track_el: ET.Element, p: Placement, it: _Item) -> None:
        item = _sub(track_el, "clipitem")
        item.set("id", it.id)
        if style == "premiere" and it.kind == "audio":
            item.set("premiereChannelType", "stereo" if p.clip.channels >= 2 else "mono")
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
        if it.kind == "audio":
            src = _sub(item, "sourcetrack")
            _sub(src, "mediatype", "audio")
            _sub(src, "trackindex", it.channel)
        links(item, p)

    def item_for(p: Placement, kind: str, xml_track: int) -> _Item:
        return next(it for it in items[id(p)] if it.kind == kind and it.track == xml_track)

    video = _sub(media, "video")
    fmt = _sub(_sub(video, "format"), "samplecharacteristics")
    _rate(fmt, tl)
    _sub(fmt, "width", tl.width)
    _sub(fmt, "height", tl.height)
    _sub(fmt, "anamorphic", "FALSE")
    _sub(fmt, "pixelaspectratio", "square")
    _sub(fmt, "fielddominance", "none")
    for t, lst in enumerate(video_by_track):
        track = _sub(video, "track")
        for p in lst:
            clipitem(track, p, item_for(p, "video", t + 1))
        _sub(track, "enabled", "TRUE")
        _sub(track, "locked", "FALSE")

    audio = _sub(media, "audio")
    _sub(audio, "numOutputChannels", 2)
    afmt = _sub(_sub(audio, "format"), "samplecharacteristics")
    _sub(afmt, "depth", 16)
    _sub(afmt, "samplerate", 48000)
    if style == "premiere":
        outputs = _sub(audio, "outputs")
        for k in (1, 2):
            group = _sub(outputs, "group")
            _sub(group, "index", k)
            _sub(group, "numchannels", 1)
            _sub(group, "downmix", 0)
            _sub(_sub(group, "channel"), "index", k)

    for t, lst in enumerate(audio_by_track):
        channels = lane_channels[t]
        for ch in range(1, channels + 1):
            xml_track = lane_first_xml_track[t] + ch - 1
            track = _sub(audio, "track")
            if style == "premiere":
                track.set("currentExplodedTrackIndex", str(ch - 1))
                track.set("totalExplodedTrackCount", str(channels))
                track.set("premiereTrackType", "Stereo" if channels == 2 else "Mono")
            for p in lst:
                it = next((i for i in items[id(p)] if i.kind == "audio" and i.track == xml_track), None)
                if it is not None:
                    clipitem(track, p, it)
            _sub(track, "enabled", "TRUE")
            _sub(track, "locked", "FALSE")
            if channels == 2:
                _sub(track, "outputchannelindex", ch)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        f.write(body)
        f.write("\n")
