# Guía de Conexiones — Sleep Monitor (Raspberry Pi 5)

Esta guía detalla cómo conectar cada sensor y actuador a los pines GPIO (BCM) de tu Raspberry Pi 5.

## 1. Sensores

| Componente | Pin BCM | Pin Físico | Notas |
| :--- | :--- | :--- | :--- |
| **DHT11 (Temp/Hum)** | GPIO 4 | Pin 7 | Conectar a 3.3V o 5V y GND. |
| **PIR HC-SR501** | GPIO 24 | Pin 18 | Conectar a 5V y GND. La señal es de 3.3V. |

## 2. Actuadores (Módulo de Relevadores para Ventiladores)

Los ventiladores se controlarán mediante un módulo de relevadores de 4 canales. Utilizaremos solo 2 canales (IN1 e IN2).
**Importante:** Conecta los ventiladores al puerto Normalmente Abierto (NO) del relé para que estén apagados por defecto. 
Si el relé requiere alimentación separada, recuerda compartir el GND.

| Módulo Relé Pin | Pin BCM | Pin Físico | Función |
| :--- | :--- | :--- | :--- |
| **IN1 (Relé 1)** | GPIO 17 | Pin 11 | Enciende/Apaga Ventilador 1 |
| **IN2 (Relé 2)** | GPIO 27 | Pin 13 | Enciende/Apaga Ventilador 2 |
| **VCC** | - | 5V | Alimentación del módulo (5V de la RPi) |
| **GND** | - | GND | GND de la RPi |

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
