from __future__ import annotations

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QDateTime, QRectF, QSize, QStandardPaths, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from material_texture_studio.detect import (
    detect_material_sets,
    detect_material_sets_by_folder,
    is_image_file,
)
from material_texture_studio.models import ChannelSource, MaterialSet, Preset
from material_texture_studio.packer import pack_material, validate_material
from material_texture_studio.presets import MAP_TYPES, PRESETS, ordered_map_types_for_preset
from material_texture_studio.preview import make_thumbnail


APP_BG = "#0E1116"
PANEL_BG = "#151A21"
ELEVATED_BG = "#1B222B"
INPUT_BG = "#10161D"
BORDER = "#2A3440"
BORDER_SOFT = "#24303B"
TEXT = "#E8EEF5"
TEXT_MUTED = "#9AA8B6"
TEXT_DIM = "#6F7D8B"
ACCENT = "#38BDF8"
ACCENT_DARK = "#0B5B7A"
SUCCESS = "#3DDC97"
WARNING = "#F0B85A"
RADIUS = 10
FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "Comfortaa.ttf"
APP_ICON_PATH = Path(__file__).resolve().parents[1] / "texture_packer_icon.ico"


def load_app_font(app: QApplication | None) -> None:
    if not app:
        return
    font_family = "Comfortaa"
    if FONT_PATH.exists():
        font_id = QFontDatabase.addApplicationFont(str(FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            font_family = families[0]
    app.setFont(QFont(font_family, 9))


def short_path(path: Path | None, *, fallback: str = "No folder selected") -> str:
    if not path:
        return fallback
    parts = path.parts
    if len(parts) <= 4:
        return str(path)
    return str(Path(parts[0], "...", *parts[-3:]))


def table_path(path_text: str) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    parts = path.parts
    if len(parts) <= 4:
        return path_text
    anchor = path.anchor.rstrip("\\/")
    tail = "\\".join(parts[-2:])
    return f"{anchor}\\...\\{tail}" if anchor else f"...\\{tail}"


def compact_list(items: list[str], limit: int = 4) -> str:
    if len(items) <= limit:
        return ", ".join(items) if items else "None"
    return ", ".join(items[:limit]) + f", +{len(items) - limit} more"


def settings_path() -> Path:
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    if root:
        return Path(root) / "settings.json"
    return Path.home() / ".material_texture_studio" / "settings.json"


def file_label(path: Path | None) -> str:
    return path.name if path else "Drop a texture here or browse"


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget:
            widget.deleteLater()
        elif child_layout:
            clear_layout(child_layout)


def make_label(text: str, object_name: str = "") -> QLabel:
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    return label


class Panel(QFrame):
    def __init__(self, object_name: str = "Panel"):
        super().__init__()
        self.setObjectName(object_name)


class Pill(QLabel):
    def __init__(self, text: str = "", tone: str = "neutral"):
        super().__init__(text)
        self.setObjectName("Pill")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(24)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class NavButton(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)


class TickCheckBox(QCheckBox):
    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self.text()) + 34, 28)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        box_size = 17
        box_y = int((self.height() - box_size) / 2)
        box = QRectF(0.5, box_y + 0.5, box_size, box_size)
        checked = self.isChecked()

        painter.setPen(QPen(QColor(ACCENT if checked else "#465568"), 1.4))
        painter.setBrush(QColor(ACCENT_DARK if checked else INPUT_BG))
        painter.drawRoundedRect(box, 5, 5)

        if checked:
            painter.setPen(QPen(QColor("#EAF8FF"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(5, box_y + 9, 8, box_y + 12)
            painter.drawLine(8, box_y + 12, 13, box_y + 5)

        painter.setPen(QColor(TEXT_MUTED))
        text_rect = QRectF(25, 0, self.width() - 25, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class FolderPickerRow(QWidget):
    folderChanged = pyqtSignal(str)

    def __init__(self, label: str, placeholder: str):
        super().__init__()
        self.path: Path | None = None

        self.title = make_label(label, "FieldLabel")
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setObjectName("PathEdit")
        self.button = QPushButton("Browse")
        self.button.setObjectName("SecondaryButton")
        self.button.clicked.connect(self.choose)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        layout.addWidget(self.title, 0, 0, 1, 2)
        layout.addWidget(self.edit, 1, 0)
        layout.addWidget(self.button, 1, 1)

    def choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder", str(self.path or Path.home()))
        if folder:
            self.set_path(Path(folder))
            self.folderChanged.emit(folder)

    def set_path(self, path: Path) -> None:
        self.path = path
        self.edit.setText(short_path(path))
        self.edit.setToolTip(str(path))


class TextureSlotCard(Panel):
    fileChanged = pyqtSignal(str, str)

    def __init__(self, map_type: str, required: bool):
        super().__init__("TextureSlotCard")
        self.map_type = map_type
        self.required = required
        self.path: Path | None = None
        self._loading = False
        self.setAcceptDrops(True)
        self.setMinimumHeight(104)
        self.setMaximumHeight(116)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        info = MAP_TYPES[map_type]

        self.preview = QLabel("MAP")
        self.preview.setObjectName("TexturePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(68, 68)

        self.title = make_label(info.label, "SlotTitle")
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.badge = Pill("Required" if required else "Optional", "required" if required else "neutral")
        self.color_hint = make_label(info.color_space, "ColorHint")
        self.color_hint.setToolTip(f"{info.label} should be treated as {info.color_space}.")

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        top_row.addWidget(self.title, 1)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(self.badge)
        meta_row.addWidget(self.color_hint)
        meta_row.addStretch(1)

        self.path_label = make_label(file_label(None), "SlotPath")
        self.path_label.setMinimumWidth(0)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.state_label = make_label("Waiting for input", "SlotState")
        self.state_label.setProperty("tone", "muted")
        self.state_label.setMinimumWidth(0)
        self.state_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(3)
        content.addLayout(top_row)
        content.addLayout(meta_row)
        content.addWidget(self.path_label)
        content.addWidget(self.state_label)

        browse = QPushButton("Browse")
        browse.setObjectName("SecondaryButton")
        browse.clicked.connect(self.browse)
        browse.setFixedSize(78, 30)

        clear = QPushButton("Clear")
        clear.setObjectName("GhostButton")
        clear.clicked.connect(lambda: self.clear())
        clear.setFixedSize(78, 30)

        button_col = QVBoxLayout()
        button_col.setContentsMargins(10, 0, 0, 0)
        button_col.setSpacing(8)
        button_col.addWidget(browse)
        button_col.addWidget(clear)
        button_col.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 18, 10)
        layout.setSpacing(12)
        layout.addWidget(self.preview)
        layout.addLayout(content, 1)
        layout.addLayout(button_col)

        self.update_state()

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {MAP_TYPES[self.map_type].label}",
            str(Path.home()),
            "Texture files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.tga *.webp);;All files (*)",
        )
        if path:
            self.set_file(Path(path))

    def set_file(self, path: Path | None, *, emit: bool = True) -> None:
        if path is None:
            self.clear(emit=emit)
            return
        if not path.is_file() or not is_image_file(path):
            QMessageBox.warning(self, "Unsupported texture", "Choose a supported image file.")
            return

        self.path = path
        self.path_label.setText(file_label(path))
        self.path_label.setToolTip(str(path))
        self._set_preview(path)
        self.update_state()
        if emit:
            self.fileChanged.emit(self.map_type, str(path))

    def clear(self, *, emit: bool = True) -> None:
        self.path = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText("MAP")
        self.path_label.setText(file_label(None))
        self.path_label.setToolTip("")
        self.update_state()
        if emit:
            self.fileChanged.emit(self.map_type, "")

    def update_state(self) -> None:
        if self.path:
            tone = "ready"
            state = "Ready"
        elif self.required:
            tone = "warning"
            state = "Missing required map"
        else:
            tone = "muted"
            state = "Optional"
        self.setProperty("state", tone)
        self.state_label.setProperty("tone", tone)
        self.state_label.setText(state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

    def _set_preview(self, path: Path) -> None:
        pixmap = make_thumbnail(path, 64)
        if pixmap:
            self.preview.setText("")
            self.preview.setPixmap(
                pixmap.scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("MAP")

    def dragEnterEvent(self, event) -> None:
        if self._event_has_supported_image(event):
            event.acceptProposedAction()
            self.setProperty("drag", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("drag", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._event_has_supported_image(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        self.setProperty("drag", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and is_image_file(path):
                self.set_file(path)
                event.acceptProposedAction()
                return
        event.ignore()

    @staticmethod
    def _event_has_supported_image(event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(
            Path(url.toLocalFile()).is_file() and is_image_file(Path(url.toLocalFile()))
            for url in event.mimeData().urls()
        )


class RecipePanel(Panel):
    def __init__(self):
        super().__init__("RecipePanel")
        self.setMinimumWidth(230)
        self.title = make_label("Packing Recipe", "PanelTitle")
        self.outputs_container = QWidget()
        self.outputs_layout = QVBoxLayout(self.outputs_container)
        self.outputs_layout.setContentsMargins(0, 0, 0, 0)
        self.outputs_layout.setSpacing(8)
        self.notes_container = QWidget()
        self.notes_layout = QVBoxLayout(self.notes_container)
        self.notes_layout.setContentsMargins(0, 0, 0, 0)
        self.notes_layout.setSpacing(6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.title)
        layout.addWidget(make_label("Outputs", "TinyHeader"))
        layout.addWidget(self.outputs_container)
        layout.addWidget(make_label("Import Notes", "TinyHeader"))
        layout.addWidget(self.notes_container)
        layout.addStretch(1)

    def set_preset(self, preset: Preset) -> None:
        clear_layout(self.outputs_layout)
        clear_layout(self.notes_layout)

        for output in preset.outputs:
            row = Panel("RecipeRow")
            row.setMinimumHeight(92)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 10, 10, 10)
            row_layout.setSpacing(6)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.addWidget(make_label(output.label, "RecipeOutput"))
            header.addStretch(1)
            suffix = Pill(output.suffix, "neutral")
            suffix.setMinimumWidth(76)
            header.addWidget(suffix)
            row_layout.addLayout(header)
            detail = make_label(output.description or self._channel_recipe(output.channels), "RecipeDetail")
            detail.setWordWrap(True)
            detail.setMinimumHeight(48)
            detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            row_layout.addWidget(detail)
            self.outputs_layout.addWidget(row)

        for note in preset.notes or ("No special import notes.",):
            note_label = make_label(note, "RecipeNote")
            note_label.setWordWrap(True)
            self.notes_layout.addWidget(note_label)

    @staticmethod
    def _channel_recipe(channels: dict[str, ChannelSource]) -> str:
        parts = []
        for channel, source in channels.items():
            if source.kind == "constant":
                parts.append(f"{channel.upper()}={source.value}")
            else:
                parts.append(f"{channel.upper()}={source.map_type or 'map'}")
        return ", ".join(parts)


class StatusBarPanel(Panel):
    openOutputRequested = pyqtSignal()

    def __init__(self):
        super().__init__("StatusPanel")
        self.status_label = make_label("Ready", "StatusLabel")
        self.progress = QProgressBar()
        self.progress.setObjectName("Progress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.percent_label = make_label("0%", "StatusPercent")
        self.toggle_log = QPushButton("Show Log")
        self.toggle_log.setObjectName("GhostButton")
        self.toggle_log.setCheckable(True)
        self.toggle_log.toggled.connect(self._toggle_log)
        self.open_output_button = QPushButton("Open Output")
        self.open_output_button.setObjectName("GhostButton")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.openOutputRequested.emit)
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("GhostButton")
        clear_button.clicked.connect(self.clear)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress, 1)
        top.addWidget(self.percent_label)
        top.addWidget(self.open_output_button)
        top.addWidget(self.toggle_log)
        top.addWidget(clear_button)

        self.log = QTextEdit()
        self.log.setObjectName("LogText")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(92)
        self.log.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.log)

    def append(self, message: str, *, status: bool = True) -> None:
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log.append(f"[{timestamp}] {message}")
        if status:
            self.status_label.setText(message)

    def set_progress(self, value: int) -> None:
        value = max(0, min(100, value))
        self.progress.setValue(value)
        self.percent_label.setText(f"{value}%")

    def set_output_available(self, available: bool) -> None:
        self.open_output_button.setEnabled(available)

    def clear(self) -> None:
        self.log.clear()

    def _toggle_log(self, checked: bool) -> None:
        self.log.setVisible(checked)
        self.toggle_log.setText("Hide Log" if checked else "Show Log")


class MaterialTextureStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        load_app_font(QApplication.instance())
        self.setWindowTitle("Material Texture Studio")
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1280, 820)
        self.setMinimumSize(1180, 720)

        self.single_input_folder: Path | None = None
        self.single_output_folder: Path | None = None
        self.batch_input_folder: Path | None = None
        self.batch_output_folder: Path | None = None
        self.materials: list[MaterialSet] = []
        self.batch_materials: list[MaterialSet] = []
        self.current_material: MaterialSet | None = None
        self.slots: dict[str, TextureSlotCard] = {}
        self._loading_slots = False
        self.last_export_folder: Path | None = None

        self._build_ui()
        self._apply_styles()
        self._load_settings()
        self._preset_changed()
        self.status.append("Ready. Choose folders or drop textures into the slots.")

    @property
    def preset(self) -> Preset:
        return PRESETS[self.preset_combo.currentData()]

    def _load_settings(self) -> None:
        path = settings_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        preset_id = data.get("preset")
        if preset_id in PRESETS:
            index = self.preset_combo.findData(preset_id)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)

        folders = data.get("folders", {})
        for attr, row_name, value in (
            ("single_input_folder", "single_source_row", folders.get("single_source")),
            ("single_output_folder", "single_output_row", folders.get("single_output")),
            ("batch_input_folder", "batch_source_row", folders.get("batch_source")),
            ("batch_output_folder", "batch_output_row", folders.get("batch_output")),
        ):
            if value:
                folder = Path(value)
                setattr(self, attr, folder)
                getattr(self, row_name).set_path(folder)

        options = data.get("options", {})
        checkbox_map = {
            "single_overwrite": self.single_overwrite_check,
            "single_folder_per_material": self.single_folder_per_material_check,
            "batch_mirror": self.batch_mirror_check,
            "batch_folder_per_material": self.batch_folder_per_material_check,
            "batch_overwrite": self.batch_overwrite_check,
            "batch_skip_incomplete": self.batch_skip_bad_check,
        }
        for key, checkbox in checkbox_map.items():
            if key in options:
                checkbox.setChecked(bool(options[key]))

        self._set_page(int(data.get("mode", 0)) if data.get("mode") in {0, 1} else 0)

    def _save_settings(self) -> None:
        path = settings_path()
        payload = {
            "preset": self.preset_combo.currentData(),
            "mode": self.pages.currentIndex() if hasattr(self, "pages") else 0,
            "folders": {
                "single_source": str(self.single_input_folder) if self.single_input_folder else "",
                "single_output": str(self.single_output_folder) if self.single_output_folder else "",
                "batch_source": str(self.batch_input_folder) if self.batch_input_folder else "",
                "batch_output": str(self.batch_output_folder) if self.batch_output_folder else "",
            },
            "options": {
                "single_overwrite": self.single_overwrite_check.isChecked(),
                "single_folder_per_material": self.single_folder_per_material_check.isChecked(),
                "batch_mirror": self.batch_mirror_check.isChecked(),
                "batch_folder_per_material": self.batch_folder_per_material_check.isChecked(),
                "batch_overwrite": self.batch_overwrite_check.isChecked(),
                "batch_skip_incomplete": self.batch_skip_bad_check.isChecked(),
            },
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self.status.append(f"Could not save app settings: {exc}", status=False)

    def closeEvent(self, event) -> None:
        self._save_settings()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root_widget = QWidget()
        root_widget.setObjectName("AppRoot")
        self.setCentralWidget(root_widget)

        root = QVBoxLayout(root_widget)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_single_page())
        self.pages.addWidget(self._build_batch_page())
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        self.status = StatusBarPanel()
        self.status.openOutputRequested.connect(self.open_last_output_folder)
        root.addWidget(self.status)

    def _build_header(self) -> QWidget:
        header = Panel("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        brand = QVBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        brand.setSpacing(3)
        brand.addWidget(make_label("Material Texture Studio", "AppTitle"))
        subtitle = make_label("Engine-ready texture packing for Unreal, Unity, and custom pipelines", "AppSubtitle")
        brand.addWidget(subtitle)
        layout.addLayout(brand, 1)

        preset_prompt = make_label("Choose your preset:", "PresetPrompt")
        preset_prompt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        preset_prompt.setMinimumWidth(170)
        layout.addWidget(preset_prompt)

        preset_box = QVBoxLayout()
        preset_box.setContentsMargins(0, 0, 0, 0)
        preset_box.setSpacing(6)
        preset_box.addWidget(make_label("Export Preset", "FieldLabel"))
        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("PresetCombo")
        self.preset_combo.setMinimumWidth(290)
        for preset_id, preset in PRESETS.items():
            self.preset_combo.addItem(preset.name, userData=preset_id)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        preset_box.addWidget(self.preset_combo)
        layout.addLayout(preset_box)
        return header

    def _build_sidebar(self) -> QWidget:
        sidebar = Panel("Sidebar")
        sidebar.setFixedWidth(190)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.single_nav = NavButton("Single Material")
        self.batch_nav = NavButton("Batch Conversion")
        self.single_nav.clicked.connect(lambda: self._set_page(0))
        self.batch_nav.clicked.connect(lambda: self._set_page(1))
        self.single_nav.setChecked(True)
        layout.addWidget(self.single_nav)
        layout.addWidget(self.batch_nav)
        layout.addSpacing(10)

        layout.addWidget(make_label("Current Preset", "TinyHeader"))
        self.sidebar_preset = make_label("", "SidebarDetail")
        self.sidebar_preset.setWordWrap(True)
        layout.addWidget(self.sidebar_preset)
        layout.addStretch(1)

        self.sidebar_ready = Pill("0 ready", "neutral")
        layout.addWidget(self.sidebar_ready)
        return sidebar

    def _build_single_page(self) -> QWidget:
        page = QWidget()
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(14)
        page_layout.addWidget(splitter)

        splitter.addWidget(self._build_single_left_panel())
        splitter.addWidget(self._build_single_slots_panel())
        self.recipe_panel = RecipePanel()
        splitter.addWidget(self.recipe_panel)
        splitter.setSizes([280, 560, 240])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        return page

    def _build_single_left_panel(self) -> QWidget:
        panel = Panel("Panel")
        panel.setMinimumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 18, 14)
        layout.setSpacing(12)

        layout.addWidget(make_label("Folders", "PanelTitle"))
        self.single_source_row = FolderPickerRow("Source Folder", "Texture folder")
        self.single_output_row = FolderPickerRow("Output Folder", "Export destination")
        self.single_source_row.folderChanged.connect(self._single_source_changed)
        self.single_output_row.folderChanged.connect(self._single_output_changed)
        layout.addWidget(self.single_source_row)
        layout.addWidget(self.single_output_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        self.auto_map_button = QPushButton("Auto Map")
        self.auto_map_button.setObjectName("PrimaryButton")
        self.auto_map_button.clicked.connect(self.scan_single_folder)
        clear = QPushButton("Clear Slots")
        clear.setObjectName("SecondaryButton")
        clear.clicked.connect(self.clear_slots)
        action_row.addWidget(clear)
        action_row.addWidget(self.auto_map_button)
        layout.addLayout(action_row)

        health_header = QHBoxLayout()
        health_header.setContentsMargins(0, 4, 0, 0)
        health_header.addWidget(make_label("Material Health", "PanelTitle"))
        health_header.addStretch(1)
        self.material_count = Pill("0 found", "neutral")
        health_header.addWidget(self.material_count)
        layout.addLayout(health_header)

        self.material_selector = QComboBox()
        self.material_selector.setObjectName("HealthSelector")
        self.material_selector.setEnabled(False)
        self.material_selector.currentIndexChanged.connect(self.select_material)
        layout.addWidget(self.material_selector)

        health_panel = Panel("HealthPanel")
        health_layout = QVBoxLayout(health_panel)
        health_layout.setContentsMargins(12, 12, 12, 12)
        health_layout.setSpacing(10)

        self.health_state = Pill("No material", "neutral")
        self.health_state.setMinimumWidth(110)
        health_layout.addWidget(self.health_state, alignment=Qt.AlignmentFlag.AlignLeft)

        self.health_source = make_label("Choose a source folder, then Auto Map.", "HealthText")
        health_layout.addWidget(self.health_source)

        self.health_maps = make_label("Maps: 0 assigned", "HealthText")
        health_layout.addWidget(self.health_maps)

        self.health_resolution = make_label("Resolution: n/a", "HealthText")
        health_layout.addWidget(self.health_resolution)

        self.health_missing = make_label("Required maps: n/a", "HealthText")
        health_layout.addWidget(self.health_missing)

        self.health_warnings = make_label("No warnings yet.", "HealthWarning")
        health_layout.addWidget(self.health_warnings)
        health_layout.addStretch(1)
        layout.addWidget(health_panel, 1)
        return panel

    def _build_single_slots_panel(self) -> QWidget:
        panel = Panel("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(make_label("Texture Inputs", "PanelTitle"))
        header.addStretch(1)
        self.single_warning = make_label("", "InlineWarning")
        header.addWidget(self.single_warning)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setObjectName("TransparentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setViewportMargins(0, 0, 16, 0)
        self.slot_container = QWidget()
        self.slot_container.setObjectName("Transparent")
        self.slot_layout = QVBoxLayout(self.slot_container)
        self.slot_layout.setContentsMargins(0, 0, 8, 0)
        self.slot_layout.setSpacing(8)
        scroll.setWidget(self.slot_container)
        layout.addWidget(scroll, 1)

        actions = Panel("ActionStrip")
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(14, 10, 14, 10)
        action_layout.setSpacing(8)
        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(14)
        self.single_overwrite_check = TickCheckBox("Overwrite")
        self.single_overwrite_check.setChecked(True)
        self.single_overwrite_check.setMinimumWidth(104)
        self.single_overwrite_check.setToolTip("Replace existing exported textures with the same names.")
        self.single_folder_per_material_check = TickCheckBox("Folder per material")
        self.single_folder_per_material_check.setChecked(True)
        self.single_folder_per_material_check.setMinimumWidth(150)
        self.single_folder_per_material_check.setToolTip("Create a separate output folder for each material.")
        option_row.addWidget(self.single_overwrite_check)
        option_row.addWidget(self.single_folder_per_material_check)
        option_row.addStretch(1)

        export_row = QHBoxLayout()
        export_row.setContentsMargins(0, 0, 0, 0)
        export_row.setSpacing(10)
        self.export_all_button = QPushButton("Export All")
        self.export_all_button.setObjectName("SecondaryButton")
        self.export_all_button.setMinimumWidth(104)
        self.export_all_button.clicked.connect(self.generate_single_all)
        self.export_selected_button = QPushButton("Export Selected")
        self.export_selected_button.setObjectName("PrimaryButton")
        self.export_selected_button.setMinimumWidth(132)
        self.export_selected_button.clicked.connect(self.generate_single_selected)
        export_row.addStretch(1)
        export_row.addWidget(self.export_all_button)
        export_row.addWidget(self.export_selected_button)
        action_layout.addLayout(option_row)
        action_layout.addLayout(export_row)
        layout.addWidget(actions)
        return panel

    def _build_batch_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        setup = Panel("Panel")
        setup_layout = QGridLayout(setup)
        setup_layout.setContentsMargins(14, 14, 14, 14)
        setup_layout.setHorizontalSpacing(12)
        setup_layout.setVerticalSpacing(12)
        self.batch_source_row = FolderPickerRow("Root Folder", "Folder containing material subfolders")
        self.batch_output_row = FolderPickerRow("Batch Output", "Export destination")
        self.batch_source_row.folderChanged.connect(self._batch_source_changed)
        self.batch_output_row.folderChanged.connect(self._batch_output_changed)
        setup_layout.addWidget(self.batch_source_row, 0, 0)
        setup_layout.addWidget(self.batch_output_row, 0, 1)

        self.batch_scan_button = QPushButton("Scan Subfolders")
        self.batch_scan_button.setObjectName("PrimaryButton")
        self.batch_scan_button.clicked.connect(self.scan_batch_folder)
        setup_layout.addWidget(self.batch_scan_button, 0, 2, alignment=Qt.AlignmentFlag.AlignBottom)
        setup_layout.setColumnStretch(0, 1)
        setup_layout.setColumnStretch(1, 1)
        root.addWidget(setup)

        summary = Panel("Panel")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 10, 14, 10)
        summary_layout.setSpacing(8)
        self.stat_total = Pill("0 total", "neutral")
        self.stat_ready = Pill("0 ready", "ready")
        self.stat_incomplete = Pill("0 incomplete", "warning")
        self.stat_exported = Pill("0 exported", "accent")
        summary_layout.addWidget(self.stat_total)
        summary_layout.addWidget(self.stat_ready)
        summary_layout.addWidget(self.stat_incomplete)
        summary_layout.addWidget(self.stat_exported)
        summary_layout.addStretch(1)
        root.addWidget(summary)

        table_panel = Panel("Panel")
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_layout.setSpacing(10)
        table_header = QHBoxLayout()
        table_header.addWidget(make_label("Batch Queue", "PanelTitle"))
        table_header.addStretch(1)
        self.batch_hint = make_label("No batch scan yet.", "MutedText")
        table_header.addWidget(self.batch_hint)
        table_layout.addLayout(table_header)
        self.batch_table = QTableWidget()
        self.batch_table.setObjectName("BatchTable")
        self.batch_table.setColumnCount(5)
        self.batch_table.setHorizontalHeaderLabels(["Material", "Source Folder", "Detected Maps", "Status", "Output Target"])
        for col, tooltip in {
            1: "Full source folder path is shown on hover.",
            4: "Full output target path is shown on hover.",
        }.items():
            header_item = self.batch_table.horizontalHeaderItem(col)
            if header_item:
                header_item.setToolTip(tooltip)
        self.batch_table.verticalHeader().setVisible(False)
        header = self.batch_table.horizontalHeader()
        header.setMinimumSectionSize(92)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(1, 170)
        header.resizeSection(4, 170)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.setShowGrid(False)
        table_layout.addWidget(self.batch_table, 1)
        root.addWidget(table_panel, 1)

        actions = Panel("ActionStrip")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(12, 10, 12, 10)
        action_layout.setSpacing(10)
        self.batch_mirror_check = TickCheckBox("Mirror subfolders")
        self.batch_mirror_check.setChecked(True)
        self.batch_mirror_check.setMinimumWidth(140)
        self.batch_mirror_check.setToolTip("Keep the same relative subfolder structure inside the batch output folder.")
        self.batch_mirror_check.stateChanged.connect(lambda: self.refresh_batch_table())
        self.batch_folder_per_material_check = TickCheckBox("Folder per material")
        self.batch_folder_per_material_check.setChecked(True)
        self.batch_folder_per_material_check.setMinimumWidth(150)
        self.batch_folder_per_material_check.setToolTip("Create a separate output folder for each detected material.")
        self.batch_overwrite_check = TickCheckBox("Overwrite")
        self.batch_overwrite_check.setChecked(True)
        self.batch_overwrite_check.setMinimumWidth(104)
        self.batch_overwrite_check.setToolTip("Replace existing exported textures with the same names.")
        self.batch_skip_bad_check = TickCheckBox("Skip incomplete")
        self.batch_skip_bad_check.setChecked(True)
        self.batch_skip_bad_check.setMinimumWidth(132)
        self.batch_skip_bad_check.setToolTip("Skip materials that are missing required maps instead of stopping the batch.")
        self.batch_export_button = QPushButton("Export Batch")
        self.batch_export_button.setObjectName("PrimaryButton")
        self.batch_export_button.setMinimumWidth(124)
        self.batch_export_button.clicked.connect(self.generate_batch)
        action_layout.addWidget(self.batch_mirror_check)
        action_layout.addWidget(self.batch_folder_per_material_check)
        action_layout.addWidget(self.batch_overwrite_check)
        action_layout.addWidget(self.batch_skip_bad_check)
        action_layout.addStretch(1)
        action_layout.addWidget(self.batch_export_button)
        root.addWidget(actions)
        return page

    def _set_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.single_nav.setChecked(index == 0)
        self.batch_nav.setChecked(index == 1)

    def _preset_changed(self) -> None:
        preset = self.preset
        self.sidebar_preset.setText(f"{preset.name}\n{preset.description}")
        if hasattr(self, "recipe_panel"):
            self.recipe_panel.set_preset(preset)
        self._rebuild_slots()
        if self.current_material:
            self._load_material_into_slots(self.current_material)
        self.refresh_batch_table()
        self._refresh_health_panel()
        self._refresh_actions()

    def _rebuild_slots(self) -> None:
        clear_layout(self.slot_layout)
        self.slots.clear()
        required = self._required_maps_for_preset(self.preset)
        for info in ordered_map_types_for_preset(self.preset):
            slot = TextureSlotCard(info.key, info.key in required)
            slot.fileChanged.connect(self.on_slot_changed)
            self.slots[info.key] = slot
            self.slot_layout.addWidget(slot)
        self.slot_layout.addStretch(1)

    def _single_source_changed(self, folder: str) -> None:
        self.single_input_folder = Path(folder)
        if not self.single_output_folder:
            self.single_output_folder = self.single_input_folder / "MaterialTextureStudio_Output"
            self.single_output_row.set_path(self.single_output_folder)
        self.scan_single_folder()

    def _single_output_changed(self, folder: str) -> None:
        self.single_output_folder = Path(folder)
        self._refresh_actions()

    def _batch_source_changed(self, folder: str) -> None:
        self.batch_input_folder = Path(folder)
        if not self.batch_output_folder:
            self.batch_output_folder = self.batch_input_folder / "MaterialTextureStudio_Batch_Output"
            self.batch_output_row.set_path(self.batch_output_folder)
        self.scan_batch_folder()

    def _batch_output_changed(self, folder: str) -> None:
        self.batch_output_folder = Path(folder)
        self.refresh_batch_table()
        self._refresh_actions()

    def scan_single_folder(self) -> None:
        if not self.single_input_folder:
            self.single_source_row.choose()
            return
        self.materials = detect_material_sets(self.single_input_folder, recursive=False, group_by_folder=False)
        if not self.materials:
            self.materials = [MaterialSet(name=self.single_input_folder.name, source_folder=self.single_input_folder)]
            self.status.append("No texture names matched. A manual material was created.")
        else:
            self.status.append(f"Folder scanned. Detected {len(self.materials)} material set(s).")

        self.material_selector.blockSignals(True)
        self.material_selector.clear()
        for material in self.materials:
            self.material_selector.addItem(material.name)
        self.material_selector.setEnabled(bool(self.materials))
        self.material_count.setText(f"{len(self.materials)} found")
        self.material_selector.blockSignals(False)
        self.material_selector.setCurrentIndex(0 if self.materials else -1)
        if self.materials:
            self.select_material(0)
        else:
            self._refresh_health_panel()
        self._refresh_actions()

    def select_material(self, row: int) -> None:
        if row < 0 or row >= len(self.materials):
            self.current_material = None
            self.clear_slots(emit=False)
            self._refresh_actions()
            return
        self.current_material = self.materials[row]
        self._load_material_into_slots(self.current_material)
        self.status.append(f"{self.current_material.name}: {self._status_for_material(self.current_material)}.")
        self._refresh_actions()

    def _load_material_into_slots(self, material: MaterialSet) -> None:
        self._loading_slots = True
        try:
            for map_type, slot in self.slots.items():
                slot.set_file(material.maps.get(map_type), emit=False)
        finally:
            self._loading_slots = False
        self._refresh_slot_warning()
        self._refresh_health_panel()

    def on_slot_changed(self, map_type: str, path_text: str) -> None:
        if self._loading_slots or not self.current_material:
            return
        if path_text:
            self.current_material.maps[map_type] = Path(path_text)
        else:
            self.current_material.maps.pop(map_type, None)
        self._refresh_slot_warning()
        self._refresh_health_panel()
        self._refresh_actions()

    def clear_slots(self, *, emit: bool = True) -> None:
        for slot in self.slots.values():
            slot.clear(emit=emit)
        if self.current_material and emit:
            for map_type in list(self.slots):
                self.current_material.maps.pop(map_type, None)
        self._refresh_slot_warning()
        self._refresh_health_panel()
        self._refresh_actions()

    def scan_batch_folder(self) -> None:
        if not self.batch_input_folder:
            self.batch_source_row.choose()
            return
        self.batch_materials = detect_material_sets_by_folder(self.batch_input_folder)
        ready = sum(1 for material in self.batch_materials if self._status_for_material(material) == "Ready")
        self.status.append(f"Batch scan found {len(self.batch_materials)} material set(s), {ready} ready.")
        self.refresh_batch_table()
        self._refresh_actions()

    def refresh_batch_table(self) -> None:
        if not hasattr(self, "batch_table"):
            return
        self.batch_table.setRowCount(0)
        for material in self.batch_materials:
            row = self.batch_table.rowCount()
            self.batch_table.insertRow(row)
            values = [
                material.name,
                str(material.source_folder or ""),
                ", ".join(self._friendly_map_names(material)) or "None",
                self._status_for_material(material),
                str(self._batch_target_root(material)) if self.batch_output_folder else "",
            ]
            for col, value in enumerate(values):
                display_value = table_path(value) if col in {1, 4} else value
                item = QTableWidgetItem(display_value)
                if col == 1:
                    item.setToolTip(f"Source folder:\n{value}" if value else "No source folder")
                elif col == 4:
                    item.setToolTip(f"Output target:\n{value}" if value else "Choose a batch output folder")
                elif col == 3:
                    warnings = validate_material(material, self.preset)
                    item.setToolTip("\n".join(warnings) if warnings else "Ready to export")
                else:
                    item.setToolTip(value)
                if col == 3:
                    item.setForeground(QColor(SUCCESS if value == "Ready" else WARNING))
                self.batch_table.setItem(row, col, item)
        self._refresh_batch_stats()

    def generate_single_selected(self) -> None:
        materials = [self.current_material.copy()] if self.current_material else []
        self._generate_materials(
            materials,
            self.single_output_folder,
            overwrite=self.single_overwrite_check.isChecked(),
            folder_per_material=self.single_folder_per_material_check.isChecked(),
            skip_bad=False,
        )

    def generate_single_all(self) -> None:
        self._generate_materials(
            [material.copy() for material in self.materials],
            self.single_output_folder,
            overwrite=self.single_overwrite_check.isChecked(),
            folder_per_material=self.single_folder_per_material_check.isChecked(),
            skip_bad=False,
        )

    def generate_batch(self) -> None:
        if not self.batch_materials:
            self.scan_batch_folder()
            if not self.batch_materials:
                return
        if not self.batch_output_folder:
            QMessageBox.warning(self, "Missing export folder", "Choose a batch export folder first.")
            return

        completed = 0
        skipped = 0
        output_paths: list[Path] = []
        export_warnings: list[str] = []
        skipped_details: list[str] = []
        total = len(self.batch_materials)
        self.status.set_progress(0)
        for index, material in enumerate(self.batch_materials, start=1):
            state = self._status_for_material(material)
            if state != "Ready" and self.batch_skip_bad_check.isChecked():
                skipped += 1
                skipped_details.append(f"{material.name}: {state}")
                self.status.append(f"Skipped {material.name}: {state}.")
                self.status.set_progress(int(index / total * 100))
                QApplication.processEvents()
                continue
            try:
                result = pack_material(
                    material,
                    self.preset,
                    self._batch_target_root(material),
                    overwrite=self.batch_overwrite_check.isChecked(),
                    folder_per_material=self.batch_folder_per_material_check.isChecked(),
                )
                completed += 1
                output_paths.extend(result.output_paths)
                export_warnings.extend(result.warnings)
                self.status.append(
                    f"Exported {result.material_name}: {len(result.output_paths)} texture(s)."
                )
                for warning in result.warnings:
                    self.status.append(warning, status=False)
            except Exception as exc:
                skipped += 1
                skipped_details.append(f"{material.name}: {exc}")
                self.status.append(f"Failed {material.name}: {exc}")
                if not self.batch_skip_bad_check.isChecked():
                    QMessageBox.critical(self, "Batch export failed", str(exc))
                    break
            self.status.set_progress(int(index / total * 100))
            QApplication.processEvents()
        self._refresh_batch_stats(exported=completed, skipped=skipped)
        if completed:
            self._set_last_export_folder(self.batch_output_folder)
        self._show_export_summary(
            title="Batch export complete",
            exported=completed,
            skipped=skipped,
            output_paths=output_paths,
            warnings=export_warnings,
            skipped_details=skipped_details,
        )

    def _generate_materials(
        self,
        materials: list[MaterialSet],
        output_folder: Path | None,
        *,
        overwrite: bool,
        folder_per_material: bool,
        skip_bad: bool,
    ) -> None:
        if not output_folder:
            QMessageBox.warning(self, "Missing export folder", "Choose an export folder first.")
            return
        if not materials:
            QMessageBox.warning(self, "No material", "Auto Map a folder or assign maps before exporting.")
            return

        completed = 0
        output_paths: list[Path] = []
        export_warnings: list[str] = []
        total = len(materials)
        self.status.set_progress(0)
        for index, material in enumerate(materials, start=1):
            try:
                result = pack_material(
                    material,
                    self.preset,
                    output_folder,
                    overwrite=overwrite,
                    folder_per_material=folder_per_material,
                )
                completed += 1
                output_paths.extend(result.output_paths)
                export_warnings.extend(result.warnings)
                self.status.append(
                    f"Exported {result.material_name}: {len(result.output_paths)} texture(s)."
                )
                for warning in result.warnings:
                    self.status.append(warning, status=False)
            except Exception as exc:
                self.status.append(f"Export failed for {material.name}: {exc}")
                if not skip_bad:
                    QMessageBox.critical(self, "Export failed", str(exc))
                    return
            self.status.set_progress(int(index / total * 100))
            QApplication.processEvents()
        if completed:
            self._set_last_export_folder(output_folder)
        self._show_export_summary(
            title="Texture pack generated",
            exported=completed,
            skipped=0,
            output_paths=output_paths,
            warnings=export_warnings,
            skipped_details=[],
        )

    def _batch_target_root(self, material: MaterialSet) -> Path:
        if not self.batch_output_folder:
            return Path()
        if not self.batch_mirror_check.isChecked() or not self.batch_input_folder or not material.source_folder:
            return self.batch_output_folder
        try:
            relative = material.source_folder.relative_to(self.batch_input_folder)
        except ValueError:
            relative = Path()
        return self.batch_output_folder / relative

    def _set_last_export_folder(self, folder: Path | None) -> None:
        self.last_export_folder = folder
        self.status.set_output_available(bool(folder and folder.exists()))

    def open_last_output_folder(self) -> None:
        if not self.last_export_folder:
            return
        self.last_export_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export_folder)))

    def _show_export_summary(
        self,
        *,
        title: str,
        exported: int,
        skipped: int,
        output_paths: list[Path],
        warnings: list[str],
        skipped_details: list[str],
    ) -> None:
        message = f"Exported {exported} material pack(s)."
        if skipped:
            message += f" Skipped {skipped}."
        if warnings:
            message += f" {len(warnings)} warning(s)."

        details: list[str] = []
        if output_paths:
            details.append("Generated files:")
            details.extend(str(path) for path in output_paths)
        if skipped_details:
            details.append("")
            details.append("Skipped or failed:")
            details.extend(skipped_details)
        if warnings:
            details.append("")
            details.append("Warnings:")
            details.extend(warnings)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(message)
        if output_paths and self.last_export_folder:
            box.setInformativeText(f"Output folder: {self.last_export_folder}")
        if details:
            box.setDetailedText("\n".join(details))
        box.exec()

    def _refresh_actions(self) -> None:
        current_ready = bool(self.current_material) and self._status_for_material(self.current_material) == "Ready"
        any_ready = any(self._status_for_material(material) == "Ready" for material in self.materials)
        self.export_selected_button.setEnabled(current_ready and bool(self.single_output_folder))
        self.export_all_button.setEnabled(any_ready and bool(self.single_output_folder))
        self.batch_export_button.setEnabled(bool(self.batch_materials) and bool(self.batch_output_folder))
        ready_total = sum(1 for material in self.materials if self._status_for_material(material) == "Ready")
        self.sidebar_ready.setText(f"{ready_total} ready")
        self.sidebar_ready.set_tone("ready" if ready_total else "neutral")
        self._refresh_slot_warning()

    def _refresh_slot_warning(self) -> None:
        if not self.current_material:
            self.single_warning.setText("")
            return
        status = self._status_for_material(self.current_material)
        self.single_warning.setText("" if status == "Ready" else status)

    def _refresh_health_panel(self) -> None:
        if not hasattr(self, "health_state"):
            return
        material = self.current_material
        if not material:
            self.health_state.setText("No material")
            self.health_state.set_tone("neutral")
            self.health_source.setText("Choose a source folder, then Auto Map.")
            self.health_source.setToolTip("")
            self.health_maps.setText("Maps: 0 assigned")
            self.health_resolution.setText("Resolution: n/a")
            self.health_missing.setText("Required maps: n/a")
            self.health_warnings.setText("No warnings yet.")
            return

        status = self._status_for_material(material)
        ready = status == "Ready"
        self.health_state.setText("Ready" if ready else "Needs maps")
        self.health_state.set_tone("ready" if ready else "warning")

        source = str(material.source_folder or self.single_input_folder or "")
        source_name = Path(source).name if source else "Manual assignment"
        self.health_source.setText(f"Source: {source_name}")
        self.health_source.setToolTip(source)

        friendly_maps = self._friendly_map_names(material)
        self.health_maps.setText(f"Maps: {len(material.maps)} assigned")
        self.health_maps.setToolTip(", ".join(friendly_maps) if friendly_maps else "No maps assigned")

        sizes = self._map_sizes(material)
        if sizes:
            unique_sizes = sorted(set(sizes.values()))
            size_text = f"{unique_sizes[0][0]}x{unique_sizes[0][1]}"
            if len(unique_sizes) > 1:
                size_text += f" (+{len(unique_sizes) - 1} more)"
            self.health_resolution.setText(f"Resolution: {size_text}")
            self.health_resolution.setToolTip(
                "\n".join(
                    f"{MAP_TYPES.get(key).label.split(' / ', 1)[0] if key in MAP_TYPES else key}: {size[0]}x{size[1]}"
                    for key, size in sorted(sizes.items())
                )
            )
        else:
            self.health_resolution.setText("Resolution: no readable textures")
            self.health_resolution.setToolTip("")

        required = self._required_maps_for_preset(self.preset)
        missing = sorted(required - set(material.maps))
        if missing:
            names = [MAP_TYPES[key].label.split(" / ", 1)[0] for key in missing if key in MAP_TYPES]
            self.health_missing.setText("Missing: " + compact_list(names, 1))
            self.health_missing.setToolTip(", ".join(names))
        else:
            self.health_missing.setText("Required: complete")
            self.health_missing.setToolTip("")

        warnings = self._health_warnings(material, sizes)
        self.health_warnings.setText(warnings[0].splitlines()[0] if warnings else "No warnings.")
        self.health_warnings.setToolTip("\n".join(warnings) if warnings else "")

    def _map_sizes(self, material: MaterialSet) -> dict[str, tuple[int, int]]:
        sizes: dict[str, tuple[int, int]] = {}
        for map_type, path in material.maps.items():
            try:
                with Image.open(path) as image:
                    sizes[map_type] = image.size
            except Exception:
                continue
        return sizes

    def _health_warnings(self, material: MaterialSet, sizes: dict[str, tuple[int, int]]) -> list[str]:
        warnings: list[str] = []
        if len(set(sizes.values())) > 1:
            grouped = [
                f"{MAP_TYPES.get(key).label.split(' / ', 1)[0] if key in MAP_TYPES else key}: {size[0]}x{size[1]}"
                for key, size in sorted(sizes.items())
            ]
            warnings.append(f"Warning: size mismatch ({len(set(sizes.values()))})\nDetails:\n" + "\n".join(grouped))
        unreadable = [key for key in material.maps if key not in sizes]
        if unreadable:
            labels = [MAP_TYPES.get(key).label.split(" / ", 1)[0] if key in MAP_TYPES else key for key in unreadable]
            warnings.append("Unreadable previews: " + ", ".join(labels))
        return warnings

    def _refresh_batch_stats(self, *, exported: int = 0, skipped: int = 0) -> None:
        total = len(self.batch_materials)
        ready = sum(1 for material in self.batch_materials if self._status_for_material(material) == "Ready")
        incomplete = total - ready
        self.stat_total.setText(f"{total} total")
        self.stat_ready.setText(f"{ready} ready")
        self.stat_incomplete.setText(f"{incomplete} incomplete")
        self.stat_exported.setText(f"{exported} exported" if not skipped else f"{exported} exported, {skipped} skipped")
        self.batch_hint.setText("No batch scan yet." if total == 0 else f"{ready} of {total} ready")

    def _friendly_map_names(self, material: MaterialSet) -> list[str]:
        return [MAP_TYPES[key].label.split(" / ", 1)[0] for key in sorted(material.maps) if key in MAP_TYPES]

    def _status_for_material(self, material: MaterialSet) -> str:
        missing = []
        for warning in validate_material(material, self.preset):
            if " needs " in warning:
                missing.append(warning.split(" needs ", 1)[1].rstrip("."))
        if missing:
            names = [MAP_TYPES.get(key).label.split(" / ", 1)[0] if key in MAP_TYPES else key for key in sorted(set(missing))]
            return "Missing " + ", ".join(names)
        return "Ready"

    def _required_maps_for_preset(self, preset: Preset) -> set[str]:
        required: set[str] = set()
        probe = MaterialSet(name="_empty")
        for warning in validate_material(probe, preset):
            if " needs " in warning:
                required.add(warning.split(" needs ", 1)[1].rstrip("."))
        return required

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget#AppRoot {{
                background: {APP_BG};
                color: {TEXT};
            }}

            QWidget {{
                color: {TEXT};
                font-family: "Comfortaa";
                font-size: 13px;
            }}

            #Header, #Sidebar, #Panel, #StatusPanel, #RecipePanel {{
                background: {PANEL_BG};
                border: 1px solid {BORDER};
                border-radius: {RADIUS}px;
            }}

            #ActionStrip {{
                background: {ELEVATED_BG};
                border: 1px solid {BORDER_SOFT};
                border-radius: {RADIUS}px;
            }}

            #Transparent, #TransparentScroll, QScrollArea > QWidget > QWidget {{
                background: transparent;
                border: none;
            }}

            #AppTitle {{
                color: {TEXT};
                font-size: 21px;
                font-weight: 650;
                letter-spacing: 0px;
            }}

            #AppSubtitle, #MutedText, #SidebarDetail, #RecipeDetail, #RecipeNote, #SlotPath {{
                color: {TEXT_MUTED};
            }}

            #PresetPrompt {{
                color: {TEXT};
                font-size: 13px;
                font-weight: 650;
            }}

            #PanelTitle {{
                color: {TEXT};
                font-size: 14px;
                font-weight: 650;
            }}

            #TinyHeader, #FieldLabel {{
                color: {TEXT_DIM};
                font-size: 11px;
                font-weight: 650;
                text-transform: uppercase;
            }}

            #PathEdit, QLineEdit, QComboBox {{
                background: {INPUT_BG};
                border: 1px solid {BORDER};
                border-radius: 8px;
                min-height: 32px;
                padding: 2px 10px;
                color: {TEXT};
                selection-background-color: {ACCENT_DARK};
            }}

            QComboBox::drop-down {{
                border: none;
                width: 28px;
            }}

            QPushButton {{
                background: {ELEVATED_BG};
                border: 1px solid #354252;
                border-radius: 8px;
                color: {TEXT};
                min-height: 32px;
                padding: 4px 12px;
            }}

            QPushButton:hover {{
                background: #223040;
                border-color: #42566A;
            }}

            QPushButton:disabled {{
                color: #607080;
                background: #141A21;
                border-color: #202A34;
            }}

            #PrimaryButton {{
                background: {ACCENT_DARK};
                border-color: #1687B6;
                color: #EAF8FF;
                font-weight: 650;
            }}

            #PrimaryButton:hover {{
                background: #0F6F94;
            }}

            #SecondaryButton {{
                background: #202936;
            }}

            #GhostButton {{
                background: transparent;
                border-color: {BORDER};
                color: {TEXT_MUTED};
            }}

            #NavButton {{
                background: transparent;
                border: 1px solid transparent;
                color: {TEXT_MUTED};
                text-align: left;
                padding-left: 12px;
                font-weight: 550;
            }}

            #NavButton:hover {{
                background: #1B242E;
                color: {TEXT};
            }}

            #NavButton:checked {{
                background: #102B3A;
                border-color: #1E7EA8;
                color: {TEXT};
            }}

            #Pill {{
                border-radius: 12px;
                padding: 2px 9px;
                background: #202936;
                border: 1px solid #344252;
                color: {TEXT_MUTED};
                font-size: 11px;
                font-weight: 650;
            }}

            #Pill[tone="accent"] {{
                background: rgba(56, 189, 248, 0.15);
                border-color: rgba(56, 189, 248, 0.42);
                color: {ACCENT};
            }}

            #Pill[tone="ready"] {{
                background: rgba(61, 220, 151, 0.12);
                border-color: rgba(61, 220, 151, 0.35);
                color: {SUCCESS};
            }}

            #Pill[tone="warning"], #Pill[tone="required"] {{
                background: rgba(240, 184, 90, 0.12);
                border-color: rgba(240, 184, 90, 0.36);
                color: {WARNING};
            }}

            #TextureSlotCard {{
                background: {ELEVATED_BG};
                border: 1px solid {BORDER};
                border-radius: {RADIUS}px;
            }}

            #TextureSlotCard[state="ready"] {{
                border-color: rgba(61, 220, 151, 0.36);
            }}

            #TextureSlotCard[state="warning"] {{
                border-color: rgba(240, 184, 90, 0.42);
            }}

            #TextureSlotCard[drag="true"] {{
                border-color: {ACCENT};
                background: #162636;
            }}

            #TexturePreview {{
                background: {INPUT_BG};
                border: 1px solid {BORDER};
                border-radius: 8px;
                color: {TEXT_DIM};
                font-size: 10px;
                font-weight: 700;
            }}

            #SlotTitle, #RecipeOutput {{
                color: {TEXT};
                font-weight: 650;
            }}

            #ColorHint {{
                color: {TEXT_DIM};
                font-size: 11px;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 2px 7px;
            }}

            #SlotState[tone="ready"] {{
                color: {SUCCESS};
            }}

            #SlotState[tone="warning"], #InlineWarning {{
                color: {WARNING};
            }}

            #SlotState[tone="muted"] {{
                color: {TEXT_DIM};
            }}

            #EmptyText {{
                color: {TEXT_DIM};
                border: 1px dashed {BORDER};
                border-radius: {RADIUS}px;
                padding: 16px;
            }}

            #HealthPanel {{
                background: {INPUT_BG};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}

            #HealthText {{
                color: {TEXT_MUTED};
                font-size: 12px;
                line-height: 145%;
            }}

            #HealthWarning {{
                color: {WARNING};
                font-size: 12px;
                line-height: 145%;
            }}

            QTableWidget, QTextEdit {{
                background: {INPUT_BG};
                border: 1px solid {BORDER};
                border-radius: 8px;
                color: {TEXT};
                selection-background-color: #123B50;
                selection-color: {TEXT};
                outline: none;
            }}

            QHeaderView::section {{
                background: {ELEVATED_BG};
                color: {TEXT_MUTED};
                border: none;
                border-bottom: 1px solid {BORDER};
                padding: 8px;
                font-weight: 650;
            }}

            QTableWidget::item {{
                border-bottom: 1px solid #1C2530;
                padding: 6px;
            }}

            QCheckBox {{
                color: {TEXT_MUTED};
                spacing: 7px;
            }}

            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 5px;
                border: 1px solid #465568;
                background: {INPUT_BG};
            }}

            QCheckBox::indicator:checked {{
                background: {ACCENT_DARK};
                border-color: {ACCENT};
            }}

            #RecipeRow {{
                background: {ELEVATED_BG};
                border: 1px solid {BORDER_SOFT};
                border-radius: 8px;
            }}

            #LogText {{
                font-family: "Comfortaa";
                font-size: 12px;
            }}

            #StatusLabel {{
                color: {TEXT_MUTED};
            }}

            #StatusPercent {{
                color: {TEXT_DIM};
                min-width: 34px;
            }}

            #Progress {{
                background: {INPUT_BG};
                border: 1px solid {BORDER};
                border-radius: 5px;
                height: 8px;
            }}

            #Progress::chunk {{
                background: {ACCENT};
                border-radius: 5px;
            }}

            QSplitter::handle:horizontal {{
                background: {APP_BG};
                width: 14px;
            }}

            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 2px;
            }}

            QScrollBar::handle:vertical {{
                background: #344454;
                border-radius: 4px;
                min-height: 30px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: #416074;
            }}

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: transparent;
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: transparent;
                border: none;
            }}

            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {{
                width: 0px;
                height: 0px;
            }}
            """
        )


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Material Texture Studio")
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    window = MaterialTextureStudio()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
