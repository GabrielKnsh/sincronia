"""Janela principal do Sincronia."""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QStackedWidget, QToolBar, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .cli import collect, format_time
from .media import MediaError, MediaInfo, load_audio, probe
from .premiere import write_premiere_xml
from .style import GREEN, ORANGE, RED, apply_theme, device_color
from .sync import Cancelled, SyncResult, synchronize
from .timeline import build_timeline
from .timeline_view import PENDING, SYNCED, UNMATCHED, Band, ClipBar, DropZone, Row, TimelineView

CLIP_ROLE = Qt.UserRole + 1
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icon.png")
PREVIEW_GAP = 2.0   # espaço entre clipes antes de sincronizar


class Task(QThread):
    """Roda uma função demorada fora da janela, para ela não travar."""
    progress = Signal(float, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit, self.isInterruptionRequested)
        except Cancelled:
            self.failed.emit("")
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.finished_ok.emit(result)


def _import_files(paths):
    def work(progress, is_cancelled):
        clips, errors = [], []
        for k, path in enumerate(paths):
            if is_cancelled():
                raise Cancelled()
            progress(k / len(paths), f"Importando {os.path.basename(path)} ({k + 1} de {len(paths)})")
            try:
                info = probe(path)
                if not info.has_audio:
                    errors.append(f"{info.name}: não tem áudio")
                    continue
                load_audio(info)
                clips.append(info)
            except MediaError as e:
                errors.append(str(e))
        return clips, errors
    return work


