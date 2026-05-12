import RPi.GPIO as GPIO
import time

# Pines Servos
PIN_SERVO1 = 5
PIN_SERVO2 = 6

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SERVO1, GPIO.OUT)
GPIO.setup(PIN_SERVO2, GPIO.OUT)

pwm1 = GPIO.PWM(PIN_SERVO1, 50) # 50Hz
pwm2 = GPIO.PWM(PIN_SERVO2, 50)
pwm1.start(0)
pwm2.start(0)

def set_angle(pwm, angle):
    duty = 2.5 + (angle / 18.0)
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.5)
    pwm.ChangeDutyCycle(0) # Detener señal para evitar vibración

print("--- Test Servos SG90 ---")
try:
    print("Moviendo Servo 1 a 0, 90, 180...")
    set_angle(pwm1, 0)
    set_angle(pwm1, 90)
    set_angle(pwm1, 180)
    set_angle(pwm1, 90)
    
    print("Moviendo Servo 2 a 0, 90, 180...")
    set_angle(pwm2, 0)
    set_angle(pwm2, 90)
    set_angle(pwm2, 180)
    set_angle(pwm2, 90)

except KeyboardInterrupt:
    pass
finally:
    pwm1.stop()
    pwm2.stop()
    GPIO.cleanup()
    print("Test finalizado.")
