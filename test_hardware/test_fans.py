import RPi.GPIO as GPIO
import time

# Pines L298N
PIN_IN1 = 17  # Fan 1
PIN_IN2 = 27  # Fan 1
PIN_ENA = 18  # Fan 1 PWM

PIN_IN3 = 22  # Fan 2
PIN_IN4 = 23  # Fan 2
PIN_ENB = 13  # Fan 2 PWM

GPIO.setmode(GPIO.BCM)
for pin in [PIN_IN1, PIN_IN2, PIN_ENA, PIN_IN3, PIN_IN4, PIN_ENB]:
    GPIO.setup(pin, GPIO.OUT)

pwm_a = GPIO.PWM(PIN_ENA, 1000)
pwm_b = GPIO.PWM(PIN_ENB, 1000)
pwm_a.start(0)
pwm_b.start(0)

def set_fan1(speed):
    GPIO.output(PIN_IN1, GPIO.HIGH)
    GPIO.output(PIN_IN2, GPIO.LOW)
    pwm_a.ChangeDutyCycle(speed)

def set_fan2(speed):
    GPIO.output(PIN_IN3, GPIO.HIGH)
    GPIO.output(PIN_IN4, GPIO.LOW)
    pwm_b.ChangeDutyCycle(speed)

def stop_fans():
    GPIO.output(PIN_IN1, GPIO.LOW)
    GPIO.output(PIN_IN2, GPIO.LOW)
    GPIO.output(PIN_IN3, GPIO.LOW)
    GPIO.output(PIN_IN4, GPIO.LOW)
    pwm_a.ChangeDutyCycle(0)
    pwm_b.ChangeDutyCycle(0)

print("--- Test Ventiladores (L298N) ---")
try:
    print("Encendiendo Ventilador 1 al 50%...")
    set_fan1(50)
    time.sleep(3)
    
    print("Encendiendo Ventilador 2 al 50%...")
    set_fan2(50)
    time.sleep(3)
    
    print("Aumentando ambos al 100%...")
    set_fan1(100)
    set_fan2(100)
    time.sleep(3)
    
    print("Apagando...")
    stop_fans()
    time.sleep(1)

except KeyboardInterrupt:
    pass
finally:
    pwm_a.stop()
    pwm_b.stop()
    GPIO.cleanup()
    print("Test finalizado.")
