# Guía de Conexiones — Sleep Monitor (Raspberry Pi 5)

Esta guía detalla cómo conectar cada sensor y actuador a los pines GPIO (BCM) de tu Raspberry Pi 5.

## 1. Sensores

| Componente | Pin BCM | Pin Físico | Notas |
| :--- | :--- | :--- | :--- |
| **DHT11 (Temp/Hum)** | GPIO 4 | Pin 7 | Conectar a 3.3V o 5V y GND. |
| **PIR HC-SR501** | GPIO 24 | Pin 18 | Conectar a 5V y GND. La señal es de 3.3V. |

## 2. Actuadores (Ventiladores via L298N)

El L298N requiere una fuente externa (ej. 12V). **Recuerda unir el GND de la fuente con el GND de la Raspberry Pi.**

| L298N Pin | Pin BCM | Pin Físico | Función |
| :--- | :--- | :--- | :--- |
| **ENA** | GPIO 18 | Pin 12 | Velocidad Ventilador 1 (PWM) |
| **IN1** | GPIO 17 | Pin 11 | Dirección Ventilador 1 |
| **IN2** | GPIO 27 | Pin 13 | Dirección Ventilador 1 |
| **ENB** | GPIO 13 | Pin 33 | Velocidad Ventilador 2 (PWM) |
| **IN3** | GPIO 22 | Pin 15 | Dirección Ventilador 2 |
| **IN4** | GPIO 23 | Pin 16 | Dirección Ventilador 2 |

## 3. Servos SG90

Conectar a 5V externo preferiblemente, pero compartiendo GND con la Raspberry Pi.

| Componente | Pin BCM | Pin Físico | Notas |
| :--- | :--- | :--- | :--- |
| **Servo 1** | GPIO 5 | Pin 29 | Señal (Naranja/Amarillo) |
| **Servo 2** | GPIO 6 | Pin 31 | Señal (Naranja/Amarillo) |

---

## Pruebas Paso a Paso

He creado scripts individuales en la carpeta `test_hardware/` para que pruebes cada componente por separado antes de abrir el Dashboard:

1. `python test_hardware/test_dht11.py`
2. `python test_hardware/test_pir.py`
3. `python test_hardware/test_fans.py`
4. `python test_hardware/test_servos.py`
