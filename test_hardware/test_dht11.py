import time
import board
import adafruit_dht

# DHT11 conectado al GPIO 4 (Pin 7)
PIN_DHT = board.D4

dht_device = adafruit_dht.DHT11(PIN_DHT, use_pulseio=False)

print("--- Test DHT11 ---")
print("Leyendo datos... (presiona Ctrl+C para salir)")

try:
    while True:
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity
            if temperature is not None:
                print(f"Temperatura: {temperature:.1f} C, Humedad: {humidity:.1f} %")
            else:
                print("Esperando lectura valida...")
        except RuntimeError as error:
            # Los errores de lectura son comunes en DHT, simplemente reintentamos
            print(f"Error de lectura: {error.args[0]}")
        
        time.sleep(2.0)
except KeyboardInterrupt:
    print("\nTest finalizado.")
finally:
    dht_device.exit()
