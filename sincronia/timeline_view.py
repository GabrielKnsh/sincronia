"""Linha do tempo desenhada à mão (trilhas, clipes e formas de onda) e área de soltar arquivos."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QToolTip, QWidget

from .media import PEAKS_PER_SECOND
from .style import ACCENT, BG, ORANGE, RED, SURFACE, TEXT, TEXT_2, TEXT_3, TOOLBAR

PENDING, SYNCED, UNMATCHED = "pending", "synced", "unmatched"


@dataclass
class ClipBar:
    start: float
    duration: float
    name: str
    color: QColor
    state: str = PENDING
    peaks: np.ndarray | None = None
    tooltip: str = ""
    warning: bool = False


@dataclass
class Row:
    label: str
    detail: str
    color: QColor
    clips: list[ClipBar] = field(default_factory=list)


@dataclass
class Band:
    start: float
    end: float
    label: str
    warning: bool = False


def _font(size: float, weight=QFont.Normal) -> QFont:
    f = QFont()
    f.setPixelSize(int(size))
    f.setWeight(weight)
    return f


def time_label(seconds: float, step: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(int(round(seconds)), 3600)
    m, s = divmod(rem, 60)
    if step < 1:
        return f"{m + 60 * h}:{seconds % 60:04.1f}"
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class TimelineView(QAbstractScrollArea):
    LABEL_W = 168
    RULER_H = 42
    ROW_H = 52
    GAP = 8
    MAX_PPS = 400.0   # pixels por segundo no zoom máximo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[Row] = []
        self.bands: list[Band] = []
        self.total = 1.0
        self.pps = 1.0
        self._fit = True
        self.viewport().setMouseTracking(True)
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.horizontalScrollBar().setSingleStep(24)
        self.verticalScrollBar().setSingleStep(24)

    # ---------- conteúdo e zoom ----------

    def set_content(self, rows: list[Row], bands: list[Band], total: float) -> None:
        self.rows, self.bands, self.total = rows, bands, max(total, 1.0)
        self.horizontalScrollBar().setValue(0)
        self.fit()

    def _min_pps(self) -> float:
        width = max(100, self.viewport().width() - self.LABEL_W - 24)
        return width / self.total

    def fit(self) -> None:
        self._fit = True
        self.pps = self._min_pps()
        self._update_bars()

    def zoom_by(self, factor: float, anchor_x: float | None = None) -> None:
        if anchor_x is None:
            anchor_x = self.LABEL_W + (self.viewport().width() - self.LABEL_W) / 2
        anchor_x = max(anchor_x, self.LABEL_W)
        t = self._x_to_time(anchor_x)
        low = self._min_pps()
        self.pps = min(max(self.pps * factor, low), max(self.MAX_PPS, low))
        self._fit = self.pps <= low * 1.0001
        self._update_bars()
        self.horizontalScrollBar().setValue(int(t * self.pps - (anchor_x - self.LABEL_W)))

    def _x_to_time(self, x: float) -> float:
        return (x - self.LABEL_W + self.horizontalScrollBar().value()) / self.pps

    def _content_height(self) -> int:
        return self.RULER_H + self.GAP + len(self.rows) * (self.ROW_H + self.GAP)

    def _update_bars(self) -> None:
        vw = self.viewport().width() - self.LABEL_W
        h = self.horizontalScrollBar()
        h.setRange(0, max(0, int(self.total * self.pps + 24 - vw)))
        h.setPageStep(max(1, vw))
        v = self.verticalScrollBar()
        v.setRange(0, max(0, self._content_height() - self.viewport().height()))
        v.setPageStep(max(1, self.viewport().height()))
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.fit()
        else:
            self._update_bars()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    def wheelEvent(self, event):
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            self.zoom_by(1.0015 ** event.angleDelta().y(), event.position().x())
            event.accept()
            return
        delta = event.pixelDelta()
        if delta.isNull():
            delta = event.angleDelta()
        dx, dy = delta.x(), delta.y()
        if event.modifiers() & Qt.ShiftModifier:
            dx, dy = dy, 0
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - dx)
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - dy)
        event.accept()

    def viewportEvent(self, event):
        # pinça no trackpad do Mac
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_by(1 + event.value(), event.position().x())
            return True
        return super().viewportEvent(event)

    # ---------- desenho ----------

    def _row_top(self, i: int) -> float:
        return self.RULER_H + self.GAP + i * (self.ROW_H + self.GAP) - self.verticalScrollBar().value()

    def _clip_rect(self, row: int, clip: ClipBar) -> QRectF:
        x = self.LABEL_W - self.horizontalScrollBar().value() + clip.start * self.pps
        return QRectF(x, self._row_top(row), max(3.0, clip.duration * self.pps), self.ROW_H)

    def paintEvent(self, event):
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, w, h, QColor(BG))
        origin = self.LABEL_W - self.horizontalScrollBar().value()

        # faixas das trilhas
        for i in range(len(self.rows)):
            y = self._row_top(i) - self.GAP / 2
            if i % 2:
                p.fillRect(QRectF(self.LABEL_W, y, w, self.ROW_H + self.GAP), QColor(255, 255, 255, 6))

        # fundo dos grupos sincronizados
        for band in self.bands:
            x = origin + band.start * self.pps
            r = QRectF(x, self.RULER_H, (band.end - band.start) * self.pps, h)
            color = QColor(RED if band.warning else ACCENT)
            color.setAlpha(14)
            p.fillRect(r, color)
            color.setAlpha(70)
            p.setPen(QPen(color, 1))
            p.drawLine(QLineF(r.left(), r.top(), r.left(), h))

        p.save()
        p.setClipRect(QRectF(self.LABEL_W, self.RULER_H, w, h))
        for i, row in enumerate(self.rows):
            for clip in row.clips:
                r = self._clip_rect(i, clip)
                if r.right() < self.LABEL_W or r.left() > w or r.bottom() < self.RULER_H or r.top() > h:
                    continue
                self._draw_clip(p, r, clip, w)
        p.restore()

        self._draw_ruler(p, w, origin)
        self._draw_labels(p, h)
        p.end()

    def _draw_clip(self, p: QPainter, r: QRectF, c: ClipBar, view_w: int) -> None:
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        base = QColor(c.color)
        if c.state == UNMATCHED:
            fill, border, wave = QColor("#3A3A3C"), QColor(RED), QColor(255, 255, 255, 90)
        elif c.state == PENDING:
            fill = QColor(base)
            fill.setAlpha(70)
            border = QColor(base)
            border.setAlpha(150)
            wave = QColor(base).lighter(140)
            wave.setAlpha(170)
        else:
            fill = QColor(base).darker(135)
            border = QColor(base).lighter(115)
            wave = QColor(255, 255, 255, 170)
        p.fillPath(path, fill)

        if c.peaks is not None and len(c.peaks) and r.width() > 8:
            p.save()
            p.setClipPath(path)
            top, height = r.top() + 18, r.height() - 22
            mid = top + height / 2
            x0 = max(int(r.left()), self.LABEL_W)
            x1 = min(int(r.right()), view_w)
            if x1 > x0:
                cols = np.arange(x0, x1, dtype=np.float64)
                idx = ((cols - r.left()) / self.pps * PEAKS_PER_SECOND).astype(np.int64)
                idx = np.clip(idx, 0, len(c.peaks) - 1)
                values = np.maximum.reduceat(c.peaks, idx) if len(idx) > 1 else c.peaks[idx]
                amp = values * (height / 2)
                p.setPen(QPen(wave, 1))
                p.drawLines([QLineF(x, mid - a, x, mid + a) for x, a in zip(cols + 0.5, amp) if a > 0.3])
            p.restore()

        p.setPen(QPen(border, 1))
        p.drawPath(path)

        if r.width() > 34:
            p.setFont(_font(11, QFont.DemiBold))
            p.setPen(QColor(TEXT if c.state != UNMATCHED else TEXT_2))
            left = max(r.left(), self.LABEL_W) + 7
            text_r = QRectF(left, r.top() + 3, r.right() - left - (20 if c.warning else 6), 14)
            if text_r.width() > 12:
                name = p.fontMetrics().elidedText(c.name, Qt.ElideRight, int(text_r.width()))
                p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter, name)
        if c.warning and r.width() > 22:
            p.setPen(QColor(ORANGE))
            p.setFont(_font(12, QFont.Bold))
            p.drawText(QRectF(r.right() - 20, r.top() + 2, 16, 16), Qt.AlignCenter, "⚠")

    def _draw_ruler(self, p: QPainter, w: int, origin: float) -> None:
        p.fillRect(QRectF(0, 0, w, self.RULER_H), QColor(SURFACE))
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawLine(QLineF(0, self.RULER_H - 0.5, w, self.RULER_H - 0.5))

        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)
                     if s * self.pps >= 90), 7200)
        t = math.floor(self._x_to_time(self.LABEL_W) / step) * step
        p.setFont(_font(10))
        while True:
            x = origin + t * self.pps
            if x > w:
                break
            if x >= self.LABEL_W - 1:
                p.setPen(QPen(QColor(TEXT_3), 1))
                p.drawLine(QLineF(x, self.RULER_H - 9, x, self.RULER_H - 1))
                for k in range(1, 5):
                    xm = x + k * step * self.pps / 5
                    p.drawLine(QLineF(xm, self.RULER_H - 4, xm, self.RULER_H - 1))
                p.setPen(QColor(TEXT_2))
                p.drawText(QPointF(x + 4, 13), time_label(t, step))
            t += step

        p.setFont(_font(10, QFont.DemiBold))
        for band in self.bands:
            x = max(origin + band.start * self.pps, self.LABEL_W) + 4
            right = origin + band.end * self.pps
            if right - x > 40:
                p.setPen(QColor(RED if band.warning else ACCENT))
                text = p.fontMetrics().elidedText(band.label, Qt.ElideRight, int(right - x - 4))
                p.drawText(QRectF(x, 18, right - x - 4, 12), Qt.AlignLeft | Qt.AlignVCenter, text)

    def _draw_labels(self, p: QPainter, h: int) -> None:
        p.fillRect(QRectF(0, 0, self.LABEL_W, h), QColor(SURFACE))
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawLine(QLineF(self.LABEL_W - 0.5, 0, self.LABEL_W - 0.5, h))
        p.fillRect(QRectF(0, 0, self.LABEL_W - 1, self.RULER_H - 1), QColor(TOOLBAR))
        p.setPen(QColor(TEXT_2))
        p.setFont(_font(10, QFont.DemiBold))
        p.drawText(QRectF(14, 0, self.LABEL_W, self.RULER_H), Qt.AlignVCenter, "TRILHAS")

        p.save()
        p.setClipRect(QRectF(0, self.RULER_H, self.LABEL_W, h))
        for i, row in enumerate(self.rows):
            y = self._row_top(i)
            if y + self.ROW_H < self.RULER_H or y > h:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(row.color)
            p.drawRoundedRect(QRectF(14, y + 13, 4, self.ROW_H - 26), 2, 2)
            p.setPen(QColor(TEXT))
            p.setFont(_font(13, QFont.DemiBold))
            label = p.fontMetrics().elidedText(row.label, Qt.ElideRight, self.LABEL_W - 40)
            p.drawText(QRectF(28, y + 8, self.LABEL_W - 36, 18), Qt.AlignVCenter, label)
            p.setPen(QColor(TEXT_2))
            p.setFont(_font(11))
            p.drawText(QRectF(28, y + 26, self.LABEL_W - 36, 16), Qt.AlignVCenter, row.detail)
        p.restore()

    # ---------- dicas ao passar o mouse ----------

    def mouseMoveEvent(self, event):
        pos = event.position()
        if pos.x() > self.LABEL_W and pos.y() > self.RULER_H:
            for i, row in enumerate(self.rows):
                for clip in row.clips:
                    if clip.tooltip and self._clip_rect(i, clip).contains(pos):
                        QToolTip.showText(event.globalPosition().toPoint(), clip.tooltip, self.viewport())
                        return
        QToolTip.hideText()


class DropZone(QWidget):
    """Tela inicial: um grande "solte aqui", como no PluralEyes."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = False
        self._drag = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(360, 300)

    def set_drag_active(self, active: bool) -> None:
        self._drag = active
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(BG))
        active = self._drag or self._hover

        box = QRectF(0, 0, min(460, self.width() - 60), min(300, self.height() - 60))
        box.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        if self._drag:
            fill = QColor(ACCENT)
            fill.setAlpha(28)
            p.fillPath(self._rounded(box, 20), fill)
        pen = QPen(QColor(ACCENT if active else "#48484A"), 2, Qt.DashLine)
        pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 20, 20)

        c = QPointF(box.center().x(), box.top() + 82)
        circle = QColor(ACCENT)
        circle.setAlpha(55 if active else 35)
        p.setPen(Qt.NoPen)
        p.setBrush(circle)
        p.drawEllipse(c, 34, 34)
        arrow = QPen(QColor(ACCENT), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(arrow)
        p.drawLine(QLineF(c.x(), c.y() - 15, c.x(), c.y() + 13))
        p.drawPolyline([QPointF(c.x() - 11, c.y() + 2), QPointF(c.x(), c.y() + 13),
                        QPointF(c.x() + 11, c.y() + 2)])

        p.setPen(QColor(TEXT))
        p.setFont(_font(26, QFont.Bold))
        p.drawText(QRectF(box.left(), box.top() + 132, box.width(), 36), Qt.AlignCenter,
                   "Solte aqui")
        p.setPen(QColor(TEXT_2))
        p.setFont(_font(14))
        p.drawText(QRectF(box.left(), box.top() + 170, box.width(), 22), Qt.AlignCenter,
                   "pastas ou arquivos das câmeras e gravadores")
        p.setPen(QColor(ACCENT))
        p.setFont(_font(13, QFont.Medium))
        p.drawText(QRectF(box.left(), box.top() + 206, box.width(), 22), Qt.AlignCenter,
                   "ou clique para escolher…")
        p.end()

    @staticmethod
    def _rounded(r: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        return path
