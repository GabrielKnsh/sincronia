"""Encontra o deslocamento de tempo entre gravações comparando o som.

Duas etapas:
1. Grosseira: cada áudio vira um "envelope de ataques" (100 valores por
   segundo que marcam quando surgem sons novos: sílabas, batidas, palmas),
   medido em 24 faixas de frequência para resistir a chiado e eco.
   Envelopes de microfones diferentes se parecem mesmo quando o timbre muda,
   e a correlação entre eles indica o alinhamento com precisão de 10 ms.
2. Fina: perto desse ponto, compara as próprias ondas sonoras (GCC-PHAT)
   para chegar à precisão de uma amostra.

Depois, os pares encontrados são juntados em grupos (como as tomadas de uma
filmagem), sempre usando primeiro as ligações mais confiáveis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from .media import ANALYSIS_RATE, MediaError, MediaInfo, load_audio

HOP = 80                         # 10 ms por quadro do envelope
NFFT = 256
ENV_RATE = ANALYSIS_RATE / HOP   # 100 quadros por segundo
BANDS = 24
NOISE_FLOOR = 0.1                # piso de energia, relativo à média de cada faixa

MIN_OVERLAP_SEC = 5.0            # sobreposição mínima exigida (ou 80% do clipe mais curto)
MIN_CONFIDENCE = 9.0             # quantos "desvios" o pico precisa se destacar do ruído
MIN_UNIQUENESS = 3.0             # distância mínima até o segundo melhor candidato
WEAK_CONFIDENCE = 6.0            # pistas fracas: só valem se duas ou mais concordarem
WEAK_UNIQUENESS = 1.5
AGREEMENT_TOLERANCE = 0.05       # segundos
REFINE_WINDOW = 800              # ajuste fino de até ±100 ms
REFINE_SEGMENT_SEC = 30.0
DRIFT_MIN_SEC = 180.0            # só mede deriva de relógio em sobreposições de 3 min ou mais
DRIFT_MAX_RATE = 300e-6          # acima disso a medição é tida como erro, não deriva real
DEVICE_OVERLAP_TOLERANCE = 1.0   # dois clipes da mesma câmera não podem se sobrepor

Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


@dataclass
class Match:
    a: int
    b: int
    offset: float        # início de b menos início de a, em segundos
    confidence: float
    overlap: float       # segundos
    drift: float = 0.0   # deriva de relógio: segundos de desvio por segundo de gravação
    strong: bool = True  # forte o bastante para valer sozinho

    @property
    def drift_ms(self) -> float:
        """Desvio acumulado ao longo da sobreposição, em milissegundos."""
        return abs(self.drift) * self.overlap * 1000


@dataclass
class SyncResult:
    groups: list[list[tuple[int, float]]]   # (índice do clipe, posição em segundos)
    unmatched: list[int]
    matches: list[Match]                    # todos os pares encontrados
    accepted: list[Match]                   # os pares usados para montar os grupos
    errors: dict[int, str]

    def drift_ms(self, clip_index: int) -> float:
        """Maior desvio de relógio medido entre este clipe e os vizinhos de grupo."""
        return max((m.drift_ms for m in self.accepted if clip_index in (m.a, m.b)), default=0.0)


def _next_pow2(n: int) -> int:
    return 1 << max(0, int(n - 1).bit_length())


def _band_edges() -> np.ndarray:
    # faixas em escala logarítmica de 100 Hz a 3,8 kHz (ignora ronco e vento)
    edges = np.round(np.geomspace(100, 3800, BANDS + 1) / (ANALYSIS_RATE / NFFT)).astype(int)
    return np.maximum(edges, np.arange(len(edges)) + edges[0])   # faixas não vazias


def onset_envelope(audio: np.ndarray) -> np.ndarray:
    """Envelope de ataques (fluxo espectral por faixas), normalizado: média 0, desvio 1."""
    if len(audio) < NFFT + HOP:
        return np.zeros(0, np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(audio, NFFT)[::HOP]
    window = (np.hanning(NFFT) / 32768.0).astype(np.float32)
    edges = _band_edges()

    energy = np.empty((frames.shape[0], BANDS), np.float32)
    chunk = 8192
    for s in range(0, frames.shape[0], chunk):
        power = np.abs(np.fft.rfft(frames[s:s + chunk] * window, axis=1)) ** 2
        energy[s:s + len(power)] = np.add.reduceat(power, edges[:-1], axis=1)

    # O piso por faixa faz o chiado constante de um microfone ruim pesar pouco.
    floor = NOISE_FLOOR * energy.mean(axis=0, keepdims=True) + 1e-12
    log_energy = np.log(energy + floor)
    flux = np.maximum(np.diff(log_energy, axis=0, prepend=log_energy[:1]), 0).sum(axis=1)

    k = int(ENV_RATE)   # tira a tendência lenta (1 s) para sobrarem os ataques
    env = flux - np.convolve(flux, np.ones(k, np.float32) / k, mode="same")
    std = env.std()
    if std < 1e-9:
        return np.zeros_like(env)
    return ((env - env.mean()) / std).astype(np.float32)


def coarse_offset(ea: np.ndarray, eb: np.ndarray):
    """Retorna (atraso em quadros, confiança, unicidade, sobreposição) ou None."""
    n, m = len(ea), len(eb)
    shorter = min(n, m)
    if shorter < ENV_RATE:   # menos de 1 s de áudio
        return None
    size = _next_pow2(n + m - 1)
    c = np.fft.irfft(np.fft.rfft(ea, size) * np.conj(np.fft.rfft(eb, size)), size)
    # c[d] = soma de ea[j + d] * eb[j]: b começa d quadros depois de a
    lags = np.arange(-(m - 1), n)
    vals = np.concatenate([c[size - (m - 1):], c[:n]]) if m > 1 else c[:n]
    overlap = np.minimum(n, lags + m) - np.maximum(0, lags)

    min_overlap = min(MIN_OVERLAP_SEC * ENV_RATE, 0.8 * shorter)
    valid = overlap >= min_overlap
    if valid.sum() < 10:
        return None
    lags, overlap = lags[valid], overlap[valid]
    score = vals[valid] / np.sqrt(overlap)

    best = int(np.argmax(score))
    median = float(np.median(score))
    spread = float(np.median(np.abs(score - median))) * 1.4826 + 1e-9
    confidence = (score[best] - median) / spread

    # segundo melhor candidato, longe (>1 s) do primeiro
    far = np.abs(lags - lags[best]) > ENV_RATE
    second = float(score[far].max()) if far.any() else median
    uniqueness = (score[best] - second) / spread
    return int(lags[best]), confidence, uniqueness, int(overlap[best])


def _refine_segment(xa, xb, delay: int, lo: int, hi: int):
    """Atraso exato medido no trecho com mais som entre lo e hi (amostras de a).
    Retorna (atraso, centro do trecho) ou None se o trecho for curto demais."""
    w = REFINE_WINDOW
    lo = max(lo, max(0, delay) + w)
    hi = min(hi, min(len(xa), delay + len(xb)) - w)
    if hi - lo < ANALYSIS_RATE:
        return None

    seg = int(REFINE_SEGMENT_SEC * ANALYSIS_RATE)
    if hi - lo > seg:
        starts = np.linspace(lo, hi - seg, 6).astype(int)
        energy = [float(np.mean(np.abs(xa[s:s + seg:16].astype(np.float32)))) for s in starts]
        lo = int(starts[int(np.argmax(energy))])
        hi = lo + seg

    a = np.diff(xa[lo:hi].astype(np.float32))
    b = np.diff(xb[lo - delay - w:hi - delay + w].astype(np.float32))
    size = _next_pow2(len(a) + len(b))
    spec = np.conj(np.fft.rfft(a, size)) * np.fft.rfft(b, size)
    spec /= np.abs(spec) ** 0.8 + 1e-12     # GCC-PHAT parcial: realça o alinhamento
    r = np.fft.irfft(spec, size)[:2 * w + 1]
    return delay + (w - int(np.argmax(r))), (lo + hi) // 2


def refine_offset(xa: np.ndarray, xb: np.ndarray, lag_frames: int) -> tuple[int, float]:
    """Ajusta o atraso para a precisão de uma amostra.

    Em sobreposições longas, mede no começo e no fim: a diferença revela a
    deriva entre os relógios dos aparelhos, e o atraso devolvido é o do meio
    (o erro fica dividido entre as duas pontas).
    Retorna (atraso em amostras, deriva em segundos por segundo)."""
    delay = lag_frames * HOP
    start, end = max(0, delay), min(len(xa), delay + len(xb))
    span = end - start
    if span >= DRIFT_MIN_SEC * ANALYSIS_RATE:
        third = span // 3
        early = _refine_segment(xa, xb, delay, start, start + third)
        late = _refine_segment(xa, xb, delay, end - third, end)
        if early and late and late[1] > early[1]:
            rate = (late[0] - early[0]) / (late[1] - early[1])
            if abs(rate) <= DRIFT_MAX_RATE:
                middle = (start + end) / 2
                return int(round(early[0] + rate * (middle - early[1]))), rate
    single = _refine_segment(xa, xb, delay, start, end)
    return (single[0] if single else delay), 0.0


def synchronize(clips: Sequence[MediaInfo], progress: Progress | None = None,
                is_cancelled: Callable[[], bool] | None = None) -> SyncResult:
    def report(frac: float, msg: str):
        if is_cancelled and is_cancelled():
            raise Cancelled()
        if progress:
            progress(frac, msg)

    n = len(clips)
    envelopes: list[np.ndarray | None] = [None] * n
    errors: dict[int, str] = {}

    for i, clip in enumerate(clips):
        report(0.4 * i / max(n, 1), f"Lendo áudio: {clip.name}")
        try:
            audio = clip.audio if clip.audio is not None else load_audio(clip)
            envelopes[i] = onset_envelope(audio)
        except MediaError as e:
            errors[i] = str(e)

    use_devices = len({c.device for c in clips}) > 1
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)
             if envelopes[i] is not None and envelopes[j] is not None
             and not (use_devices and clips[i].device == clips[j].device)]

    matches: list[Match] = []
    for k, (i, j) in enumerate(pairs):
        report(0.4 + 0.6 * k / max(len(pairs), 1),
               f"Comparando {clips[i].name} × {clips[j].name}")
        found = coarse_offset(envelopes[i], envelopes[j])
        if not found:
            continue
        lag, confidence, uniqueness, overlap = found
        if confidence < WEAK_CONFIDENCE or uniqueness < WEAK_UNIQUENESS:
            continue
        strong = confidence >= MIN_CONFIDENCE and uniqueness >= MIN_UNIQUENESS
        samples, drift = refine_offset(clips[i].audio, clips[j].audio, lag)
        matches.append(Match(i, j, samples / ANALYSIS_RATE, confidence,
                             overlap / ENV_RATE, drift, strong))

    report(1.0, "Montando grupos")
    groups, unmatched, accepted = _build_groups(clips, matches, use_devices)
    return SyncResult(groups, unmatched, matches, accepted, errors)


def _conflict(clips: Sequence[MediaInfo], a: dict[int, float], b: dict[int, float]) -> bool:
    """Verdadeiro se dois clipes da mesma câmera ficariam sobrepostos."""
    for i, pi in a.items():
        for j, pj in b.items():
            if clips[i].device != clips[j].device:
                continue
            overlap = min(pi + clips[i].duration, pj + clips[j].duration) - max(pi, pj)
            if overlap > DEVICE_OVERLAP_TOLERANCE:
                return True
    return False


def _build_groups(clips, matches, use_devices):
    component = list(range(len(clips)))
    members: dict[int, dict[int, float]] = {i: {i: 0.0} for i in range(len(clips))}
    accepted = []

    def merge(ca, cb, shift, m) -> bool:
        moved = {k: v + shift for k, v in members[cb].items()}
        if use_devices and _conflict(clips, members[ca], moved):
            return False
        members[ca].update(moved)
        for k in moved:
            component[k] = ca
        del members[cb]
        accepted.append(m)
        return True

    # 1ª passada: só as ligações fortes, da mais confiável para a menos.
    for m in sorted((m for m in matches if m.strong), key=lambda m: -m.confidence):
        ca, cb = component[m.a], component[m.b]
        if ca != cb:
            merge(ca, cb, members[ca][m.a] + m.offset - members[cb][m.b], m)

    # 2ª passada: um clipe ainda sozinho entra num grupo se pelo menos duas
    # ligações fracas, com clipes diferentes desse grupo, apontam para o mesmo lugar.
    weak = [m for m in matches if not m.strong]
    changed = True
    while changed:
        changed = False
        for i in [r for r, pos in members.items() if len(pos) == 1]:
            votes: dict[int, list[tuple[float, Match]]] = {}
            for m in weak:
                if i not in (m.a, m.b):
                    continue
                j = m.b if i == m.a else m.a
                root = component[j]
                if root == component[i]:
                    continue
                pos = members[root][j] + (m.offset if i == m.b else -m.offset)
                votes.setdefault(root, []).append((pos, m))
            for root, candidates in votes.items():
                candidates.sort(key=lambda c: -c[1].confidence)
                best_pos, best = candidates[0]
                agreeing = {(c[1].a, c[1].b) for c in candidates
                            if abs(c[0] - best_pos) <= AGREEMENT_TOLERANCE}
                if len(agreeing) >= 2 and merge(root, i, best_pos, best):
                    changed = True
                    break

    groups, unmatched = [], []
    for root in sorted(members, key=lambda r: min(members[r])):
        positions = members[root]
        if len(positions) == 1:
            unmatched.append(root)
            continue
        first = min(positions.values())
        groups.append(sorted(((k, p - first) for k, p in positions.items()),
                             key=lambda kp: (kp[1], kp[0])))
    return groups, unmatched, accepted
