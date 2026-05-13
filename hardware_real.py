# -*- coding: utf-8 -*-
"""
hardware_real.py — Controlador de hardware físico para Raspberry Pi 5
=====================================================================
Sensores:
  - DHT11 / Steren ARD-360 (GPIO 4, Pin 7)  → Temperatura + Humedad
  - PIR HC-SR501             (GPIO 24, Pin 18) → Movimiento (digital)

Actuadores — Módulo de Relevadores (para 2 ventiladores):
  - IN1 (Relé 1) → GPIO 17 (Pin 11) │ Enciende/apaga ventilador 1
  - IN2 (Relé 2) → GPIO 27 (Pin 13) │ Enciende/apaga ventilador 2

Pinout resumen (BCM):
  DHT11 DATA:   GPIO 4  (pin 7)
  PIR OUT:      GPIO 24 (pin 18)
  RELAY 1 IN:   GPIO 17 (pin 11)
  RELAY 2 IN:   GPIO 27 (pin 13)

Notas:
  - El módulo ARD-360 (DHT11) ya incluye resistencia pull-up; solo 3 pines.
  - Los módulos de relé suelen ser "Active LOW" (se encienden con LOW y apagan con HIGH).
  - Conectar los ventiladores al puerto Normalmente Abierto (NO) del relé.
"""

import threading
import time

# ── GPIO / Hardware imports — sólo disponibles en RPi ─────────────────────────
try:
    import RPi.GPIO as GPIO
    import adafruit_dht
    import board
    _HW_AVAILABLE = True
except ImportError:
    _HW_AVAILABLE = False
    print("[hardware_real] AVISO: Librerias RPi no disponibles -- modo stub activo.")


# ── Constantes GPIO (BCM) ──────────────────────────────────────────────────────

# DHT11 (Steren ARD-360)
PIN_DHT11    = 4     # GPIO 4 — Pin 7

# PIR HC-SR501
PIN_PIR      = 24    # GPIO 24 — Pin 18

# Módulo de Relevadores — Ventiladores
PIN_RELAY_1  = 17    # GPIO 17 — Pin 11 (Ventilador 1)
PIN_RELAY_2  = 27    # GPIO 27 — Pin 13 (Ventilador 2)

# (Los pines L298N fueron eliminados)

# Servos SG90 / similares
PIN_SERVO_1  = 5     # GPIO 5 — Pin 29
PIN_SERVO_2  = 6     # GPIO 6 — Pin 31

# PWM
FAN_PWM_FREQ = 1000  # Hz — frecuencia PWM para el L298N
FAN_SPEED_DEFAULT = 75  # % duty cycle por defecto cuando se encienden
SERVO_PWM_FREQ = 50  # Hz — periodo de ~20 ms para servos hobby
SERVO_MIN_DUTY = 2.5
SERVO_MAX_DUTY = 12.5


