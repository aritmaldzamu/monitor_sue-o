# Cambios de Hardware: Puente H (L298N) a Relevadores

Este archivo documenta la migración del control de los ventiladores, pasando de un controlador de motor L298N a un módulo de relevadores de 4 canales.

## Archivos Modificados

1. **`hardware_real.py`**:
   - **Eliminado**: Control PWM (frecuencia, duty cycle) y pines de dirección (IN1, IN2, ENA, IN3, IN4, ENB) específicos del L298N.
   - **Agregado**: Control digital (encendido/apagado) usando `PIN_RELAY_1` (GPIO 17) y `PIN_RELAY_2` (GPIO 27).
   - **Lógica**: Se ajustó para manejar relés "Active LOW", donde enviar `GPIO.LOW` enciende el relé y `GPIO.HIGH` lo apaga. La función `set_fan_speed` ahora es ignorada a nivel de hardware pero se mantiene para no romper la interfaz con `dashboard.py`.

2. **`test_hardware/test_fans.py`**:
   - Reescribió completamente el script de prueba. Ahora inicializa los pines de relé en HIGH y alterna a LOW para probar el encendido de los ventiladores 1 y 2.

3. **`CONNECTION_GUIDE.md`**:
   - Se actualizó la sección 2 (Actuadores) para reflejar los nuevos pines y las instrucciones de conexión (uso del puerto Normalmente Abierto [NO] y pin Común [COM] del relé).

## Verificación Recomendada Post-Pull

Al hacer `git pull` en la Raspberry Pi, verifica lo siguiente:
- [ ] Ejecutar `python test_hardware/test_fans.py` hace sonar el "clic" de los relés y enciende los ventiladores uno por uno.
- [ ] La interfaz gráfica (`dashboard.py`) aún puede encender/apagar los ventiladores mediante el botón de calor/frío (aunque ignore el control de porcentaje de velocidad).
- [ ] Asegurarse de que el GND del módulo de relés está compartido con el GND de la Raspberry Pi.
