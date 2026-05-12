# -*- coding: utf-8 -*-
# Pinout activo (BCM):
#   DHT11 DATA : GPIO 4  (pin 7)
#   PIR OUT    : GPIO 24 (pin 18)
#   L298N IN1  : GPIO 17 (pin 11)
#   L298N IN2  : GPIO 27 (pin 13)
#   L298N ENA  : GPIO 18 (pin 12) PWM
#   L298N IN3  : GPIO 22 (pin 15)
#   L298N IN4  : GPIO 23 (pin 16)
#   L298N ENB  : GPIO 13 (pin 33) PWM
#   SERVO 1    : GPIO 5  (pin 29) PWM
#   SERVO 2    : GPIO 6  (pin 31) PWM
import sys
import time
import math
import collections
import csv
import openpyxl
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QMessageBox, QFileDialog,
    QPushButton, QTableWidgetItem
)
from PyQt5.QtCore import QTimer, Qt, QDateTime
from PyQt5.QtGui import QPixmap, QPainter, QPen, QBrush, QColor, QFont

import pyqtgraph as pg
from pyqtgraph import PlotWidget

from frontend import Ui_MainWindow
from hardware_real import HardwareReal
try:
    from detector_vision_mediapipe import VisionDetector
    VISION_ENGINE = "MediaPipe Face Mesh"
except Exception as exc:
    from detector_vision import VisionDetector
    VISION_ENGINE = f"Haar fallback ({exc})"
from firestore_crud import FirestoreManager, FirebaseSyncThread



