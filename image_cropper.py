"""이미지 일괄 자르기 (Image Batch Cropper) - Windows 11 GUI

폴더 안의 모든 이미지를 같은 영역으로 잘라 지정한 폴더에 저장합니다.
"""
import ctypes
import os
import re
import sys
from collections import Counter
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRect, QRectF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

APP_NAME = "이미지 일괄 자르기"
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}

ACCENT = "#5b8cff"
BG = "#17181d"
CARD = "#212329"
BORDER = "#30333c"
TEXT = "#e6e8ee"
MUTED = "#8b90a0"
WARN = "#f2b84b"


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def pil_to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    return QImage(data, im.width, im.height, im.width * 4,
                  QImage.Format_RGBA8888).copy()


# ---------------------------------------------------------------- 작업 스레드
class CropWorker(QThread):
    progress = Signal(int, str)
    done = Signal(int, list)

    def __init__(self, files, out_dir, box, fmt, suffix):
        super().__init__()
        self.files, self.out_dir, self.box = files, Path(out_dir), box
        self.fmt, self.suffix = fmt, suffix

    def run(self):
        x, y, w, h = self.box
        ok, errors = 0, []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for i, path in enumerate(self.files, 1):
            try:
                with Image.open(path) as im:
                    right, bottom = min(x + w, im.width), min(y + h, im.height)
                    if x >= right or y >= bottom:
                        raise ValueError("자르기 영역이 이미지 범위를 벗어납니다")
                    cropped = im.crop((x, y, right, bottom))
                    ext = path.suffix if self.fmt == "original" else (
                        ".png" if self.fmt == "png" else ".jpg")
                    target = self.out_dir / f"{path.stem}{self.suffix}{ext}"
                    kwargs = {}
                    icc = im.info.get("icc_profile")
                    if icc:
                        kwargs["icc_profile"] = icc
                    if ext.lower() in (".jpg", ".jpeg"):
                        if cropped.mode not in ("RGB", "L"):
                            cropped = cropped.convert("RGB")
                        kwargs.update(quality=95, subsampling=0)
                    cropped.save(target, **kwargs)
                ok += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path.name}: {e}")
            self.progress.emit(i, path.name)
        self.done.emit(ok, errors)