class HardwareReal:
    """
    Controlador de hardware real para Raspberry Pi 5.
    Expone la misma interfaz que HardwareSimulator para compatibilidad.

    Componentes:
      - DHT11 (ARD-360) → temperatura y humedad
      - PIR HC-SR501     → detección de movimiento (0 = sin mov, 1 = mov)
      - Relevadores + 2 ventiladores DC 12V
    """

    def __init__(self, btn_calor_callback=None, btn_frio_callback=None):
        # Valores cacheados — None mientras no hay lectura real del sensor
        self._temp = None   # DHT11: None hasta primera lectura exitosa
        self._hum  = None   # DHT11: None hasta primera lectura exitosa
        self._lux  = None   # Sin sensor de luz en este pinout
        self._mov  = 0.0    # PIR: 0.0 = sin movimiento, 1.0 = movimiento

        # Estado de actuadores
        self.fan_on        = False
        self._fan_speed    = FAN_SPEED_DEFAULT  # % 0–100
        self.humidifier_on = False  # No hay actuador de humedad en este pinout
        self.led_on        = False  # No hay LED en este pinout

        self._override_temp = None  # None = automático
        self.running = True

        self._btn_calor_cb = btn_calor_callback
        self._btn_frio_cb  = btn_frio_callback

        # Objetos hardware
        self._dht    = None
        self._pwm_a  = None  # PWM ventilador 1
        self._pwm_b  = None  # PWM ventilador 2
        self._servo_pwm = {}
        self.servo_angles = {1: 90, 2: 90}

        if _HW_AVAILABLE:
            self._init_gpio()
            self._init_dht()
        else:
            print("[hardware_real] Ejecutando en modo stub (sin hardware).")

        # Hilo lector de sensores
        self._read_thread = threading.Thread(
            target=self._sensor_loop, daemon=True)
        self._read_thread.start()

    # ── Inicialización ────────────────────────────────────────────────────────

    def _init_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # ── Ventiladores (Relevadores) ─────────────────────────────────────────
        # Los módulos de relé suelen activarse con LOW. Inicializamos en HIGH (apagado).
        GPIO.setup(PIN_RELAY_1, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(PIN_RELAY_2, GPIO.OUT, initial=GPIO.HIGH)

        # (PWM variables se mantienen en None porque ya no usamos L298N)
        self._pwm_a = None
        self._pwm_b = None

        # Servos: senal PWM solamente. Alimentar servos con fuente externa 5V.
        for idx, pin in ((1, PIN_SERVO_1), (2, PIN_SERVO_2)):
            GPIO.setup(pin, GPIO.OUT)
            pwm = GPIO.PWM(pin, SERVO_PWM_FREQ)
            pwm.start(0)
            self._servo_pwm[idx] = pwm

        # ── PIR HC-SR501 ──────────────────────────────────────────────────────
        GPIO.setup(PIN_PIR, GPIO.IN)
        # Detectar flanco de subida (PIR activa en HIGH)
        GPIO.add_event_detect(PIN_PIR, GPIO.BOTH,
                              callback=self._on_pir_change, bouncetime=200)

        print("[hardware_real] GPIO inicializado (Relés + PIR).")

    def _init_dht(self):
        """Inicializar sensor DHT11 con Adafruit CircuitPython."""
        try:
            # board.D4 corresponde a GPIO 4 en RPi
            self._dht = adafruit_dht.DHT11(board.D4, use_pulseio=False)
            print(f"[hardware_real] DHT11 OK (GPIO {PIN_DHT11}).")
        except Exception as e:
            self._dht = None
            print(f"[hardware_real] DHT11 error: {e}")

    # ── Callback PIR ──────────────────────────────────────────────────────────

    def _on_pir_change(self, channel):
        """Callback por interrupción del PIR HC-SR501."""
        state = GPIO.input(PIN_PIR)
        self._mov = 1.0 if state == GPIO.HIGH else 0.0
        estado = "MOVIMIENTO detectado" if state == GPIO.HIGH else "Sin movimiento"
        print(f"[hardware_real] PIR → {estado}")

    # ── Lectura de sensores ───────────────────────────────────────────────────

    def _read_dht11(self):
        """Lee temperatura y humedad del DHT11 (ARD-360)."""
        if not _HW_AVAILABLE or self._dht is None:
            return
        try:
            temp = self._dht.temperature
            hum  = self._dht.humidity
            if temp is not None and hum is not None:
                self._temp = round(float(temp), 1)
                self._hum  = round(float(hum), 1)
        except RuntimeError as e:
            # El DHT11 ocasionalmente lanza RuntimeError en lecturas rápidas
            print(f"[hardware_real] DHT11 read (ignorado): {e}")
        except Exception as e:
            print(f"[hardware_real] DHT11 error: {e}")

    def _sensor_loop(self):
        """Hilo principal de lectura de sensores cada 2 segundos.
        El DHT11 necesita al menos 1–2 s entre lecturas."""
        while self.running:
            self._read_dht11()
            self._auto_actuators()
            time.sleep(2.0)

    def _auto_actuators(self):
        """
        Logica automatica:
          - Si temp > 22 grados C y no hay override -> encender ventiladores
          - Si temp <= 22 grados C y no hay override -> apagar ventiladores
        Solo actua si hay lectura real (temp no es None).
        """
        if not _HW_AVAILABLE or self._temp is None:
            return
        if self._override_temp is None:
            if self._temp > 22:
                self.set_fan(True)
            else:
                self.set_fan(False)

    # ── Interfaz pública (compatible con HardwareSimulator) ───────────────────

    def get_temperature(self):
        """Retorna la temperatura en grados C leida del DHT11, o None si no hay hardware."""
        return self._temp

    def get_humidity(self):
        """Retorna la humedad relativa en % leida del DHT11, o None si no hay hardware."""
        return self._hum

    def get_light(self):
        """Sin sensor de luz en este pinout. Retorna None."""
        return None

    def get_movement(self) -> float:
        """Retorna 1.0 si el PIR detecta movimiento, 0.0 si no. 0.0 en stub."""
        return self._mov

    def set_fan(self, state: bool, speed: int = None):
        """
        Enciende/apaga ambos ventiladores via Relevadores.
        speed: ignorado, ya que los relés no soportan control de velocidad.
        """
        self.fan_on = state

        # Si se pasa speed, lo guardamos para compatibilidad con la UI, pero no hace nada
        if speed is not None:
            self._fan_speed = max(0, min(100, speed))

        if _HW_AVAILABLE:
            # Nota: Asumiendo relé "Active LOW" (LOW = encendido, HIGH = apagado)
            # Si tu relé es Active HIGH, cambia GPIO.LOW por GPIO.HIGH abajo, y viceversa.
            if state:
                GPIO.output(PIN_RELAY_1, GPIO.LOW)  # Encender
                GPIO.output(PIN_RELAY_2, GPIO.LOW)  # Encender
            else:
                GPIO.output(PIN_RELAY_1, GPIO.HIGH) # Apagar
                GPIO.output(PIN_RELAY_2, GPIO.HIGH) # Apagar

        print(f"[hardware_real] Ventiladores -> "
              f"{'ON (' + str(self._fan_speed) + '%)' if state else 'OFF'}")

    def set_fan_speed(self, speed: int):
        """Ajusta la velocidad (0-100%) - Ignorado en relés, guardado para compatibilidad UI."""
        self._fan_speed = max(0, min(100, speed))
        # Con relés no podemos cambiar el DutyCycle
        print(f"[hardware_real] Velocidad ventiladores -> {self._fan_speed}%")

    def set_servo_angle(self, servo_id: int, angle: float):
        """
        Mueve un servo a un angulo entre 0 y 180 grados.
        servo_id: 1 -> GPIO 5, 2 -> GPIO 6.
        """
        if servo_id not in (1, 2):
            raise ValueError("servo_id debe ser 1 o 2")

        angle = max(0.0, min(180.0, float(angle)))
        self.servo_angles[servo_id] = angle

        duty = SERVO_MIN_DUTY + (
            (SERVO_MAX_DUTY - SERVO_MIN_DUTY) * angle / 180.0
        )
        if _HW_AVAILABLE and servo_id in self._servo_pwm:
            self._servo_pwm[servo_id].ChangeDutyCycle(duty)
            time.sleep(0.35)
            self._servo_pwm[servo_id].ChangeDutyCycle(0)

        print(f"[hardware_real] Servo {servo_id} -> {angle:.0f} grados")

    def set_servos(self, angle_1: float = None, angle_2: float = None):
        """Mueve ambos servos; deja sin cambio el que reciba None."""
        if angle_1 is not None:
            self.set_servo_angle(1, angle_1)
        if angle_2 is not None:
            self.set_servo_angle(2, angle_2)

    def get_servo_angle(self, servo_id: int):
        if servo_id not in (1, 2):
            raise ValueError("servo_id debe ser 1 o 2")
        return self.servo_angles[servo_id]

    def set_humidifier(self, state: bool):
        """No hay actuador de humedad en este pinout. Solo actualiza estado."""
        self.humidifier_on = state
        print(f"[hardware_real] Humidificador (stub) -> {'ON' if state else 'OFF'}")

    def set_led(self, state: bool):
        """No hay LED en este pinout. Solo actualiza estado."""
        self.led_on = state
        print(f"[hardware_real] LED (stub) -> {'ON' if state else 'OFF'}")

    def force_temperature(self, temp: float):
        """Override manual desde la UI para control de ventiladores."""
        self._override_temp = "calor" if temp > 22 else "frio"
        self.set_fan(temp > 22)

    def clear_override(self):
        """Vuelve a modo automático."""
        self._override_temp = None

    def stop(self):
        self.running = False
        if _HW_AVAILABLE:
            # Apagar ventiladores
            self.set_fan(False)
            # (PWMs de L298N eliminados)
            for pwm in self._servo_pwm.values():
                pwm.ChangeDutyCycle(0)
                pwm.stop()
            # Liberar DHT11
            if self._dht:
                self._dht.exit()
            GPIO.cleanup()
        print("[hardware_real] Hardware detenido y GPIO limpiado.")
