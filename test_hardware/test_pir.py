import RPi.GPIO as GPIO
import time

# PIR conectado al GPIO 24 (Pin 18)
PIN_PIR = 24

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_PIR, GPIO.IN)

print("--- Test PIR HC-SR501 ---")
print("Esperando movimiento... (presiona Ctrl+C para salir)")

try:
    while True:
        state = GPIO.input(PIN_PIR)
        if state == GPIO.HIGH:
            print("¡MOVIMIENTO DETECTADO!")
        else:
            print("Todo tranquilo...")
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\nTest finalizado.")
finally:
    GPIO.cleanup()
