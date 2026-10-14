"""Uso: python -m sincronia.cli PASTA_OU_ARQUIVO [...] -o saida.xml"""

from __future__ import annotations

import argparse
import os
import sys

from .media import MediaError, is_media_file, probe
from .premiere import write_premiere_xml
from .sync import synchronize
from .timeline import build_timeline


def collect(paths: list[str]) -> list[str]:
    files = []
    for path in paths:
        if os.path.isdir(path):
            for folder, _, names in os.walk(path):
                files += [os.path.join(folder, n) for n in sorted(names) if is_media_file(n)]
        else:
            files.append(path)
    return files


def format_time(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    return f"{sign}{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{seconds % 60:06.3f}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sincroniza clipes pelo áudio.")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("-o", "--output", help="arquivo XML para o Premiere")
    args = parser.parse_args(argv)

    clips = []
    for path in collect(args.paths):
        try:
            clips.append(probe(path))
        except MediaError as e:
            print(f"Ignorado: {e}", file=sys.stderr)

    result = synchronize(clips, progress=lambda f, m: print(f"[{f:4.0%}] {m}", file=sys.stderr))
    for g, group in enumerate(result.groups, 1):
        print(f"Grupo {g}:")
        for idx, pos in group:
            print(f"  {format_time(pos)}  {clips[idx].device}/{clips[idx].name}")
    for idx in result.unmatched:
        print(f"Não sincronizado: {clips[idx].device}/{clips[idx].name}")
    for idx, err in result.errors.items():
        print(f"Erro: {err}")

    if args.output:
        write_premiere_xml(build_timeline(clips, result), args.output)
        print(f"XML salvo em {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
