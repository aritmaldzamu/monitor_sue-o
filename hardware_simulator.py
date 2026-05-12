import random
import time
import threading

class HardwareSimulator:
    """
    Simulador de hardware para desarrollo en PC.
    Expone la misma interfaz que HardwareReal (RPi).
    Componentes simulados:
      - DHT11   → temperatura + humedad
      - PIR HC-SR501 → movimiento digital (0.0 / 1.0)
      - L298N + 2 ventiladores DC brushless
    """
    def __init__(self):
        # Simulated sensor states
        self.temperature = 21.0
        self.humidity = 50.0
        self.light = 5.0
        self._movement = 0.0   # PIR: 0.0 = quieto, 1.0 = movimiento

        # Actuator states
        self.fan_on = False
        self._fan_speed = 75   # % duty cycle PWM (L298N ENA/ENB)
        self.humidifier_on = False
        self.led_on = False
        self.servo_angles = {1: 90, 2: 90}

        # Simulation flags
        self.running = True
        
        # Thread to simulate natural environmental changes
        self.sim_thread = threading.Thread(target=self._simulate_environment, daemon=True)
        self.sim_thread.start()
        
    def _simulate_environment(self):
        while self.running:
            time.sleep(2)

            # Temperatura: ventiladores la bajan si están ON
            if self.fan_on:
                self.temperature -= random.uniform(0.1, 0.3)
            else:
                self.temperature += random.uniform(-0.1, 0.2)

            # Humedad
            if self.humidifier_on:
                self.humidity += random.uniform(0.5, 1.5)
            else:
                self.humidity += random.uniform(-0.5, 0.2)

            # Luz
            if self.led_on:
                self.light = 50.0 + random.uniform(-2, 2)
            else:
                self.light = 5.0 + random.uniform(-1, 1)

            # PIR simulado: ~10% probabilidad de detectar movimiento
            self._movement = 1.0 if random.random() < 0.10 else 0.0

            # Mantener rangos válidos
            self.temperature = max(10, min(40, self.temperature))
            self.humidity = max(20, min(90, self.humidity))
            self.light = max(0, min(100, self.light))

    def get_temperature(self):
        return round(self.temperature, 1)

    def get_humidity(self):
        return int(self.humidity)

    def get_light(self) -> float:
        return round(self.light, 1)

    def get_movement(self) -> float:
        """PIR HC-SR501 simulado: 0.0 = sin movimiento, 1.0 = movimiento."""
        return self._movement

    def set_fan(self, state: bool, speed: int = None):
        """Enciende/apaga ventiladores. speed=0-100 (PWM L298N)."""
        self.fan_on = state
        if speed is not None:
            self._fan_speed = max(0, min(100, speed))

    def set_fan_speed(self, speed: int):
        """Ajusta velocidad PWM sin cambiar el estado on/off."""
        self._fan_speed = max(0, min(100, speed))

    def set_humidifier(self, state: bool):
        self.humidifier_on = state

    def set_led(self, state: bool):
        self.led_on = state

    def set_servo_angle(self, servo_id: int, angle: float):
        if servo_id not in (1, 2):
            raise ValueError("servo_id debe ser 1 o 2")
        self.servo_angles[servo_id] = max(0.0, min(180.0, float(angle)))

    def set_servos(self, angle_1: float = None, angle_2: float = None):
        if angle_1 is not None:
            self.set_servo_angle(1, angle_1)
        if angle_2 is not None:
            self.set_servo_angle(2, angle_2)

    def get_servo_angle(self, servo_id: int):
        if servo_id not in (1, 2):
            raise ValueError("servo_id debe ser 1 o 2")
        return self.servo_angles[servo_id]

    def force_temperature(self, temp: float):
        self.temperature = temp

    def stop(self):
        self.running = False