# ---------------------------------------------------------------- 미리보기 캔버스
class CropCanvas(QWidget):
    rectChanged = Signal(int, int, int, int)
    HANDLE = 8
    TOL = 8

    def __init__(self):
        super().__init__()
        self.pix = None
        self.img_w = self.img_h = 0
        self.bw = self.bh = 1
        self.crop = QRect(0, 0, 1, 1)
        self.scale = 1.0
        self.mode = None
        self.setMouseTracking(True)

    # --- 외부 API
    def set_image(self, pix, w, h):
        self.pix, self.img_w, self.img_h = pix, w, h
        self.update()

    def set_bounds(self, bw, bh):
        self.bw, self.bh = max(1, bw), max(1, bh)
        self.set_scale(self.scale)

    def set_crop(self, x, y, w, h):
        self.crop = QRect(x, y, w, h)
        self.update()

    def set_scale(self, s):
        self.scale = max(0.01, s)
        self.setFixedSize(max(1, round(self.bw * self.scale)),
                          max(1, round(self.bh * self.scale)))
        self.update()

    # --- 그리기
    def _screen_rect(self) -> QRectF:
        s = self.scale
        c = self.crop
        return QRectF(c.x() * s, c.y() * s, c.width() * s, c.height() * s)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.scale
        full = QRectF(0, 0, self.width(), self.height())
        p.fillRect(full, QColor("#101114"))
        p.fillRect(full, QBrush(QColor("#2a2d36"), Qt.BDiagPattern))
        if self.pix:
            p.drawPixmap(QRectF(0, 0, self.img_w * s, self.img_h * s),
                         self.pix, QRectF(self.pix.rect()))

        r = self._screen_rect()
        shade = QPainterPath()
        shade.addRect(full)
        inner = QPainterPath()
        inner.addRect(r)
        p.fillPath(shade.subtracted(inner), QColor(0, 0, 0, 150))

        p.setPen(QPen(QColor(ACCENT), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        # 3등분 가이드
        p.setPen(QPen(QColor(255, 255, 255, 60), 1, Qt.DashLine))
        for k in (1, 2):
            p.drawLine(QPointF(r.left() + r.width() * k / 3, r.top()),
                       QPointF(r.left() + r.width() * k / 3, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + r.height() * k / 3),
                       QPointF(r.right(), r.top() + r.height() * k / 3))
        # 핸들
        p.setPen(QPen(QColor(ACCENT), 1.5))
        p.setBrush(QColor("white"))
        hs = self.HANDLE
        for hx in (r.left(), r.center().x(), r.right()):
            for hy in (r.top(), r.center().y(), r.bottom()):
                if hx == r.center().x() and hy == r.center().y():
                    continue
                p.drawRoundedRect(QRectF(hx - hs / 2, hy - hs / 2, hs, hs), 2, 2)
        # 크기 라벨
        label = f"{self.crop.width()} × {self.crop.height()} px"
        f = QFont("Segoe UI", 9, QFont.DemiBold)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(label) + 14
        lx = max(2, min(r.left() + 6, self.width() - tw - 2))
        ly = max(2, r.top() + 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawRoundedRect(QRectF(lx, ly, tw, 22), 6, 6)
        p.setPen(QColor("white"))
        p.drawText(QRectF(lx, ly, tw, 22), Qt.AlignCenter, label)
        p.end()

    # --- 마우스 조작
    def _hit(self, pos):
        r = self._screen_rect()
        t = self.TOL
        x, y = pos.x(), pos.y()
        inside_v = r.top() - t <= y <= r.bottom() + t
        inside_h = r.left() - t <= x <= r.right() + t
        m = set()
        if inside_v and abs(x - r.left()) <= t:
            m.add("l")
        elif inside_v and abs(x - r.right()) <= t:
            m.add("r")
        if inside_h and abs(y - r.top()) <= t:
            m.add("t")
        elif inside_h and abs(y - r.bottom()) <= t:
            m.add("b")
        if m:
            return frozenset(m)
        if r.contains(pos):
            return frozenset({"move"})
        return frozenset({"new"})

    CURSORS = {
        frozenset("l"): Qt.SizeHorCursor, frozenset("r"): Qt.SizeHorCursor,
        frozenset("t"): Qt.SizeVerCursor, frozenset("b"): Qt.SizeVerCursor,
        frozenset("tl"): Qt.SizeFDiagCursor, frozenset("br"): Qt.SizeFDiagCursor,
        frozenset("tr"): Qt.SizeBDiagCursor, frozenset("bl"): Qt.SizeBDiagCursor,
        frozenset({"move"}): Qt.SizeAllCursor, frozenset({"new"}): Qt.CrossCursor,
    }

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.mode = self._hit(e.position())
        self.start_pos = e.position()
        self.start_crop = QRect(self.crop)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.mode is None:
            self.setCursor(self.CURSORS[self._hit(pos)])
            return
        s = self.scale
        dx = (pos.x() - self.start_pos.x()) / s
        dy = (pos.y() - self.start_pos.y()) / s
        c = self.start_crop
        x1, y1, x2, y2 = c.x(), c.y(), c.x() + c.width(), c.y() + c.height()
        if "move" in self.mode:
            w, h = x2 - x1, y2 - y1
            x1 = min(max(0, round(x1 + dx)), self.bw - w)
            y1 = min(max(0, round(y1 + dy)), self.bh - h)
            x2, y2 = x1 + w, y1 + h
        elif "new" in self.mode:
            x1, y1 = self.start_pos.x() / s, self.start_pos.y() / s
            x2, y2 = pos.x() / s, pos.y() / s
        else:
            if "l" in self.mode:
                x1 += dx
            if "r" in self.mode:
                x2 += dx
            if "t" in self.mode:
                y1 += dy
            if "b" in self.mode:
                y2 += dy
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        x1 = round(min(max(0, x1), self.bw - 1))
        y1 = round(min(max(0, y1), self.bh - 1))
        x2 = round(min(max(x1 + 1, x2), self.bw))
        y2 = round(min(max(y1 + 1, y2), self.bh))
        self.crop = QRect(x1, y1, x2 - x1, y2 - y1)
        self.update()
        self.rectChanged.emit(x1, y1, x2 - x1, y2 - y1)

    def mouseReleaseEvent(self, _):
        self.mode = None


class PreviewArea(QScrollArea):
    resized = Signal()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit()


# ---------------------------------------------------------------- 메인 창
def card(title: str):
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("cardTitle")
    lay.addWidget(t)
    return frame, lay


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 940)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.settings = QSettings("ImageCropper", "ImageCropper")
        self.files: list[Path] = []
        self.sizes: list[tuple[int, int]] = []
        self.max_w = self.max_h = 0
        self.worker = None

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(10)
        left = QScrollArea()
        left.setObjectName("leftScroll")
        left.setWidgetResizable(True)
        left.setFrameShape(QFrame.NoFrame)
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.setWidget(self._build_left())
        left_box = QWidget()
        lb = QVBoxLayout(left_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.addWidget(left, 1)
        lb.addWidget(self._build_run_box())
        left_box.setMinimumWidth(400)
        splitter.addWidget(left_box)
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 900])
        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(16, 16, 16, 16)
        rl.addWidget(splitter)
        self.setCentralWidget(root)
        self._set_crop_enabled(False)

        last_src = self.settings.value("src", "")
        last_out = self.settings.value("out", "")
        if last_out:
            self.out_edit.setText(last_out)
        if last_src and Path(last_src).is_dir():
            self.load_folder(last_src)

    # --- UI 구성
    def _build_left(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)


        # ① 원본 폴더
        c, cl = card("①  원본 폴더")
        row = QHBoxLayout()
        self.src_edit = QLineEdit()
        self.src_edit.setReadOnly(True)
        self.src_edit.setPlaceholderText("폴더를 선택하거나 창에 끌어다 놓으세요")
        b = QPushButton("찾아보기")
        b.clicked.connect(self.pick_src)
        row.addWidget(self.src_edit, 1)
        row.addWidget(b)
        cl.addLayout(row)
        self.width_info = QLabel("이미지를 불러오면 가로 크기가 표시됩니다")
        self.width_info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.width_info.setObjectName("info")
        cl.addWidget(self.width_info)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["번호", "가로 (px)", "세로 (px)"])
        hh = self.table.horizontalHeader()
        for col in range(3):
            hh.setSectionResizeMode(col, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(130)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.table.currentCellChanged.connect(lambda r, *_: self.show_preview(r))
        cl.addWidget(self.table, 1)
        lay.addWidget(c, 1)

        # ② 자르기 영역
        c, cl = card("②  자르기 영역 (px)")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.sp_x, self.sp_w = QSpinBox(), QSpinBox()
        self.sp_y, self.sp_h = QSpinBox(), QSpinBox()
        for sp in (self.sp_x, self.sp_y, self.sp_w, self.sp_h):
            sp.setRange(0, 100000)
            sp.setSuffix(" px")
            sp.setAccelerated(True)
            sp.setToolTip("숫자를 입력하거나 마우스 휠 / ↑↓ 키로 조절")
            sp.valueChanged.connect(self.on_spin)
        self.btn_wmax = QPushButton("최대")
        self.btn_wmax.setObjectName("small")
        self.btn_wmax.setToolTip("가로를 가장 긴 가로 크기로 되돌립니다")
        self.btn_wmax.clicked.connect(self.reset_width)
        self.btn_hmax = QPushButton("최대")
        self.btn_hmax.setObjectName("small")
        self.btn_hmax.setToolTip("세로를 전체 높이로 되돌립니다")
        self.btn_hmax.clicked.connect(self.reset_height)
        for col, text in ((1, "시작 위치"), (2, "크기")):
            h = QLabel(text)
            h.setObjectName("colHead")
            g.addWidget(h, 0, col)
        g.addWidget(self._lbl("가로 (X)"), 1, 0)
        g.addWidget(self.sp_x, 1, 1)
        g.addWidget(self.sp_w, 1, 2)
        g.addWidget(self.btn_wmax, 1, 3)
        g.addWidget(self._lbl("세로 (Y)"), 2, 0)
        g.addWidget(self.sp_y, 2, 1)
        g.addWidget(self.sp_h, 2, 2)
        g.addWidget(self.btn_hmax, 2, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        cl.addLayout(g)
        self.result_info = QLabel("")
        self.result_info.setObjectName("muted")
        self.result_info.setWordWrap(True)
        cl.addWidget(self.result_info)
        lay.addWidget(c)

        # ③ 저장 폴더
        c, cl = card("③  저장 폴더")
        row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("잘라낸 이미지를 저장할 폴더")
        b = QPushButton("찾아보기")
        b.clicked.connect(self.pick_out)
        row.addWidget(self.out_edit, 1)
        row.addWidget(b)
        cl.addLayout(row)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(10)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("원본 형식 유지", "original")
        self.fmt_combo.addItem("PNG (무손실)", "png")
        self.fmt_combo.addItem("JPG (품질 95)", "jpg")
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("예: _crop")
        self.suffix_edit.setToolTip("비워 두면 원본과 같은 파일명으로 저장합니다")
        g2.setVerticalSpacing(4)
        h1, h2 = QLabel("저장 형식"), QLabel("파일명 접미사")
        h1.setObjectName("colHead")
        h2.setObjectName("colHead")
        g2.addWidget(h1, 0, 0)
        g2.addWidget(h2, 0, 1)
        g2.addWidget(self.fmt_combo, 1, 0)
        g2.addWidget(self.suffix_edit, 1, 1)
        g2.setColumnStretch(0, 1)
        g2.setColumnStretch(1, 1)
        cl.addLayout(g2)
        lay.addWidget(c)
        return panel

    def _build_run_box(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(8)
        self.run_btn = QPushButton("실행")
        self.run_btn.setObjectName("primary")
        self.run_btn.setMinimumHeight(46)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self.run)
        lay.addWidget(self.run_btn)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        lay.addWidget(self.progress)
        self.status = QLabel("준비")
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        return box

    def _build_right(self):
        c, cl = card("미리보기")
        top = QHBoxLayout()
        self.preview_name = QLabel("")
        self.preview_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.preview_name.setObjectName("muted")
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItem("화면에 맞춤", "fit")
        self.zoom_combo.addItem("가로에 맞춤", "width")
        self.zoom_combo.addItem("100%", "100")
        self.zoom_combo.currentIndexChanged.connect(self.update_scale)
        top.addWidget(self.preview_name, 1)
        top.addWidget(self.zoom_combo)
        cl.addLayout(top)

        self.canvas = CropCanvas()
        self.canvas.rectChanged.connect(self.on_canvas_rect)
        self.area = PreviewArea()
        self.area.setObjectName("preview")
        self.area.setWidget(self.canvas)
        self.area.setAlignment(Qt.AlignCenter)
        self.area.setWidgetResizable(False)
        self.area.resized.connect(self.update_scale)
        self.placeholder = QLabel("원본 폴더를 선택하면 이미지가 여기에 표시됩니다\n\n"
                                  "미리보기에서 파란 영역의 테두리를 끌어 자를 부분을 조절하세요")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setObjectName("placeholder")
        cl.addWidget(self.placeholder, 1)
        cl.addWidget(self.area, 1)
        self.area.hide()
        hint = QLabel("테두리·모서리: 크기 조절   ·   안쪽: 이동   ·   바깥 드래그: 새 영역 그리기")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignCenter)
        cl.addWidget(hint)
        return c

    @staticmethod
    def _lbl(text):
        l = QLabel(text)
        l.setObjectName("field")
        return l

    def _set_crop_enabled(self, on):
        for w in (self.sp_x, self.sp_y, self.sp_w, self.sp_h,
                  self.btn_wmax, self.btn_hmax, self.run_btn):
            w.setEnabled(on)

    # --- 폴더
    def pick_src(self):
        d = QFileDialog.getExistingDirectory(self, "원본 폴더 선택",
                                             self.src_edit.text() or "")
        if d:
            self.load_folder(d)

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택",
                                             self.out_edit.text() or self.src_edit.text())
        if d:
            self.out_edit.setText(os.path.normpath(d))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file():
                p = p.parent
            if p.is_dir():
                self.load_folder(str(p))
                break

    def load_folder(self, folder):
        folder = os.path.normpath(folder)
        files = sorted((p for p in Path(folder).iterdir()
                        if p.is_file() and p.suffix.lower() in IMG_EXT),
                       key=lambda p: natural_key(p.name))
        files_ok, sizes = [], []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p in files:
                try:
                    with Image.open(p) as im:
                        sizes.append(im.size)
                        files_ok.append(p)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            QApplication.restoreOverrideCursor()

        self.src_edit.setText(folder)
        self.settings.setValue("src", folder)
        self.files, self.sizes = files_ok, sizes
        self.table.setRowCount(0)
        if not files_ok:
            self.max_w = self.max_h = 0
            self.width_info.setText("이 폴더에는 이미지가 없습니다")
            self._set_crop_enabled(False)
            self.area.hide()
            self.placeholder.show()
            self.preview_name.setText("")
            return

        self.max_w = max(w for w, _ in sizes)
        self.max_h = max(h for _, h in sizes)
        widths = Counter(w for w, _ in sizes)
        if len(widths) == 1:
            self.width_info.setText(
                f"이미지 <b>{len(files_ok)}</b>개  ·  가로 <b>{self.max_w}px</b> (모두 동일)")
        else:
            dist = ", ".join(f"{w}px×{n}" for w, n in sorted(widths.items(), reverse=True)[:4])
            self.width_info.setText(
                f"이미지 <b>{len(files_ok)}</b>개  ·  가장 긴 가로 <b>{self.max_w}px</b>"
                f"<br><span style='color:{WARN}'>가로 크기가 다른 이미지 있음: {dist}</span>")

        self.table.setRowCount(len(files_ok))
        for r, (p, (w, h)) in enumerate(zip(files_ok, sizes)):
            items = [QTableWidgetItem(str(r + 1)), QTableWidgetItem(str(w)),
                     QTableWidgetItem(str(h))]
            for it in items:
                it.setTextAlignment(Qt.AlignCenter)
            if w != self.max_w:
                items[1].setForeground(QColor(WARN))
            for col, it in enumerate(items):
                self.table.setItem(r, col, it)

        self.canvas.set_bounds(self.max_w, self.max_h)
        self._set_crop_enabled(True)
        self.set_crop(0, 0, self.max_w, self.max_h)
        self.placeholder.hide()
        self.area.show()
        self.table.setCurrentCell(0, 0)
        self.show_preview(0)
        self.update_scale()
        self.status.setText("준비")
        self.progress.setValue(0)

    # --- 미리보기
    def show_preview(self, row):
        if not (0 <= row < len(self.files)):
            return
        p = self.files[row]
        try:
            with Image.open(p) as im:
                pix = QPixmap.fromImage(pil_to_qimage(im))
            w, h = self.sizes[row]
            self.canvas.set_image(pix, w, h)
            self.preview_name.setText(f"{row + 1} / {len(self.files)}번째 이미지   ·   {w} × {h}px")
        except Exception as e:  # noqa: BLE001
            self.preview_name.setText(f"{row + 1}번째 이미지 - 미리보기 실패")

    def update_scale(self, *_):
        if not self.max_w:
            return
        vp = self.area.viewport().size()
        sb = self.area.verticalScrollBar().sizeHint().width()
        mode = self.zoom_combo.currentData()
        if mode == "100":
            s = 1.0
        elif mode == "width":
            s = (vp.width() - sb - 4) / self.max_w
        else:
            s = min((vp.width() - 4) / self.max_w, (vp.height() - 4) / self.max_h)
        self.canvas.set_scale(min(s, 4.0))

    # --- 자르기 영역 동기화
    def set_crop(self, x, y, w, h):
        for sp in (self.sp_x, self.sp_y, self.sp_w, self.sp_h):
            sp.blockSignals(True)
        self.sp_x.setRange(0, max(0, self.max_w - 1))
        self.sp_y.setRange(0, max(0, self.max_h - 1))
        self.sp_x.setValue(x)
        self.sp_y.setValue(y)
        self.sp_w.setRange(1, max(1, self.max_w - x))
        self.sp_h.setRange(1, max(1, self.max_h - y))
        self.sp_w.setValue(w)
        self.sp_h.setValue(h)
        for sp in (self.sp_x, self.sp_y, self.sp_w, self.sp_h):
            sp.blockSignals(False)
        self.canvas.set_crop(x, y, self.sp_w.value(), self.sp_h.value())
        self._update_result_info()

    def on_spin(self, *_):
        self.set_crop(self.sp_x.value(), self.sp_y.value(),
                      self.sp_w.value(), self.sp_h.value())

    def on_canvas_rect(self, x, y, w, h):
        self.set_crop(x, y, w, h)

    def reset_width(self):
        self.set_crop(0, self.sp_y.value(), self.max_w, self.sp_h.value())

    def reset_height(self):
        self.set_crop(self.sp_x.value(), 0, self.sp_w.value(), self.max_h)

    def _update_result_info(self):
        x, y, w, h = (self.sp_x.value(), self.sp_y.value(),
                      self.sp_w.value(), self.sp_h.value())
        txt = (f"결과 크기 <b>{w} × {h}px</b>  ·  영역 ({x}, {y}) → ({x + w}, {y + h})")
        short = sum(1 for iw, ih in self.sizes if ih < y + h or iw < x + w)
        if short:
            txt += (f"<br><span style='color:{WARN}'>{short}개 이미지는 영역보다 작아 "
                    f"이미지 끝까지만 잘립니다</span>")
        self.result_info.setText(txt)

    # --- 실행
    def run(self):
        if not self.files:
            return
        out = self.out_edit.text().strip()
        if not out:
            self.pick_out()
            out = self.out_edit.text().strip()
            if not out:
                return
        out_dir = Path(out)
        fmt = self.fmt_combo.currentData()
        suffix = self.suffix_edit.text().strip()
        if re.search(r'[\\/:*?"<>|]', suffix):
            QMessageBox.warning(self, APP_NAME, "파일명 접미사에 사용할 수 없는 문자가 있습니다.")
            return

        def target_of(p):
            ext = p.suffix if fmt == "original" else (".png" if fmt == "png" else ".jpg")
            return out_dir / f"{p.stem}{suffix}{ext}"

        targets = [target_of(p) for p in self.files]
        src_set = {p.resolve() for p in self.files}
        overwrite_src = [t for t in targets if t.exists() and t.resolve() in src_set]
        existing = [t for t in targets if t.exists()]
        if overwrite_src:
            r = QMessageBox.warning(
                self, APP_NAME,
                f"원본 이미지 {len(overwrite_src)}개를 덮어쓰게 됩니다.\n"
                "원본은 복구할 수 없습니다. 계속할까요?\n\n"
                "(다른 저장 폴더나 파일명 접미사를 쓰면 원본이 보존됩니다)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        elif existing:
            r = QMessageBox.question(
                self, APP_NAME,
                f"저장 폴더에 같은 이름의 파일이 {len(existing)}개 있습니다. 덮어쓸까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                return

        self.settings.setValue("out", str(out_dir))
        box = (self.sp_x.value(), self.sp_y.value(), self.sp_w.value(), self.sp_h.value())
        self.progress.setRange(0, len(self.files))
        self.progress.setValue(0)
        self._set_crop_enabled(False)
        self.run_btn.setText("처리 중…")
        self.worker = CropWorker(list(self.files), out_dir, box, fmt, suffix)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_progress(self, i, name):
        self.progress.setValue(i)
        self.status.setText(f"처리 중  {i} / {len(self.files)}")

    def on_done(self, ok, errors):
        self._set_crop_enabled(True)
        self.run_btn.setText("실행")
        out = self.out_edit.text().strip()
        self.status.setText(f"완료: {ok}개 저장" + (f", {len(errors)}개 실패" if errors else ""))
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        if errors:
            box.setIcon(QMessageBox.Warning)
            box.setText(f"{ok}개 저장, {len(errors)}개 실패")
            box.setDetailedText("\n".join(errors))
        else:
            box.setIcon(QMessageBox.Information)
            box.setText(f"{ok}개 이미지를 모두 저장했습니다.")
        open_btn = box.addButton("폴더 열기", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn and os.path.isdir(out):
            os.startfile(out)


# ---------------------------------------------------------------- 스타일
STYLE = f"""
* {{ font-family: 'Segoe UI', 'Malgun Gothic'; font-size: 10pt; color: {TEXT}; }}
QMainWindow {{ background: {BG}; }}
QLabel {{ background: transparent; }}
#appTitle {{ font-size: 17pt; font-weight: 700; }}
#muted {{ color: {MUTED}; }}
#field {{ color: {MUTED}; }}
#colHead {{ color: {MUTED}; font-size: 9pt; }}
#info {{ color: {TEXT}; background: #1a2235; border: 1px solid #2a3a5c;
         border-radius: 8px; padding: 8px 10px; }}
#placeholder {{ color: {MUTED}; background: #131418; border: 1px dashed {BORDER};
                border-radius: 10px; font-size: 11pt; }}
#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
#cardTitle {{ font-size: 11pt; font-weight: 600; }}
QLineEdit, QSpinBox, QComboBox {{
    background: #2a2d35; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 6px 9px; selection-background-color: {ACCENT}; min-height: 20px; }}
QSpinBox {{ padding: 4px 26px 4px 10px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 22px;
    border: none; background: transparent; }}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #353946; border-radius: 4px; }}
QSpinBox::up-arrow {{ image: url(ARROW_UP); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url(ARROW_PATH); width: 9px; height: 9px; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:read-only {{ color: {MUTED}; }}
QSpinBox:disabled, QLineEdit:disabled {{ color: #5a5f6d; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url(ARROW_PATH); width: 10px; height: 10px; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: #2a2d35; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; outline: 0; padding: 4px; }}
QPushButton {{ background: #2f333d; border: 1px solid #3a3e4a; border-radius: 7px;
    padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: #383c48; }}
QPushButton:pressed {{ background: #2a2d35; }}
QPushButton:disabled {{ color: #5a5f6d; background: #25272e; border-color: #2c2f37; }}
QPushButton#small {{ padding: 5px 10px; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white;
    font-size: 12pt; font-weight: 700; border-radius: 10px; }}
QPushButton#primary:hover {{ background: #6f9bff; }}
QPushButton#primary:pressed {{ background: #4a78e0; }}
QPushButton#primary:disabled {{ background: #2f3a55; color: #7c8aa8; }}
QTableWidget {{ background: #1b1d22; border: 1px solid {BORDER}; border-radius: 8px;
    alternate-background-color: #1f2127; outline: 0; }}
QTableWidget::item {{ padding: 4px 6px; border: none; }}
QTableWidget::item:selected {{ background: #2c3d63; color: white; }}
QHeaderView::section {{ background: #22252c; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 6px; font-weight: 600; }}
QProgressBar {{ background: #2a2d35; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QScrollArea#preview {{ background: #131418; border: 1px solid {BORDER}; border-radius: 10px; }}
QScrollArea#preview > QWidget {{ background: #131418; }}
QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; border: none; margin: 2px; }}
QScrollBar:vertical {{ width: 10px; }}
QScrollBar:horizontal {{ height: 10px; }}
QScrollBar::handle {{ background: #3a3e4a; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: #4a4f5e; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}
QScrollArea#leftScroll, QScrollArea#leftScroll > QWidget > QWidget {{ background: {BG}; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: #2a2d35; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
QMessageBox {{ background: {CARD}; }}
"""


def make_arrows() -> dict:
    """콤보박스/스핀박스용 화살표 이미지를 임시 폴더에 만들어 경로를 돌려줍니다."""
    import tempfile
    out = {}
    for key, pts in (("ARROW_PATH", [(4, 7), (10, 13), (16, 7)]),
                     ("ARROW_UP", [(4, 13), (10, 7), (16, 13)])):
        path = os.path.join(tempfile.gettempdir(), f"image_cropper_{key.lower()}.png")
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(MUTED), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(x, y) for x, y in pts])
        p.end()
        pm.save(path)
        out[key] = path.replace("\\", "/")
    return out


def build_style() -> str:
    s = STYLE
    for k, v in make_arrows().items():
        s = s.replace(k, v)
    return s


def enable_dark_titlebar(win):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(win.winId())
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
        # Windows 11: 둥근 모서리
        pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    except Exception:  # noqa: BLE001
        pass


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ImageCropper.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = app.palette()
    for role, col in ((QPalette.Window, BG), (QPalette.Base, '#2a2d35'),
                      (QPalette.AlternateBase, '#1f2127'), (QPalette.Text, TEXT),
                      (QPalette.WindowText, TEXT), (QPalette.Button, '#2f333d'),
                      (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
                      (QPalette.HighlightedText, '#ffffff'), (QPalette.ToolTipBase, '#2a2d35'),
                      (QPalette.ToolTipText, TEXT)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(build_style())
    icon = resource_path("icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow()
    enable_dark_titlebar(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
