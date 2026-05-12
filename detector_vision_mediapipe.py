# -*- coding: utf-8 -*-
"""
detector_vision_mediapipe.py — Detector de sueño con MediaPipe Face Mesh
=========================================================================
Analiza el feed de cámara en tiempo real y calcula:

  EAR  (Eye Aspect Ratio)    → ojos cerrados → dormido
  MAR  (Mouth Aspect Ratio)  → boca abierta → posible ronquido
  HEAD (Head Motion Score)   → traslación de landmarks entre frames → agitación

Estado de sueño emitido:
  - sleeping      (bool)  EAR < EAR_THRESH por N frames consecutivos
  - snoring_risk  (bool)  MAR > MAR_THRESH
  - head_moving   (bool)  delta_nariz > MOTION_THRESH
  - ear           (float) promedio de ambos ojos
  - mar           (float) boca
  - sleep_quality (str)   "PROFUNDO" / "LIGERO" / "DESPIERTO" / "AGITADO"

Landmarks MediaPipe Face Mesh usados:
  Ojo izq:  33,160,158,133,153,144
  Ojo der: 362,385,387,263,373,380
  Boca:    61,291,39,181,0,17
  Nariz:   1
"""

import time
import math
import collections

import cv2
import mediapipe as mp
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

# ── Índices de landmarks ───────────────────────────────────────────────────────
EYE_LEFT  = [33, 160, 158, 133, 153, 144]
EYE_RIGHT = [362, 385, 387, 263, 373, 380]
MOUTH_IDX = [61, 291, 39, 181, 0, 17]
NOSE_TIP  = 1

# ── Umbrales ───────────────────────────────────────────────────────────────────
EAR_THRESH      = 0.22   # debajo de esto = ojos cerrados
EAR_CONSEC_FRAMES = 20   # frames consecutivos con ojos cerrados → dormido
MAR_THRESH      = 0.55   # encima de esto = boca abierta (posible ronquido)
MOTION_THRESH   = 8.0    # px de desplazamiento de nariz entre frames

# ── Colores overlay ────────────────────────────────────────────────────────────
COLOR_OK      = (80, 220, 100)
COLOR_WARN    = (60, 180, 255)
COLOR_ALERT   = (60, 80, 255)
COLOR_TEXT_BG = (20, 20, 20)