class SleepScoreRing(QLabel):
    """Dibuja un anillo de puntuación de sueño con QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.score = 0
        self.setMinimumSize(200, 200)
        self.setMaximumSize(200, 200)

    def set_score(self, value: int):
        self.score = max(0, min(100, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        radius = min(cx, cy) - 18
        pen_w = 14

        # Track (fondo)
        painter.setPen(QPen(QColor("#1f1f24"), pen_w, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(cx - radius, cy - radius, radius * 2, radius * 2,
                        225 * 16, -270 * 16)

        # Progreso
        if self.score > 0:
            sweep = int(-270 * self.score / 100 * 16)
            color = QColor("#b8f2b8") if self.score >= 70 else (
                QColor("#e6d28e") if self.score >= 40 else QColor("#f28e8e"))
            painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(cx - radius, cy - radius, radius * 2, radius * 2,
                            225 * 16, sweep)

        # Texto central — puntuación
        painter.setPen(QColor("#ededf0"))
        font = QFont("JetBrains Mono", 28, QFont.Bold)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, -10, 0, -10), Qt.AlignCenter,
                         str(self.score))

        # Subtexto
        painter.setPen(QColor("#8a8a93"))
        font2 = QFont("JetBrains Mono", 9)
        painter.setFont(font2)
        painter.drawText(self.rect().adjusted(0, 40, 0, 40), Qt.AlignCenter,
                         "SCORE")

        painter.end()


class MiniBarsWidget(QLabel):
    """Dibuja mini barras de historial para un sensor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = collections.deque([0.5] * 20, maxlen=20)
        self.color = QColor("#ededf0")
        self.setMinimumSize(0, 56)
        self.setMaximumSize(16777215, 56)

    def push(self, value: float, vmin: float, vmax: float):
        rng = vmax - vmin if vmax != vmin else 1
        normalized = (value - vmin) / rng
        self.values.append(max(0.0, min(1.0, normalized)))
        self.update()

    def set_color(self, color: QColor):
        self.color = color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        n = len(self.values)
        bar_w = max(2, (w - n) // n)
        gap = 2

        for i, v in enumerate(self.values):
            x = i * (bar_w + gap)
            bar_h = max(2, int(v * (h - 4)))
            y = h - bar_h - 2

            alpha = int(80 + 175 * ((i + 1) / n))
            c = QColor(self.color)
            c.setAlpha(alpha)
            painter.fillRect(x, y, bar_w, bar_h, c)

        painter.end()


# ─── Main App ──────────────────────────────────────────────────────────────────

class SleepMonitorApp(QMainWindow):
    TEMP_MIN, TEMP_MAX = 10.0, 40.0
    HUM_MIN, HUM_MAX = 20.0, 90.0
    LUX_MIN, LUX_MAX = 0.0, 100.0
    MOV_MIN, MOV_MAX = 0.0, 1.0

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self._apply_readability_styles()

        # ── Estado interno ─────────────────────────────────────────────────────
        self.fan_active = False
        self._fan_speed = 75          # % velocidad ventiladores (PWM)
        self.session_start = datetime.now()
        self.sample_count = 0
        self.sample_interval_ms = 1000
        self.total_samples_target = 360
        self.ideal_temp_min = 18.0
        self.ideal_temp_max = 22.0
        self.ideal_hum_min = 40
        self.ideal_hum_max = 60
        self.lux_auto_threshold = 10
        self.history = {
            "temp": [], "hum": [], "lux": [], "mov": [], "ts": []
        }
        self.is_awake = False
        self.vision = None
        self.camera_active = False
        self._vision_engine = VISION_ENGINE
        self.vision_history = {
            "total": 0,
            "sleeping": 0,
            "awake": 0,
            "snoring": 0,
            "moving": 0,
            "no_face": 0,
            "ear": collections.deque(maxlen=600),
            "mar": collections.deque(maxlen=600),
            "head_delta": collections.deque(maxlen=600),
            "last_quality": "SIN DATOS",
        }
        self._active_chart_series = "all"
        self._pir_last = 0.0          # última lectura PIR

        # ── Hardware / Firebase ────────────────────────────────────────────────
        self.hardware = HardwareReal()
        self.db_manager = FirestoreManager()
        self.firebase_sync = FirebaseSyncThread(
            self.db_manager, self.hardware, None
        )
        self.firebase_sync.start()

        # ── Vision ────────────────────────────────────────────────────────────
        # La camara se inicia manualmente desde el boton del Dashboard.

        # ── Reemplazar scoreRing con widget custom ────────────────────────────
        self._setup_score_ring()

        # ── Reemplazar tempBars / humBars / luxBars / movBars ─────────────────
        self._setup_mini_bars()

        # ── Reemplazar chartArea con pyqtgraph ────────────────────────────────
        self._setup_chart()

        # ── Video label ───────────────────────────────────────────────────────
        self._setup_video_label()

        # ── Conectar botones ──────────────────────────────────────────────────
        self._connect_buttons()
        self._init_secondary_pages()

        # ── Timers ────────────────────────────────────────────────────────────
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        self.data_timer = QTimer(self)
        self.data_timer.timeout.connect(self._update_dashboard)
        self.data_timer.start(self.sample_interval_ms)

        # ── Primer render ─────────────────────────────────────────────────────
        self._update_clock()
        self._update_chips()

    # ─── Setup helpers ────────────────────────────────────────────────────────

    def _apply_readability_styles(self):
        self.setStyleSheet(self.styleSheet() + """
QLabel {
    color: #ededf0;
}
QLabel[role="cardSub"],
QLabel[role="actLabel"],
QLabel[role="pageSub"],
QLabel[role="unit"],
QLabel[role="placeholder"] {
    color: #c7c7cc;
}
QLabel[role="cardTitle"] {
    color: #d8d8dd;
}
QFrame[role="chip"] QLabel,
QLabel[role="chipText"] {
    color: #ededf0;
}
QLabel#brandMark,
QPushButton[nav="true"][active="true"],
QPushButton[variant="primary"] {
    color: #0b0b0c;
}
QPushButton[variant="ghost"],
QPushButton[nav="true"] {
    color: #ededf0;
}
""")
        dark_exceptions = {"brandMark"}
        non_text_labels = {"statusDot", "chipRecDot"}
        for label in self.findChildren(QLabel):
            name = label.objectName()
            if name in dark_exceptions or name in non_text_labels:
                continue
            if name.endswith("Badge"):
                continue
            role = label.property("role")
            color = "#ededf0"
            if role in {"cardSub", "actLabel", "pageSub", "unit", "placeholder"}:
                color = "#c7c7cc"
            elif role == "cardTitle":
                color = "#d8d8dd"
            label.setStyleSheet((label.styleSheet() or "") + f"; color: {color};")

    def _setup_score_ring(self):
        layout = self.ui.heroLayout
        old = self.ui.scoreRing
        self.score_ring = SleepScoreRing(self.ui.cardHero)
        layout.replaceWidget(old, self.score_ring)
        old.deleteLater()
        self.score_ring.set_score(78)

    def _setup_mini_bars(self):
        def _replace(old_widget, parent, layout, color_hex):
            bar = MiniBarsWidget(parent)
            bar.set_color(QColor(color_hex))
            layout.replaceWidget(old_widget, bar)
            old_widget.deleteLater()
            return bar

        self.bars_temp = _replace(
            self.ui.tempBars, self.ui.cardTemp, self.ui.tempLayout, "#c7c7cc")
        self.bars_hum = _replace(
            self.ui.humBars, self.ui.cardHum, self.ui.humLayout, "#9ecbff")
        self.bars_lux = _replace(
            self.ui.luxBars, self.ui.cardLux, self.ui.luxLayout, "#e6d28e")
        self.bars_mov = _replace(
            self.ui.movBars, self.ui.cardMov, self.ui.movLayout, "#f28e8e")

    def _setup_chart(self):
        pg.setConfigOption("background", "#0e0e10")
        pg.setConfigOption("foreground", "#5a5a62")

        self.plot_widget = PlotWidget()
        self.plot_widget.setMinimumHeight(160)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis("bottom").setLabel("Tiempo", units="min")
        self.plot_widget.getAxis("left").setLabel("Valor norm.")
        self.plot_widget.setYRange(0, 1, padding=0.05)

        self._curves = {
            "temp": self.plot_widget.plot(pen=pg.mkPen("#c7c7cc", width=2),
                                          name="Temp"),
            "hum":  self.plot_widget.plot(pen=pg.mkPen("#9ecbff", width=2),
                                          name="Hum"),
            "lux":  self.plot_widget.plot(pen=pg.mkPen("#e6d28e", width=2),
                                          name="Lux"),
            "mov":  self.plot_widget.plot(pen=pg.mkPen("#f28e8e", width=2),
                                          name="Mov"),
        }

        # Quitar placeholder y añadir plot al chartArea
        self.ui.chartPlaceholder.hide()
        self.ui.vboxlayout5.addWidget(self.plot_widget)

    def _setup_video_label(self):
        """El feed de video va en una etiqueta flotante sobre el score ring."""
        self.video_label = QLabel(self.ui.cardMov)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet(
            "background:#000; border:1px solid #242428; border-radius:8px;"
        )
        self.video_label.setMinimumHeight(180)
        self.video_label.setText("CAMARA INACTIVA")
        self.video_label.hide()  # oculto hasta abrir la camara
        self.ui.movLayout.insertWidget(5, self.video_label)

        self.btn_camera = QPushButton(self.ui.cardMov)
        self.btn_camera.setObjectName("btnOpenCamera")
        self.btn_camera.setText("ABRIR CAMARA")
        self.btn_camera.setCursor(Qt.PointingHandCursor)
        self.btn_camera.setProperty("variant", "primary")
        self.ui.movActBtns.addWidget(self.btn_camera)

    def _connect_buttons(self):
        ui = self.ui

        # Temperatura / Ventiladores (L298N)
        ui.btnTempCalor.clicked.connect(lambda: self.hardware.force_temperature(30.0))
        ui.btnTempFrio.clicked.connect(lambda: self.hardware.force_temperature(15.0))
        ui.btnTempFan.clicked.connect(self._toggle_fan)

        # Velocidad del ventilador (si existen los botones en la UI)
        try:
            ui.btnFanSpeedLow.clicked.connect(lambda: self._set_fan_speed(40))
            ui.btnFanSpeedMed.clicked.connect(lambda: self._set_fan_speed(70))
            ui.btnFanSpeedHigh.clicked.connect(lambda: self._set_fan_speed(100))
        except AttributeError:
            pass  # Botones opcionales — no rompen si no están en el .ui

        # Humedad (stub — no hay actuador físico en este pinout)
        ui.btnHumOn.clicked.connect(lambda: self.hardware.set_humidifier(True))
        ui.btnHumExtract.clicked.connect(lambda: self.hardware.set_humidifier(False))

        # Luz (stub — no hay LED en este pinout)
        ui.btnLuxOn.clicked.connect(lambda: self.hardware.set_led(True))
        ui.btnLuxOff.clicked.connect(lambda: self.hardware.set_led(False))
        ui.btnLuxAuto.clicked.connect(self._toggle_lux_auto)

        # Movimiento / visión
        ui.btnMovAwake.clicked.connect(lambda: self._on_vision_status(True))
        ui.btnMovSnooze.clicked.connect(self._snooze)
        self.btn_camera.clicked.connect(self._toggle_camera)

        # Gráfica – filtros
        ui.btnChartAll.clicked.connect(lambda: self._set_chart_series("all"))
        ui.btnChartTemp.clicked.connect(lambda: self._set_chart_series("temp"))
        ui.btnChartHum.clicked.connect(lambda: self._set_chart_series("hum"))
        ui.btnChartLux.clicked.connect(lambda: self._set_chart_series("lux"))
        ui.btnChartMov.clicked.connect(lambda: self._set_chart_series("mov"))

        # Hero actions
        ui.btnExportExcel.clicked.connect(self._export_excel)
        ui.btnReporte.clicked.connect(self._show_report)
        ui.btnHistorico.clicked.connect(self._show_historico)

        # Nav
        ui.btnNavDashboard.clicked.connect(lambda: self._nav("dashboard"))
        ui.btnNavHistorico.clicked.connect(lambda: self._nav("historico"))
        ui.btnNavConfig.clicked.connect(lambda: self._nav("config"))
        ui.btnNavReporte.clicked.connect(lambda: self._nav("reporte"))

        # Paginas secundarias
        ui.btnHistRefresh.clicked.connect(self._refresh_historico_page)
        ui.btnHistExportar.clicked.connect(self._export_excel)
        ui.btnCfgRestore.clicked.connect(lambda: self._restore_config_defaults())
        ui.btnCfgGuardar.clicked.connect(self._save_config)
        ui.btnRepExcel.clicked.connect(self._export_excel)
        ui.btnRepCsv.clicked.connect(self._export_csv)
        ui.btnRepPdf.clicked.connect(
            lambda: QMessageBox.information(
                self, "PDF",
                "Exportar a PDF aun no esta disponible. Usa Excel o CSV."
            )
        )

    def _init_secondary_pages(self):
        self.ui.tblHistorico.setSortingEnabled(False)
        self.ui.tblHistorico.verticalHeader().setVisible(False)
        self.ui.tblHistorico.setRowCount(0)
        self._restore_config_defaults(show_message=False)
        self._refresh_historico_page()
        self._refresh_report_page()

    # ─── Slot implementations ─────────────────────────────────────────────────

    def _toggle_fan(self):
        """Alterna ventiladores ON/OFF con la velocidad actual configurada."""
        self.fan_active = not self.fan_active
        self.hardware.set_fan(self.fan_active, speed=self._fan_speed)
        if self.fan_active:
            self.ui.btnTempFan.setStyleSheet(
                "background:#b8f2b8; color:#0b0b0c; border:1px solid #b8f2b8;")
        else:
            self.ui.btnTempFan.setStyleSheet("")

    def _set_fan_speed(self, speed: int):
        """Cambia la velocidad PWM de los ventiladores (0–100%)."""
        self._fan_speed = speed
        if self.fan_active:
            self.hardware.set_fan_speed(speed)
        print(f"[dashboard] Velocidad ventiladores → {speed}%")

    def _toggle_lux_auto(self):
        # Auto: apagar LED si hay luz suficiente, encender si es oscuro
        lux = self.hardware.get_light()
        if lux is None:
            QMessageBox.information(
                self, "Luz",
                "No hay sensor de luz configurado en este pinout."
            )
            return
        self.hardware.set_led(lux < self.lux_auto_threshold)
        self.ui.btnLuxAuto.setStyleSheet(
            "background:#e6d28e; color:#0b0b0c; border:1px solid #e6d28e;"
        )

    def _snooze(self):
        QMessageBox.information(self, "Snooze",
                                "Alarma silenciada por 5 minutos.")

    def _toggle_camera(self):
        if self.camera_active:
            self._stop_camera()
        else:
            self._start_camera()

    def _start_camera(self):
        try:
            self.vision = VisionDetector()
            self.vision.frame_ready.connect(self._on_frame)
            self.vision.status_ready.connect(self._on_vision_status)
            self.vision.start()
        except Exception as exc:
            self.vision = None
            self.camera_active = False
            QMessageBox.critical(
                self, "Camara",
                f"No se pudo iniciar la camara.\n\n{exc}"
            )
            return

        self.camera_active = True
        self.video_label.show()
        self.btn_camera.setText("CERRAR CAMARA")
        self.btn_camera.setProperty("variant", "ghost")
        self.btn_camera.style().unpolish(self.btn_camera)
        self.btn_camera.style().polish(self.btn_camera)
        self.ui.lblMovValue.setText("CAM")
        self.ui.lblMovBadge.setText("ANALIZANDO")
        self.ui.statusText.setText(f"Vision: {self._vision_engine}")

    def _stop_camera(self):
        if self.vision is not None:
            self.vision.stop()
            self.vision = None
        self.camera_active = False
        self.video_label.clear()
        self.video_label.setText("CAMARA INACTIVA")
        self.video_label.hide()
        self.btn_camera.setText("ABRIR CAMARA")
        self.btn_camera.setProperty("variant", "primary")
        self.btn_camera.style().unpolish(self.btn_camera)
        self.btn_camera.style().polish(self.btn_camera)
        self.ui.lblMovBadge.setText("CAMARA OFF")

    def _update_vision_history(self, status: dict):
        quality = status.get("sleep_quality", "SIN DATOS")
        sleeping = bool(status.get("sleeping", False))
        snoring = bool(status.get("snoring_risk", False))
        moving = bool(status.get("head_moving", False))
        has_face = quality != "SIN DATOS"

        self.vision_history["total"] += 1
        self.vision_history["last_quality"] = quality
        if not has_face:
            self.vision_history["no_face"] += 1
            return

        if sleeping:
            self.vision_history["sleeping"] += 1
        else:
            self.vision_history["awake"] += 1
        if snoring:
            self.vision_history["snoring"] += 1
        if moving:
            self.vision_history["moving"] += 1

        self.vision_history["ear"].append(float(status.get("ear", 0.0)))
        self.vision_history["mar"].append(float(status.get("mar", 0.0)))
        self.vision_history["head_delta"].append(
            float(status.get("head_delta", 0.0)))

    def _vision_summary(self):
        total = self.vision_history["total"]
        valid = total - self.vision_history["no_face"]
        if valid <= 0:
            return {
                "confidence": 0.0,
                "sleep_pct": 0.0,
                "awake_pct": 0.0,
                "snoring_pct": 0.0,
                "moving_pct": 0.0,
                "avg_ear": None,
                "avg_mar": None,
                "avg_head": None,
                "penalty": 0,
                "last_quality": self.vision_history["last_quality"],
            }

        avg_ear = (sum(self.vision_history["ear"]) /
                   len(self.vision_history["ear"])) if self.vision_history["ear"] else None
        avg_mar = (sum(self.vision_history["mar"]) /
                   len(self.vision_history["mar"])) if self.vision_history["mar"] else None
        avg_head = (sum(self.vision_history["head_delta"]) /
                    len(self.vision_history["head_delta"])) if self.vision_history["head_delta"] else None

        awake_pct = self.vision_history["awake"] / valid
        snoring_pct = self.vision_history["snoring"] / valid
        moving_pct = self.vision_history["moving"] / valid
        penalty = int((awake_pct * 18) + (snoring_pct * 12) + (moving_pct * 15))

        return {
            "confidence": valid / total if total else 0.0,
            "sleep_pct": self.vision_history["sleeping"] / valid,
            "awake_pct": awake_pct,
            "snoring_pct": snoring_pct,
            "moving_pct": moving_pct,
            "avg_ear": avg_ear,
            "avg_mar": avg_mar,
            "avg_head": avg_head,
            "penalty": min(30, penalty),
            "last_quality": self.vision_history["last_quality"],
        }

    def _set_chart_series(self, series: str):
        self._active_chart_series = series
        # Resaltar botón activo
        buttons = {
            "all": self.ui.btnChartAll, "temp": self.ui.btnChartTemp,
            "hum": self.ui.btnChartHum, "lux": self.ui.btnChartLux,
            "mov": self.ui.btnChartMov,
        }
        for k, btn in buttons.items():
            if k == series:
                btn.setProperty("variant", "primary")
            else:
                btn.setProperty("variant", "ghost")
            # Forzar re-apply del estilo
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh_chart()

    def _refresh_chart(self):
        series = self._active_chart_series
        show = {
            "all": ["temp", "hum", "lux", "mov"],
            "temp": ["temp"], "hum": ["hum"],
            "lux": ["lux"], "mov": ["mov"],
        }.get(series, ["temp", "hum", "lux", "mov"])

        n = len(self.history["ts"])
        xs = list(range(n))

        for key, curve in self._curves.items():
            if key in show and n > 0:
                ys = self.history[key]
                curve.setData(xs, ys)
                curve.show()
            else:
                curve.hide()

    def _export_excel(self):
        n = len(self.history["ts"])
        if n == 0:
            QMessageBox.warning(self, "Sin datos",
                                "Aún no hay datos para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", f"somnus_{datetime.now():%Y%m%d_%H%M}.xlsx",
            "Excel (*.xlsx)"
        )
        if not path:
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sleep Monitor"
        ws.append(["Muestra", "Timestamp", "Temp (°C)", "Humedad (%)",
                   "Luz (lux)", "Movimiento", "Estado"])
        for i in range(n):
            ws.append([
                i + 1,
                self.history["ts"][i],
                round(self._hist_temp(i), 1),
                round(self._hist_hum(i), 1),
                "SIN SENSOR",
                round(self.history["mov"][i], 3),
                "Despierto" if self.is_awake else "Durmiendo",
            ])
        wb.save(path)
        QMessageBox.information(self, "Exportado",
                                f"Datos guardados en:\n{path}")

    def _export_csv(self):
        n = len(self.history["ts"])
        if n == 0:
            QMessageBox.warning(self, "Sin datos",
                                "Aun no hay datos para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar CSV", f"somnus_{datetime.now():%Y%m%d_%H%M}.csv",
            "CSV (*.csv)"
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Muestra", "Timestamp", "Temp (C)",
                             "Humedad (%)", "Luz (lux)", "Movimiento"])
            for i in range(n):
                writer.writerow([
                    i + 1,
                    self.history["ts"][i],
                    round(self._hist_temp(i), 1),
                    round(self._hist_hum(i), 1),
                    "SIN SENSOR",
                    self.history["mov"][i],
                ])
        QMessageBox.information(self, "Exportado",
                                f"Datos guardados en:\n{path}")

    def _show_report(self):
        n = len(self.history["ts"])
        if n == 0:
            QMessageBox.information(self, "Reporte", "Sin datos aún.")
            return
        dur = (datetime.now() - self.session_start)
        h, rem = divmod(int(dur.total_seconds()), 3600)
        m = rem // 60
        temps = [v * (self.TEMP_MAX - self.TEMP_MIN) + self.TEMP_MIN
                 for v in self.history["temp"]]
        hums = [v * (self.HUM_MAX - self.HUM_MIN) + self.HUM_MIN
                for v in self.history["hum"]]
        msg = (
            f"📊 REPORTE DE SESIÓN\n"
            f"Duración: {h}h {m}m\n"
            f"Muestras: {n}\n\n"
            f"Temperatura promedio: {sum(temps)/len(temps):.1f}°C\n"
            f"Humedad promedio: {sum(hums)/len(hums):.1f}%\n"
            f"Estado actual: {'Despierto' if self.is_awake else 'Durmiendo'}\n"
            f"Score de sueño: {self.score_ring.score}/100"
        )
        QMessageBox.information(self, "Reporte de Sesión", msg)

    def _show_historico(self):
        QMessageBox.information(
            self, "Histórico",
            f"Total de muestras registradas en esta sesión: "
            f"{len(self.history['ts'])}\n"
            f"Usa 'Exportar a Excel' para obtener el historial completo."
        )

    def _nav(self, section: str):
        labels = {
            "dashboard": self.ui.btnNavDashboard,
            "historico": self.ui.btnNavHistorico,
            "config": self.ui.btnNavConfig,
            "reporte": self.ui.btnNavReporte,
        }
        for k, btn in labels.items():
            btn.setProperty("active", "true" if k == section else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if section == "dashboard" and self.camera_active:
            self.video_label.show()
        elif not self.camera_active:
            self.video_label.hide()

    # ─── Timers ───────────────────────────────────────────────────────────────

    def _show_report(self):
        self._nav("reporte")

    def _show_historico(self):
        self._nav("historico")

    def _nav(self, section: str):
        pages = {
            "dashboard": 0,
            "historico": 1,
            "config": 2,
            "reporte": 3,
        }
        labels = {
            "dashboard": self.ui.btnNavDashboard,
            "historico": self.ui.btnNavHistorico,
            "config": self.ui.btnNavConfig,
            "reporte": self.ui.btnNavReporte,
        }
        for key, button in labels.items():
            button.setChecked(key == section)
            button.setProperty("active", "true" if key == section else "false")
            button.style().unpolish(button)
            button.style().polish(button)

        self.ui.pages.setCurrentIndex(pages.get(section, 0))
        if section == "historico":
            self._refresh_historico_page()
        elif section == "reporte":
            self._refresh_report_page()

        if section == "config":
            self.video_label.show()
            self.video_label.raise_()
        else:
            self.video_label.hide()

    def _save_config(self):
        temp_min = self.ui.spnTempMin.value()
        temp_max = self.ui.spnTempMax.value()
        hum_min = self.ui.spnHumMin.value()
        hum_max = self.ui.spnHumMax.value()
        if temp_min >= temp_max or hum_min >= hum_max:
            QMessageBox.warning(
                self, "Configuracion",
                "El valor minimo debe ser menor que el maximo."
            )
            return

        self.sample_interval_ms = self.ui.spnIntervalo.value() * 1000
        self.total_samples_target = self.ui.spnTotal.value()
        self.ideal_temp_min = temp_min
        self.ideal_temp_max = temp_max
        self.ideal_hum_min = hum_min
        self.ideal_hum_max = hum_max
        self.lux_auto_threshold = self.ui.spnLuxMax.value()

        if hasattr(self, "data_timer"):
            self.data_timer.setInterval(self.sample_interval_ms)
        self._update_chips()
        QMessageBox.information(self, "Configuracion",
                                "Cambios guardados para esta sesion.")

    def _restore_config_defaults(self, show_message=True):
        self.ui.spnIntervalo.setValue(1)
        self.ui.spnTotal.setValue(360)
        self.ui.txtInicio.setText(self.session_start.strftime("%H:%M"))
        self.ui.spnTempMin.setValue(18.0)
        self.ui.spnTempMax.setValue(22.0)
        self.ui.spnHumMin.setValue(40)
        self.ui.spnHumMax.setValue(60)
        self.ui.spnLuxMax.setValue(10)
        self.ui.txtProyecto.setText("somnus-sleep")
        self.ui.txtColeccion.setText("lecturas")
        self.ui.txtCreds.setText(str(Path("serviceAccountKey.json")))
        self.ui.chkAutoStart.setChecked(True)
        self.ui.chkLive.setChecked(True)
        if show_message:
            self._save_config()

    def _hist_temp(self, index):
        return self.history["temp"][index] * (self.TEMP_MAX - self.TEMP_MIN) + self.TEMP_MIN

    def _hist_hum(self, index):
        return self.history["hum"][index] * (self.HUM_MAX - self.HUM_MIN) + self.HUM_MIN

    def _history_averages(self):
        n = len(self.history["ts"])
        if n == 0:
            return None, None
        temps = [self._hist_temp(i) for i in range(n)]
        hums = [self._hist_hum(i) for i in range(n)]
        return sum(temps) / n, sum(hums) / n

    def _movement_events(self):
        events = 0
        prev = 0.0
        for mov in self.history["mov"]:
            if mov >= 1.0 and prev < 1.0:
                events += 1
            prev = mov
        return events

    def _session_duration_text(self):
        dur = datetime.now() - self.session_start
        h, rem = divmod(int(dur.total_seconds()), 3600)
        m = rem // 60
        return f"{h}h {m:02d}m"

    def _refresh_historico_page(self):
        n = len(self.history["ts"])
        self.ui.lblKpiSesiones.setText("1" if n else "---")
        self.ui.lblKpiPromedio.setText(
            f"{self.score_ring.score}" if n else "---")
        self.ui.lblKpiHoras.setText(self._session_duration_text() if n else "---")
        self.ui.lblKpiLecturas.setText(str(n) if n else "0")

        table = self.ui.tblHistorico
        table.setRowCount(0)
        if n == 0:
            return

        rows = list(range(max(0, n - 100), n))
        table.setRowCount(len(rows))
        for row, idx in enumerate(reversed(rows)):
            values = [
                str(idx + 1),
                self.history["ts"][idx],
                f"{self._hist_temp(idx):.1f} C",
                f"{self._hist_hum(idx):.1f} %",
                "SIN SENSOR",
                "MOV" if self.history["mov"][idx] >= 1.0 else "---",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, col, item)
        table.resizeColumnsToContents()

    def _refresh_report_page(self):
        n = len(self.history["ts"])
        vision = self._vision_summary()
        if n == 0:
            if vision["confidence"] >= 0.15:
                score = self.score_ring.score
                calidad = ("Reparador" if score >= 70 else
                           "Regular" if score >= 40 else "Deficiente")
                self.ui.lblRepScore.setText(f"{score} / 100 - {calidad}")
            else:
                self.ui.lblRepScore.setText("SIN DATOS")
            self.ui.lblRepFecha.setText("Esperando lecturas reales de sensores.")
            self.ui.label22.setText("Temp media  ---")
            self.ui.label23.setText("Hum media  ---")
            self.ui.label24.setText("Luz media  SIN SENSOR")
            self.ui.label25.setText("Despertares  ---")
            self.ui.label28.setText("- Sin lecturas reales suficientes para analizar temperatura.")
            self.ui.label29.setText("- Sin lecturas reales suficientes para analizar humedad.")
            self.ui.label30.setText(
                f"- Vision facial: {vision['last_quality']} "
                f"(confianza {vision['confidence'] * 100:.0f} %)."
            )
            self.ui.label31.setText(
                "- La vision participa en el score cuando hay cara visible suficiente."
            )
            return

        avg_temp, avg_hum = self._history_averages()
        score = self.score_ring.score
        calidad = ("Reparador" if score >= 70 else
                   "Regular" if score >= 40 else "Deficiente")
        self.ui.lblRepScore.setText(f"{score} / 100 - {calidad}")
        self.ui.lblRepFecha.setText(
            f"Sesion del {self.session_start:%d/%m/%Y, %H:%M} - "
            f"duracion {self._session_duration_text()}"
        )
        self.ui.label22.setText(f"Temp media  {avg_temp:.1f} C")
        self.ui.label23.setText(f"Hum media  {avg_hum:.0f} %")
        self.ui.label24.setText("Luz media  SIN SENSOR")
        self.ui.label25.setText(f"Despertares  {self._movement_events()}")
        self.ui.label28.setText(
            f"- Temperatura promedio: {avg_temp:.1f} C "
            f"(ideal {self.ideal_temp_min:.1f}-{self.ideal_temp_max:.1f} C)."
        )
        self.ui.label29.setText(
            f"- Humedad promedio: {avg_hum:.0f} % "
            f"(ideal {self.ideal_hum_min}-{self.ideal_hum_max} %)."
        )
        self.ui.label30.setText(
            f"- Vision: dormido {vision['sleep_pct'] * 100:.0f} %, "
            f"despierto {vision['awake_pct'] * 100:.0f} %, "
            f"roncando {vision['snoring_pct'] * 100:.0f} %, "
            f"agitacion {vision['moving_pct'] * 100:.0f} %."
        )
        self.ui.label31.setText(
            f"- Penalizacion facial aplicada: -{vision['penalty']} pts "
            f"(confianza {vision['confidence'] * 100:.0f} %)."
        )

    def _update_clock(self):
        now = QDateTime.currentDateTime()
        self.ui.clockLbl.setText(now.toString("HH:mm:ss"))
        self._update_chips()

    def _update_chips(self):
        dur = datetime.now() - self.session_start
        h, rem = divmod(int(dur.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        self.ui.chipInicioTxt.setText(
            f"Inicio  {self.session_start:%H:%M}")
        self.ui.chipMuestraTxt.setText(
            f"Muestra  {self.sample_count}/{self.total_samples_target}")
        self.ui.chipIntervaloTxt.setText(
            f"Intervalo  {self.sample_interval_ms // 1000} s")
        self.ui.chipFirestoreTxt.setText(
            f"Firestore  {'✓' if self.db_manager.connected else '✗'}")
        self.ui.chipRecTxt.setText(
            f"Grabando  {h:02d}:{m:02d}:{s:02d}")

    def _update_dashboard(self):
        # ── Leer valores reales del hardware (None si no hay sensor) ───────────
        temp = self.hardware.get_temperature()   # DHT11 o None
        hum  = self.hardware.get_humidity()      # DHT11 o None
        mov_raw = self.hardware.get_movement()   # PIR: 0.0 o 1.0
        mov = float(mov_raw) if mov_raw is not None else 0.0
        self._pir_last = mov

        # ── Etiquetas ─────────────────────────────────────────────────────────
        self.ui.lblTempValue.setText(f"{temp:.1f}" if temp is not None else "---")
        self.ui.lblHumValue.setText(f"{hum:.1f}"   if hum  is not None else "---")
        self.ui.lblLuxValue.setText("N/A")          # Sin sensor LDR
        pir_texto = "MOV" if mov >= 1.0 else "---"
        self.ui.lblMovValue.setText(pir_texto)

        # ── Badges ────────────────────────────────────────────────────────────
        if temp is not None:
            self._update_badge(self.ui.lblTempBadge, temp, self.ideal_temp_min,
                               self.ideal_temp_max, "OPTIMO", "ALERTA")
        else:
            self._set_badge_no_data(self.ui.lblTempBadge)

        if hum is not None:
            self._update_badge(self.ui.lblHumBadge, hum, self.ideal_hum_min,
                               self.ideal_hum_max, "OPTIMO", "ALERTA")
        else:
            self._set_badge_no_data(self.ui.lblHumBadge)

        # Luz: sin sensor
        self.ui.lblLuxBadge.setText("SIN SENSOR")
        self.ui.lblLuxBadge.setStyleSheet(
            "color:#8a8a93; border:1px solid #3a3a42;"
            " border-radius:10px; padding:3px 8px;")

        self._update_mov_badge(mov)

        # ── Mini bars (solo si hay lectura real) ──────────────────────────────
        if temp is not None:
            self.bars_temp.push(temp, self.TEMP_MIN, self.TEMP_MAX)
        if hum is not None:
            self.bars_hum.push(hum, self.HUM_MIN, self.HUM_MAX)
        self.bars_mov.push(mov, self.MOV_MIN, self.MOV_MAX)

        has_environment = temp is not None and hum is not None
        has_vision = self._vision_summary()["confidence"] >= 0.15

        # ── Historial (solo si hay datos reales de ambos sensores) ────────────
        if has_environment:
            self.history["temp"].append(
                (temp - self.TEMP_MIN) / (self.TEMP_MAX - self.TEMP_MIN))
            self.history["hum"].append(
                (hum - self.HUM_MIN) / (self.HUM_MAX - self.HUM_MIN))
            self.history["lux"].append(0.0)
            self.history["mov"].append(mov)
            self.history["ts"].append(datetime.now().strftime("%H:%M:%S"))
            self.sample_count += 1

            # Mantener solo las ultimas 8 horas (28800 muestras a 1/seg)
            max_samples = 28800
            for k in self.history:
                if len(self.history[k]) > max_samples:
                    self.history[k] = self.history[k][-max_samples:]

            # Score de sueno solo con datos reales
            self._compute_sleep_score(temp, hum, mov)
            if self.ui.pages.currentWidget() == self.ui.pageHistorico:
                self._refresh_historico_page()
            elif self.ui.pages.currentWidget() == self.ui.pageReporte:
                self._refresh_report_page()
        elif has_vision:
            self._compute_sleep_score(None, None, mov)
            if self.ui.pages.currentWidget() == self.ui.pageReporte:
                self._refresh_report_page()
        else:
            # Sin datos: mostrar score en 0 y mensaje de espera
            self.score_ring.set_score(0)
            self.ui.lblHeroBig.setText("Esperando sensores...")
            if self.ui.pages.currentWidget() == self.ui.pageReporte:
                self._refresh_report_page()


        # Gráfica
        self._refresh_chart()

        # Chips
        self._update_chips()

        # Status bar Firebase
        if self.db_manager.connected:
            self.ui.statusText.setText("Firestore · en línea")
            self.ui.statusDot.setStyleSheet(
                "background:#b8f2b8; border-radius:4px;"
                " min-width:8px; max-width:8px; min-height:8px; max-height:8px;")
        else:
            self.ui.statusText.setText("Firestore · sin conexión")
            self.ui.statusDot.setStyleSheet(
                "background:#f28e8e; border-radius:4px;"
                " min-width:8px; max-width:8px; min-height:8px; max-height:8px;")

    def _update_badge(self, label, value, low, high, ok_text, bad_text):
        if low <= value <= high:
            label.setText(ok_text)
            label.setStyleSheet(
                "color:#b8f2b8; border:1px solid #2a4d2a;"
                " border-radius:10px; padding:3px 8px;")
        else:
            label.setText(bad_text)
            label.setStyleSheet(
                "color:#e6d28e; border:1px solid #5a4f2a;"
                " background:#1f1c10; border-radius:10px; padding:3px 8px;")

    def _set_badge_no_data(self, label):
        """Badge gris cuando el sensor no tiene lectura real."""
        label.setText("SIN DATOS")
        label.setStyleSheet(
            "color:#8a8a93; border:1px solid #3a3a42;"
            " border-radius:10px; padding:3px 8px;")

    def _update_mov_badge(self, mov: float):
        """PIR HC-SR501: digital — 0.0 = sin movimiento, 1.0 = movimiento."""
        lbl = self.ui.lblMovBadge
        if mov >= 1.0:
            lbl.setText("ACTIVO")
            lbl.setStyleSheet(
                "color:#f28e8e; border:1px solid #5a2a2a;"
                " background:#1f1010; border-radius:10px; padding:3px 8px;")
            # Si hay movimiento detectado → marcar como despierto
            self._on_vision_status(True)
        else:
            lbl.setText("QUIETO")
            lbl.setStyleSheet(
                "color:#b8f2b8; border:1px solid #2a4d2a;"
                " border-radius:10px; padding:3px 8px;")

    def _compute_sleep_score(self, temp, hum, mov):
        """
        Score 0-100 basado en datos reales del DHT11 y PIR HC-SR501.
        Solo se llama cuando temp y hum tienen valores reales (no None).
        """
        score = 100

        # Temperatura: óptima 18-22°C (DHT11)
        if temp is not None:
            if temp < self.ideal_temp_min:
                score -= min(30, int((self.ideal_temp_min - temp) * 5))
            elif temp > self.ideal_temp_max:
                score -= min(30, int((temp - self.ideal_temp_max) * 5))

        # Humedad: óptima 40-60% (DHT11)
        if hum is not None:
            if hum < self.ideal_hum_min:
                score -= min(20, int((self.ideal_hum_min - hum) * 1))
            elif hum > self.ideal_hum_max:
                score -= min(20, int((hum - self.ideal_hum_max) * 1))

        # Movimiento PIR: digital (0 o 1) → penaliza fuerte si hay mov
        # mov=1.0 → -35 pts (señal clara de que el usuario está despierto)
        score -= int(mov * 35)

        vision = self._vision_summary()
        if vision["confidence"] >= 0.15:
            score -= vision["penalty"]

        score = max(0, min(100, int(score)))

        # Actualizar la etiqueta hero
        dur = datetime.now() - self.session_start
        h, rem = divmod(int(dur.total_seconds()), 3600)
        m = rem // 60
        calidad = ("Reparador" if score >= 70 else
                   "Regular" if score >= 40 else "Deficiente")
        self.ui.lblHeroBig.setText(
            f"{calidad} — sesión de {h}h {m:02d}m")
        self.score_ring.set_score(score)

    # ─── Vision callbacks ─────────────────────────────────────────────────────

    def _on_frame(self, pixmap: QPixmap):
        scaled = pixmap.scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.video_label.setPixmap(scaled)

    def _on_vision_status(self, status):
        if isinstance(status, dict):
            self._update_vision_history(status)
            quality = status.get("sleep_quality", "SIN DATOS")
            if quality == "CAMARA NO DISPONIBLE":
                self.ui.lblMovValue.setText("---")
                self.ui.lblMovBadge.setText("SIN CAMARA")
                self.ui.statusText.setText("Vision: camara no disponible")
                self.camera_active = False
                self.btn_camera.setText("ABRIR CAMARA")
                self.btn_camera.setProperty("variant", "primary")
                self.btn_camera.style().unpolish(self.btn_camera)
                self.btn_camera.style().polish(self.btn_camera)
                return
            sleeping = bool(status.get("sleeping", False))
            snoring = bool(status.get("snoring_risk", False))
            moving = bool(status.get("head_moving", False))

            self.is_awake = not sleeping and quality != "SIN DATOS"
            self.firebase_sync.set_awake_status(self.is_awake)
            self.ui.lblMovValue.setText("RON" if snoring else ("Zzz" if sleeping else "OK"))
            self.ui.lblMovBadge.setText(quality)

            details = (
                f"EAR {status.get('ear', 0):.3f} | "
                f"MAR {status.get('mar', 0):.3f} | "
                f"MOV {status.get('head_delta', 0):.1f}px"
            )
            if snoring:
                self.ui.statusText.setText(f"Vision: posible ronquido - {details}")
            elif sleeping:
                self.ui.statusText.setText(f"Vision: dormido - {details}")
            elif moving:
                self.ui.statusText.setText(f"Vision: agitado - {details}")
            elif quality == "SIN DATOS":
                self.ui.statusText.setText("Vision: sin cara detectada")
            else:
                self.ui.statusText.setText(f"Vision: despierto - {details}")
            return

        self.is_awake = bool(status)
        self.firebase_sync.set_awake_status(self.is_awake)
        if self.is_awake:
            self.ui.lblMovBadge.setText("DESPIERTO")
            self.ui.statusText.setText("Usuario Despierto")
        else:
            self.ui.lblMovBadge.setText("DORMIDO")
            self.ui.statusText.setText("Usuario Durmiendo")

    # ─── Close ────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self.data_timer.stop()
        self.clock_timer.stop()
        self.hardware.stop()
        if self.vision is not None:
            self.vision.stop()
        self.firebase_sync.stop()
        event.accept()


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SleepMonitorApp()
    window.show()
    sys.exit(app.exec_())
