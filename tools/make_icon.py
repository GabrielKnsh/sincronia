"""Desenha o ícone do aplicativo (sincronia/resources/icon.png, 1024×1024).

Uso: python tools/make_icon.py
"""

import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "sincronia", "resources", "icon.png")

app = QGuiApplication(sys.argv)
size = 1024
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

# fundo no formato dos ícones do macOS (quadrado arredondado com margem)
body = QRectF(100, 100, 824, 824)
path = QPainterPath()
path.addRoundedRect(body, 185, 185)
grad = QLinearGradient(body.topLeft(), body.bottomRight())
grad.setColorAt(0, QColor("#2B2B30"))
grad.setColorAt(1, QColor("#121214"))
p.fillPath(path, grad)
p.setPen(QPen(QColor(255, 255, 255, 30), 4))
p.drawPath(path)

# três formas de onda (câmeras e gravador), alinhadas por uma linha de sincronia
waves = [("#0A84FF", 330, 0.0), ("#30D158", 512, 1.3), ("#FF9F0A", 694, 2.6)]
import math  # noqa: E402
for color, y, phase in waves:
    pen = QPen(QColor(color), 26, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    for k in range(13):
        x = 230 + k * 47
        a = 16 + 54 * abs(math.sin(k * 0.9 + phase)) * (1 - abs(k - 6) / 9)
        p.drawLine(QPointF(x, y - a), QPointF(x, y + a))

p.setPen(QPen(QColor("#FFFFFF"), 14, Qt.SolidLine, Qt.RoundCap))
p.drawLine(QPointF(512, 225), QPointF(512, 799))
p.setBrush(QColor("#FFFFFF"))
p.setPen(Qt.NoPen)
p.drawEllipse(QPointF(512, 225), 24, 24)
p.end()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT)
print("Ícone salvo em", OUT)