def _dot_icon(color: QColor) -> QIcon:
    pix = QPixmap(24, 24)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(6, 6, 12, 12)
    p.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sincronia")
        self.resize(1240, 760)
        self.setMinimumSize(820, 480)
        self.setAcceptDrops(True)

        self.clips: list[MediaInfo] = []
        self.result: SyncResult | None = None
        self.synced_clips: list[MediaInfo] = []
        self._synced_index: dict[int, int] = {}
        self.task: Task | None = None

        self._build_toolbar()
        self._build_body()
        self._build_menus()
        self._refresh()

    # ---------- montagem da janela ----------

    def _build_toolbar(self):
        bar = QToolBar("Ações")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.setUnifiedTitleAndToolBarOnMac(True)

        def spacer():
            w = QWidget()
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            return w

        self.add_btn = QPushButton("Adicionar Mídia…")
        self.sync_btn = QPushButton("Sincronizar")
        self.export_btn = QPushButton("Exportar para Premiere…")
        bar.addWidget(spacer())
        for b in (self.add_btn, self.sync_btn, self.export_btn):
            b.setMinimumWidth(180)
            b.setCursor(Qt.PointingHandCursor)
            bar.addWidget(b)
        bar.addWidget(spacer())

        self.add_btn.clicked.connect(self._choose_files)
        self.sync_btn.clicked.connect(self._synchronize)
        self.export_btn.clicked.connect(self._export)

    def _build_body(self):
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        # barra lateral de mídia
        sidebar = QWidget(objectName="sidebar")
        sidebar.setMinimumWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        side.addWidget(QLabel("MÍDIA", objectName="sidebarTitle"))

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setIndentation(16)
        self.tree.setIconSize(QSize(14, 14))
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.header().resizeSection(1, 26)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        side.addWidget(self.tree, 1)

        footer = QWidget(objectName="sidebarFooter")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(8, 4, 10, 4)
        foot.setSpacing(2)
        self.plus_btn = QToolButton(text="+")
        self.plus_btn.setToolTip("Adicionar mídia")
        self.plus_btn.setPopupMode(QToolButton.InstantPopup)
        plus_menu = QMenu(self.plus_btn)
        plus_menu.addAction("Adicionar Arquivos…", self._choose_files)
        plus_menu.addAction("Adicionar Pasta…", self._choose_folder)
        self.plus_btn.setMenu(plus_menu)
        self.minus_btn = QToolButton(text="−")
        self.minus_btn.setToolTip("Remover selecionados")
        self.minus_btn.clicked.connect(self._remove_selected)
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #98989D; font-size: 11px;")
        foot.addWidget(self.plus_btn)
        foot.addWidget(self.minus_btn)
        foot.addStretch(1)
        foot.addWidget(self.count_label)
        side.addWidget(footer)

        # área principal: "solte aqui" ou a linha do tempo
        self.stack = QStackedWidget()
        self.drop = DropZone()
        self.drop.clicked.connect(self._choose_files)
        self.timeline = TimelineView()
        self.stack.addWidget(self.drop)
        self.stack.addWidget(self.timeline)

        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, 970])

        # barra de status
        status = QWidget(objectName="statusbar")
        status.setFixedHeight(34)
        row = QHBoxLayout(status)
        row.setContentsMargins(12, 0, 12, 0)
        left = QWidget()
        left.setFixedWidth(230)
        right = QWidget()
        right.setFixedWidth(230)
        right_row = QHBoxLayout(right)
        right_row.setContentsMargins(0, 0, 0, 0)
        right_row.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self._cancel)
        right_row.addWidget(self.progress, 1)
        right_row.addWidget(self.cancel_btn)
        self.status = QLabel(objectName="statusText")
        self.status.setAlignment(Qt.AlignCenter)
        row.addWidget(left)
        row.addWidget(self.status, 1)
        row.addWidget(right)
        layout.addWidget(status)
        self.progress.hide()
        self.cancel_btn.hide()

        for key in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            shortcut = QShortcut(key, self.tree, self._remove_selected)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)

    def _build_menus(self):
        def action(menu, text, slot, shortcut=None, role=None):
            act = QAction(text, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            if role is not None:
                act.setMenuRole(role)
            menu.addAction(act)
            return act

        bar = self.menuBar()
        file_menu = bar.addMenu("Arquivo")
        self.act_add_files = action(file_menu, "Adicionar Arquivos…", self._choose_files, "Ctrl+O")
        self.act_add_folder = action(file_menu, "Adicionar Pasta…", self._choose_folder, "Ctrl+Shift+O")
        file_menu.addSeparator()
        self.act_export = action(file_menu, "Exportar para Premiere…", self._export, "Ctrl+E")
        self.act_include = QAction("Incluir Clipes Não Sincronizados na Exportação", self, checkable=True)
        self.act_include.setChecked(True)
        file_menu.addAction(self.act_include)
        file_menu.addSeparator()
        self.act_clear = action(file_menu, "Remover Toda a Mídia", self._clear)
        file_menu.addSeparator()
        action(file_menu, "Sair", self.close, QKeySequence.Quit, QAction.QuitRole)

        sync_menu = bar.addMenu("Sincronizar")
        self.act_sync = action(sync_menu, "Sincronizar", self._synchronize, "Ctrl+R")

        view_menu = bar.addMenu("Visualizar")
        action(view_menu, "Ajustar à Janela", self.timeline.fit, "Ctrl+0")
        action(view_menu, "Aproximar", lambda: self.timeline.zoom_by(1.6), "Ctrl+=")
        action(view_menu, "Afastar", lambda: self.timeline.zoom_by(1 / 1.6), "Ctrl+-")

        help_menu = bar.addMenu("Ajuda")
        action(help_menu, "Como Usar o Sincronia", self._help)
        action(help_menu, "Sobre o Sincronia", self._about, role=QAction.AboutRole)

    # ---------- estado da interface ----------

    def _set_primary(self, primary: QPushButton | None):
        for b in (self.add_btn, self.sync_btn, self.export_btn):
            b.setProperty("primary", b is primary)
            b.style().unpolish(b)
            b.style().polish(b)

    def _busy(self) -> bool:
        return self.task is not None and self.task.isRunning()

    def _refresh(self):
        busy = self._busy()
        has_clips = bool(self.clips)
        can_sync = len(self.clips) >= 2 and not busy
        can_export = self.result is not None and bool(self.result.groups) and not busy

        self.add_btn.setEnabled(not busy)
        self.sync_btn.setEnabled(can_sync)
        self.export_btn.setEnabled(can_export)
        for act in (self.act_add_files, self.act_add_folder):
            act.setEnabled(not busy)
        self.act_sync.setEnabled(can_sync)
        self.act_export.setEnabled(can_export)
        self.act_clear.setEnabled(has_clips and not busy)
        self.plus_btn.setEnabled(not busy)
        self.minus_btn.setEnabled(has_clips and not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)

        if not has_clips:
            self._set_primary(self.add_btn)
        elif can_export:
            self._set_primary(self.export_btn)
        else:
            self._set_primary(self.sync_btn)

        devices = len({c.device for c in self.clips})
        self.count_label.setText(f"{len(self.clips)} arquivo{'s' if len(self.clips) != 1 else ''}"
                                 if has_clips else "")
        if busy:
            return
        if not has_clips:
            self.status.setText("Aguardando mídia")
        elif self.result is None:
            if len(self.clips) < 2:
                self.status.setText("Adicione pelo menos mais um arquivo")
            else:
                self.status.setText(f"{len(self.clips)} arquivos de {devices} "
                                    f"{'câmeras/gravadores' if devices != 1 else 'câmera/gravador'}"
                                    " · Pronto para sincronizar")
        else:
            synced = sum(len(g) for g in self.result.groups)
            total = len(self.synced_clips)
            text = (f"{synced} de {total} clipes sincronizados em {len(self.result.groups)} "
                    f"grupo{'s' if len(self.result.groups) != 1 else ''}")
            if self.result.unmatched:
                text += f" · {len(self.result.unmatched)} não sincronizado(s)"
            self.status.setText(text if synced else "Nenhum clipe pôde ser sincronizado")

    def _run(self, fn, on_done):
        self.task = Task(fn, self)
        self.task.progress.connect(self._on_progress)
        self.task.finished_ok.connect(on_done)
        self.task.failed.connect(self._on_failed)
        self.task.finished.connect(self._refresh)
        self.task.start()
        self.progress.setValue(0)
        self._refresh()

    def _on_progress(self, frac, message):
        self.progress.setValue(int(frac * 1000))
        self.status.setText(message)

    def _on_failed(self, details):
        if not details:
            return
        box = QMessageBox(QMessageBox.Critical, "Erro", "Algo deu errado.", parent=self)
        box.setDetailedText(details)
        box.exec()

    def _cancel(self):
        if self.task:
            self.task.requestInterruption()
            self.status.setText("Cancelando…")

    # ---------- arquivos ----------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self._busy():
            event.acceptProposedAction()
            self.drop.set_drag_active(True)

    def dragLeaveEvent(self, event):
        self.drop.set_drag_active(False)

    def dropEvent(self, event):
        self.drop.set_drag_active(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self._add_paths(paths)

    def _choose_files(self):
        if self._busy():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Escolha vídeos e áudios")
        self._add_paths(paths)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Escolha uma pasta")
        if folder:
            self._add_paths([folder])

    def _add_paths(self, paths):
        known = {os.path.normcase(c.path) for c in self.clips}
        files = [p for p in collect(paths) if os.path.normcase(p) not in known]
        if not files:
            return

        def done(result):
            clips, errors = result
            self.clips.extend(clips)
            self._sort_clips()
            self._invalidate()
            if errors:
                QMessageBox.warning(self, "Alguns arquivos foram ignorados", "\n".join(errors[:30]))

        self._run(_import_files(files), done)

    def _sort_clips(self):
        self.clips.sort(key=lambda c: (c.device.lower(), c.name.lower()))

    def _device_colors(self) -> dict[str, QColor]:
        devices = sorted({c.device for c in self.clips}, key=str.lower)
        return {d: device_color(i) for i, d in enumerate(devices)}

    def _selected_clips(self) -> list[MediaInfo]:
        selected = []
        for item in self.tree.selectedItems():
            clip = item.data(0, CLIP_ROLE)
            if clip is not None:
                selected.append(clip)
            else:   # câmera/gravador selecionado: todos os arquivos dele
                selected += [item.child(k).data(0, CLIP_ROLE) for k in range(item.childCount())]
        return list({id(c): c for c in selected}.values())

    def _remove_selected(self):
        if self._busy():
            return
        remove = {id(c) for c in self._selected_clips()}
        if remove:
            self.clips = [c for c in self.clips if id(c) not in remove]
            self._invalidate()

    def _clear(self):
        if self.clips and QMessageBox.question(
                self, "Remover toda a mídia", "Remover todos os arquivos da lista?") == QMessageBox.Yes:
            self.clips = []
            self._invalidate()

    def _tree_menu(self, pos):
        if not self._selected_clips() or self._busy():
            return
        menu = QMenu(self)
        menu.addAction("Definir Câmera/Gravador…", self._set_device)
        menu.addSeparator()
        menu.addAction("Remover", self._remove_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_device(self):
        clips = self._selected_clips()
        name, ok = QInputDialog.getText(self, "Câmera ou gravador",
                                        "Nome da câmera/gravador destes arquivos:",
                                        text=clips[0].device)
        if ok and name.strip():
            for c in clips:
                c.device = name.strip()
            self._sort_clips()
            self._invalidate()

    # ---------- desenho da lista e da linha do tempo ----------

    def _invalidate(self):
        self.result = None
        self.synced_clips = []
        self._update_views()

    def _update_views(self):
        self._fill_tree()
        self._fill_timeline()
        self._refresh()

    def _clip_status(self, clip: MediaInfo):
        """(símbolo, cor, explicação) do clipe depois de sincronizar."""
        if self.result is None:
            return "", None, ""
        index = self._synced_index[id(clip)]
        if index in self.result.unmatched:
            reason = self.result.errors.get(index, "Nenhum som em comum com os outros arquivos.")
            return "✕", QColor(RED), reason
        drift = self.result.drift_ms(index)
        if drift > self._frame_ms():
            return "⚠", QColor(ORANGE), (
                f"Os relógios dos aparelhos se afastaram ~{drift:.0f} ms ao longo deste clipe. "
                "Ele foi alinhado pelo meio; confira as pontas no Premiere.")
        return "✓", QColor(GREEN), "Sincronizado"

    def _frame_ms(self) -> float:
        fps = next((c.fps for c in self.clips if c.has_video and c.fps), 30.0)
        return 1000.0 / fps

    def _fill_tree(self):
        self.tree.clear()
        colors = self._device_colors()
        parents: dict[str, QTreeWidgetItem] = {}
        for clip in self.clips:
            parent = parents.get(clip.device)
            if parent is None:
                parent = QTreeWidgetItem([clip.device, ""])
                parent.setIcon(0, _dot_icon(colors[clip.device]))
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                self.tree.addTopLevelItem(parent)
                parents[clip.device] = parent
            symbol, color, reason = self._clip_status(clip)
            item = QTreeWidgetItem([clip.name, symbol])
            item.setData(0, CLIP_ROLE, clip)
            kind = (f"Vídeo {clip.width}×{clip.height} · {clip.fps:g} fps"
                    if clip.has_video else "Áudio")
            item.setToolTip(0, f"{clip.path}\n{kind} · {format_time(clip.duration)[:-4]}")
            if color is not None:
                item.setForeground(1, color)
                item.setToolTip(1, reason)
                item.setTextAlignment(1, Qt.AlignCenter)
            parent.addChild(item)
        self.tree.expandAll()
        for name, parent in parents.items():
            n = parent.childCount()
            parent.setText(0, f"{name}")
            parent.setToolTip(0, f"{n} arquivo{'s' if n != 1 else ''}")

    def _fill_timeline(self):
        if not self.clips:
            self.stack.setCurrentWidget(self.drop)
            return
        self.stack.setCurrentWidget(self.timeline)
        colors = self._device_colors()
        if self.result is None:
            rows, bands, total = self._preview_rows(colors)
        else:
            rows, bands, total = self._synced_rows(colors)
        self.timeline.set_content(rows, bands, total)

    def _clip_tooltip(self, clip: MediaInfo, start: float | None, note: str = "") -> str:
        lines = [f"<b>{clip.name}</b>", f"{clip.device} · duração {format_time(clip.duration)[:-4]}"]
        if start is not None:
            lines.append(f"Começa em {format_time(start)}")
        if note:
            lines.append(note)
        return "<br>".join(lines)

    def _preview_rows(self, colors):
        """Antes de sincronizar: cada câmera/gravador numa trilha, clipes em fila."""
        rows, total = [], 0.0
        by_device: dict[str, list[MediaInfo]] = {}
        for clip in self.clips:
            by_device.setdefault(clip.device, []).append(clip)
        for device, clips in by_device.items():
            row = Row(device, f"{len(clips)} clipe{'s' if len(clips) != 1 else ''}", colors[device])
            t = 0.0
            for clip in clips:
                row.clips.append(ClipBar(t, clip.duration, clip.name, colors[device], PENDING,
                                         clip.peaks, self._clip_tooltip(clip, None)))
                t += clip.duration + PREVIEW_GAP
            total = max(total, t)
            rows.append(row)
        return rows, [], total

    def _synced_rows(self, colors):
        clips, result = self.synced_clips, self.result
        tl = build_timeline(clips, result, include_unmatched=True)
        keyed: dict[tuple[int, int], list] = {}
        for p in tl.placements:
            key = (0, p.video_track) if p.video_track is not None else (1, p.audio_track)
            keyed.setdefault(key, []).append(p)

        rows, seen = [], {}
        for key in sorted(keyed):
            placements = keyed[key]
            device = placements[0].clip.device
            seen[device] = seen.get(device, 0) + 1
            label = device if seen[device] == 1 else f"{device} {seen[device]}"
            kind = "Vídeo" if key[0] == 0 else "Áudio"
            row = Row(label, f"{kind} · {len(placements)} clipe{'s' if len(placements) != 1 else ''}",
                      colors[device])
            for p in placements:
                symbol, _, reason = self._clip_status(p.clip)
                state = UNMATCHED if p.group < 0 else SYNCED
                note = reason if symbol in ("⚠", "✕") else ""
                row.clips.append(ClipBar(p.start, p.clip.duration, p.clip.name, colors[device], state,
                                         p.clip.peaks,
                                         self._clip_tooltip(p.clip, p.start if p.group >= 0 else None, note),
                                         warning=symbol == "⚠"))
            rows.append(row)

        bands: dict[int, Band] = {}
        for p in tl.placements:
            end = p.start + p.clip.duration
            band = bands.get(p.group)
            if band is None:
                label = f"Grupo {p.group + 1}" if p.group >= 0 else "Não sincronizados"
                bands[p.group] = Band(p.start, end, label, warning=p.group < 0)
            else:
                band.start, band.end = min(band.start, p.start), max(band.end, end)
        total = max((b.end for b in bands.values()), default=1.0)
        return rows, [bands[g] for g in sorted(bands, key=lambda g: (g < 0, g))], total

    # ---------- sincronizar e exportar ----------

    def _synchronize(self):
        if len(self.clips) < 2 or self._busy():
            return
        clips = list(self.clips)

        def work(progress, is_cancelled):
            return synchronize(clips, progress, is_cancelled)

        def done(result: SyncResult):
            self.result = result
            self.synced_clips = clips
            self._synced_index = {id(c): i for i, c in enumerate(clips)}
            self._update_views()

        self._invalidate()
        self._run(work, done)

    def _export(self):
        if self.result is None or not self.result.groups:
            return
        clips = self.synced_clips
        start_dir = os.path.dirname(clips[0].path) if clips else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar para o Premiere",
            os.path.join(start_dir, "Sincronia.xml"), "XML do Premiere (*.xml)")
        if not path:
            return
        if not path.lower().endswith(".xml"):
            path += ".xml"
        try:
            timeline = build_timeline(clips, self.result, self.act_include.isChecked())
            write_premiere_xml(timeline, path, sequence_name=os.path.splitext(os.path.basename(path))[0])
        except Exception:
            self._on_failed(traceback.format_exc())
            return
        self.status.setText(f"Exportado: {os.path.basename(path)}")
        QMessageBox.information(
            self, "Exportado",
            "Pronto! Para abrir no Premiere Pro:\n\n"
            "1. Abra (ou crie) um projeto.\n"
            "2. Menu Arquivo › Importar… e escolha este arquivo XML.\n"
            "3. Abra a sequência que aparece no painel Projeto.\n\n"
            "Não mova nem renomeie os vídeos e áudios antes de importar.")

    # ---------- ajuda ----------

    def _help(self):
        QMessageBox.information(
            self, "Como usar o Sincronia",
            "1. Deixe os arquivos de cada câmera ou gravador numa pasta própria "
            "(ex.: Camera A, Camera B, Gravador). Cada pasta vira uma trilha.\n\n"
            "2. Arraste as pastas para a janela.\n\n"
            "3. Clique em Sincronizar. O programa compara o som de todos os arquivos.\n\n"
            "4. Clique em Exportar para Premiere e importe o XML no Premiere "
            "(Arquivo › Importar…).\n\n"
            "Dicas: todas as câmeras precisam gravar o próprio áudio, mesmo que ruim. "
            "Na linha do tempo, use Ctrl/⌘ + rolagem (ou pinça no trackpad) para aproximar.")

    def _about(self):
        QMessageBox.about(
            self, "Sobre o Sincronia",
            f"<h3>Sincronia {__version__}</h3>"
            "<p>Sincroniza câmeras e gravadores pelo áudio e exporta para o Premiere Pro.</p>"
            "<p>Gratuito. Usa FFmpeg, Qt (PySide6) e NumPy.</p>")

    def closeEvent(self, event):
        if self._busy():
            self.task.requestInterruption()
            self.task.wait(5000)
        super().closeEvent(event)


def _selftest(report_path: str) -> None:
    """Usado no empacotamento: confirma que o FFmpeg embutido funciona."""
    import subprocess
    from .media import _hidden_window_flags, ffmpeg_path
    exe = ffmpeg_path()
    out = subprocess.run([exe, "-version"], capture_output=True, text=True,
                         creationflags=_hidden_window_flags()).stdout.splitlines()
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"{exe}\n{out[0] if out else 'FALHOU'}\n")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        _selftest(sys.argv[2])
        return
    if sys.platform == "win32":   # ícone próprio na barra de tarefas
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sincronia.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Sincronia")
    app.setApplicationVersion(__version__)
    apply_theme(app)
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