def _ear(landmarks, indices, w, h) -> float:
    """Eye Aspect Ratio: (p2-p6 + p3-p5) / (2 * p1-p4)"""
    pts = [(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices]
    A = math.dist(pts[1], pts[5])
    B = math.dist(pts[2], pts[4])
    C = math.dist(pts[0], pts[3])
    return (A + B) / (2.0 * C) if C > 0 else 0.0


def _mar(landmarks, indices, w, h) -> float:
    """Mouth Aspect Ratio: abertura vertical / abertura horizontal"""
    pts = [(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices]
    A = math.dist(pts[2], pts[5])
    B = math.dist(pts[3], pts[4])
    C = math.dist(pts[0], pts[1])
    return (A + B) / (2.0 * C) if C > 0 else 0.0


class VisionDetector(QThread):
    """
    QThread que captura cámara, aplica MediaPipe Face Mesh y emite:
      frame_ready(QPixmap)      — frame con overlay dibujado
      status_ready(dict)        — métricas de sueño
    """

    frame_ready  = pyqtSignal(QPixmap)
    status_ready = pyqtSignal(dict)

    def __init__(self, camera_index: int = 0):
        super().__init__()
        self.camera_index = camera_index
        self.running = True

        self._ear_counter  = 0      # frames consecutivos con ojos cerrados
        self._sleeping     = False
        self._prev_nose    = None   # posición nariz frame anterior
        self._motion_buf   = collections.deque(maxlen=10)  # suavizar movimiento

        # MediaPipe Face Mesh
        self._mp_face_mesh = mp.solutions.face_mesh
        self._face_mesh    = self._mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._mp_draw = mp.solutions.drawing_utils
        self._draw_spec_pts = self._mp_draw.DrawingSpec(
            color=(60, 60, 80), thickness=1, circle_radius=1)

    # ── Helpers de dibujo ─────────────────────────────────────────────────────

    def _draw_text_box(self, frame, text: str, pos, color, scale=0.55):
        x, y = pos
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.rectangle(frame, (x - 4, y - th - 6), (x + tw + 4, y + 4),
                      COLOR_TEXT_BG, -1)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, 1, cv2.LINE_AA)

    def _draw_eye_contour(self, frame, landmarks, indices, w, h, color):
        pts = np.array(
            [(int(landmarks[i].x * w), int(landmarks[i].y * h))
             for i in indices], np.int32)
        cv2.polylines(frame, [pts], True, color, 1, cv2.LINE_AA)

    def _draw_mouth_contour(self, frame, landmarks, indices, w, h, color):
        pts = np.array(
            [(int(landmarks[i].x * w), int(landmarks[i].y * h))
             for i in indices], np.int32)
        cv2.polylines(frame, [pts], True, color, 1, cv2.LINE_AA)

    # ── Lógica principal ──────────────────────────────────────────────────────

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 20)

        time.sleep(0.5)
        if not cap.isOpened():
            self.status_ready.emit({
                "sleeping": False,
                "snoring_risk": False,
                "head_moving": False,
                "ear": 0.0,
                "mar": 0.0,
                "head_delta": 0.0,
                "sleep_quality": "CAMARA NO DISPONIBLE",
                "ear_counter": 0,
            })
            cap.release()
            self._face_mesh.close()
            return

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            h, w = frame.shape[:2]
            rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self._face_mesh.process(rgb)

            ear_val    = 0.0
            mar_val    = 0.0
            head_delta = 0.0
            snoring    = False
            moving     = False

            if result.multi_face_landmarks:
                lm = result.multi_face_landmarks[0].landmark

                # ── EAR ────────────────────────────────────────────────────────
                ear_l = _ear(lm, EYE_LEFT,  w, h)
                ear_r = _ear(lm, EYE_RIGHT, w, h)
                ear_val = (ear_l + ear_r) / 2.0

                eye_color = COLOR_WARN if ear_val < EAR_THRESH else COLOR_OK
                self._draw_eye_contour(frame, lm, EYE_LEFT,  w, h, eye_color)
                self._draw_eye_contour(frame, lm, EYE_RIGHT, w, h, eye_color)

                # ── MAR ────────────────────────────────────────────────────────
                mar_val = _mar(lm, MOUTH_IDX, w, h)
                snoring = mar_val > MAR_THRESH
                mouth_color = COLOR_ALERT if snoring else COLOR_OK
                self._draw_mouth_contour(frame, lm, MOUTH_IDX, w, h, mouth_color)

                # ── Head Motion ────────────────────────────────────────────────
                nose = lm[NOSE_TIP]
                nx, ny = int(nose.x * w), int(nose.y * h)
                if self._prev_nose is not None:
                    head_delta = math.dist((nx, ny), self._prev_nose)
                self._prev_nose = (nx, ny)
                self._motion_buf.append(head_delta)
                avg_motion = sum(self._motion_buf) / len(self._motion_buf)
                moving = avg_motion > MOTION_THRESH

                # ── EAR counter → estado dormido ───────────────────────────────
                if ear_val < EAR_THRESH:
                    self._ear_counter += 1
                else:
                    self._ear_counter = max(0, self._ear_counter - 2)

                self._sleeping = self._ear_counter >= EAR_CONSEC_FRAMES

                # ── Calidad de sueño ───────────────────────────────────────────
                if self._sleeping and not moving and not snoring:
                    quality = "PROFUNDO"
                    qcolor  = COLOR_OK
                elif self._sleeping and not moving:
                    quality = "LIGERO"
                    qcolor  = COLOR_WARN
                elif snoring:
                    quality = "RONCANDO"
                    qcolor  = COLOR_ALERT
                elif moving:
                    quality = "AGITADO"
                    qcolor  = COLOR_ALERT
                else:
                    quality = "DESPIERTO"
                    qcolor  = (200, 200, 200)

                # ── Overlay métricas ───────────────────────────────────────────
                self._draw_text_box(
                    frame, f"EAR: {ear_val:.3f}  MAR: {mar_val:.3f}",
                    (10, 30), COLOR_OK)
                self._draw_text_box(
                    frame, f"MOV: {avg_motion:.1f}px  CTR: {self._ear_counter}",
                    (10, 60), COLOR_WARN)
                self._draw_text_box(
                    frame, quality, (10, 95), qcolor, scale=0.75)

                # ── Emitir estado ──────────────────────────────────────────────
                status = {
                    "sleeping":      self._sleeping,
                    "snoring_risk":  snoring,
                    "head_moving":   moving,
                    "ear":           round(ear_val, 3),
                    "mar":           round(mar_val, 3),
                    "head_delta":    round(avg_motion, 1),
                    "sleep_quality": quality,
                    "ear_counter":   self._ear_counter,
                }
                self.status_ready.emit(status)

            else:
                # Sin cara detectada
                self._prev_nose = None
                self._ear_counter = max(0, self._ear_counter - 1)
                self._draw_text_box(frame, "Sin cara detectada",
                                    (10, 30), (100, 100, 100))
                self.status_ready.emit({
                    "sleeping": False, "snoring_risk": False,
                    "head_moving": False, "ear": 0.0, "mar": 0.0,
                    "head_delta": 0.0, "sleep_quality": "SIN DATOS",
                    "ear_counter": 0,
                })

            # ── Convertir a QPixmap y emitir ──────────────────────────────────
            rgb_out = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hh, ww, ch = rgb_out.shape
            qt_img = QImage(rgb_out.data, ww, hh, ch * ww, QImage.Format_RGB888)
            self.frame_ready.emit(QPixmap.fromImage(qt_img))

            time.sleep(0.04)  # ~25 fps máximo

        cap.release()
        self._face_mesh.close()

    def stop(self):
        self.running = False
        self.wait()
