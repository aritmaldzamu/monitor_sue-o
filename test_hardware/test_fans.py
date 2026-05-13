import RPi.GPIO as GPIO
import time

# Pines de Relevadores
PIN_RELAY_1 = 17  # Fan 1
PIN_RELAY_2 = 27  # Fan 2

GPIO.setmode(GPIO.BCM)

# Inicializar en HIGH (asumiendo que los relés son Active LOW, HIGH = apagado)
GPIO.setup(PIN_RELAY_1, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(PIN_RELAY_2, GPIO.OUT, initial=GPIO.HIGH)

def set_fan1(state):
    # state = True (encender), False (apagar)
    GPIO.output(PIN_RELAY_1, GPIO.LOW if state else GPIO.HIGH)

def set_fan2(state):
    GPIO.output(PIN_RELAY_2, GPIO.LOW if state else GPIO.HIGH)

def stop_fans():
    GPIO.output(PIN_RELAY_1, GPIO.HIGH)
    GPIO.output(PIN_RELAY_2, GPIO.HIGH)

print("--- Test Ventiladores (Relevadores) ---")
try:
    print("Encendiendo Ventilador 1...")
    set_fan1(True)
    time.sleep(3)
    
    print("Encendiendo Ventilador 2...")
    set_fan2(True)
    time.sleep(3)
    
    print("Apagando Ventilador 1...")
    set_fan1(False)
    time.sleep(2)

    print("Apagando Ventilador 2...")
    stop_fans()
    time.sleep(1)

except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()
    print("Test finalizado.")
