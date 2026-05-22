# 🫀 BioSignalSimulator Pro

**Simulador portátil de señales fisiológicas sintéticas para entrenamiento clínico y validación de equipos biomédicos**

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Platform](https://img.shields.io/badge/platform-ESP32-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**Grupo #22:** Scarlet Sánchez y Rafael Mata  
**Institución:** Escuela Superior Politécnica del Litoral (ESPOL)  
**Trabajo de Titulación - Ingeniería en Mecatrónica**

---

## 📋 Descripción

BioSignalSimulator Pro es un dispositivo portátil que genera señales biomédicas sintéticas con morfología clínicamente representativa. Diseñado para:

- 🎓 **Entrenamiento clínico**: Estudiantes de medicina e ingeniería biomédica
- 🔧 **Validación de equipos**: Prueba de monitores y dispositivos médicos
- 📚 **Investigación**: Desarrollo de algoritmos de procesamiento de señales

### Señales Generadas

| Señal | Modelo | Condiciones | Rango |
|-------|--------|-------------|-------|
| **ECG** | McSharry ECGSYN | 9 (Normal, Taquicardia, Bradicardia, FA, FV, PVC, Bloqueo, ST↑, ST↓) | -0.5 a +1.5 mV |
| **EMG** | Fuglevand MU | 6 (Reposo, Leve, Moderada, Fuerte, Temblor, Fatiga) | -5.0 a +5.0 mV |
| **PPG** | Suma de Gaussianas | 6 (Normal, Arritmia, Baja perfusión, Alta perfusión, Vasoconstricción, SpO2 bajo) | 800-1200 mV |

---

## 🚀 Características

- ✅ **Pantalla táctil 7"** - Visualización en tiempo real con waveforms
- ✅ **Salida analógica BNC** - 0-3.3V para conexión a osciloscopios/equipos
- ✅ **Batería recargable** - ~4 horas de autonomía
- ✅ **Parámetros ajustables** - HR, amplitud, ruido, HRV en tiempo real
- ✅ **Múltiples condiciones** - Patologías pre-configuradas por señal
- ✅ **Portátil** - Diseño compacto con carcasa impresa 3D

---

## 🛠️ Hardware

### Componentes Principales

| Componente | Función |
|------------|---------|
| ESP32 WROOM-32 | Microcontrolador dual-core @ 240 MHz |
| Nextion NX8048T070 | Display táctil 7" 800×480 |
| 2× 18650 Li-ion | Alimentación (5200 mAh en paralelo) |
| LM358 | Buffer salida analógica (seguidor de voltaje) |
| CD4051 | Multiplexor analógico para filtros RC selectivos |
| XL6009 | Regulador Step-Up 5V (η≈92%) |
| IP5306 + BMS 1S 3A | Carga USB-C y protección batería |
| Fusible 1.5A | Protección sobrecorriente a salida 5V |
| Filtro LC | 22µH + 1µF + 470nF (reduce ruido switching) |

### Diagrama de Conexiones

```
USB-C → IP5306 → BMS 1S 3A → Baterías 2×18650 → Switch → XL6009 → [Fusible 1.5A] → [Filtro LC] → ESP32 + Nextion
                 (paralelo)                                          22µH+1µF+470nF
                                                                            ↓
                                         ESP32 DAC (GPIO25) → CD4051 → RC Filter → BNC
                                                                ↑
                                                     GPIO32/33 (S0/S1)
```

### Cadena de Acondicionamiento de Señal

```
DAC 8-bit → LM358 Buffer → CD4051 Multiplexor → Filtro RC Selectivo → BNC
  (2 kHz)    (ganancia ×1)   CH0: 6.8kΩ (ECG, Fc=23.4Hz)    C=1µF
                             CH1: 1.0kΩ (EMG, Fc=159Hz)     compartido
                             CH2: 25kΩ  (PPG, Fc=6.37Hz)
```

> **Nota:** Se usa LM358 por disponibilidad local en Ecuador. El MCP6002 (rail-to-rail) sería ideal para aprovechar el rango completo 0-3.3V del DAC.

---

## 📱 Interfaz de Usuario

### Flujo de Navegación

```
PORTADA → MENÚ → Selección Señal (ECG/EMG/PPG)
                        ↓
              Selección Condición
                        ↓
              WAVEFORM (visualización)
                   ↓         ↓
              [Valores]  [Parámetros]
```

### Controles

- **Play/Pause/Stop**: Control de simulación
- **Valores**: Métricas en tiempo real (HR, RR, amplitudes)
- **Parámetros**: Ajuste de sliders (HR, amplitud, ruido)

---

## 💻 Software

### Estructura del Proyecto

```
BioSignalSimulator Pro/
├── src/
│   ├── main.cpp              # Programa principal
│   ├── models/               # Modelos de señales
│   │   ├── ecg_model.cpp     # Modelo ECG McSharry
│   │   ├── emg_model.cpp     # Modelo EMG Fuglevand
│   │   └── ppg_model.cpp     # Modelo PPG Suma Gaussianas
│   ├── core/                 # Núcleo del sistema
│   │   ├── signal_engine.cpp # Motor de generación
│   │   └── state_machine.cpp # Máquina de estados
│   └── comm/                 # Comunicaciones
│       └── nextion_driver.cpp
├── include/                  # Headers
├── docs/                     # Documentación
└── nextion/                  # Proyecto HMI Nextion
```

### Compilación

```bash
# Requiere PlatformIO
pio run                    # Compilar
pio run -t upload          # Cargar al ESP32
pio device monitor         # Monitor serial
```

---

## 📊 Especificaciones Técnicas

| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| Fs Timer (DAC) | 2000 Hz | Nyquist ×2 sobre EMG 1000 Hz |
| Fs Modelo ECG | 300 Hz | F99% energía = 21.6 Hz |
| Fs Modelo EMG | 1000 Hz | F99% energía = 146.3 Hz |
| Fs Modelo PPG | 100 Hz | F99% energía = 4.9 Hz |
| Resolución DAC | 8 bits (0-255) | Suficiente para aplicación educativa |
| Voltaje salida | 0-3.3V | Rango DAC ESP32 |
| Refresh Nextion | 100-200 Hz | Downsampling desde 2 kHz |
| Autonomía | ~3.8 horas | 5200 mAh @ 1.26 A promedio |
| Costo total | ~$154 USD | Componentes disponibles localmente |

---

## 📡 Visualización WiFi (Próximamente)

El dispositivo puede actuar como **Access Point WiFi**, permitiendo que múltiples estudiantes visualicen las señales en tiempo real desde sus celulares o laptops.

| Característica | Descripción |
|----------------|-------------|
| **Conexión** | WiFi AP (192.168.4.1) |
| **Clientes** | Hasta 6 simultáneos |
| **Funciones** | Streaming, zoom local, pausa, descarga CSV, screenshots |
| **Control** | Solo desde dispositivo físico |

Ver metodología completa: [`docs/APP_WEB_METODOLOGIA.md`](docs/APP_WEB_METODOLOGIA.md)

---

## 📚 Documentación

- [`docs/METODOLOGIA_COMPUTACIONAL.md`](docs/METODOLOGIA_COMPUTACIONAL.md) - Metodología y modelos matemáticos
- [`docs/metodos/metodos/METODOLOGIA_ELECTRONICA.md`](docs/metodos/metodos/METODOLOGIA_ELECTRONICA.md) - Diseño electrónico detallado
- [`docs/metodos/metodos/METODOLOGIA_MECANICA.md`](docs/metodos/metodos/METODOLOGIA_MECANICA.md) - Diseño mecánico y carcasa
- [`docs/info/README_NEXTION_UI.md`](docs/info/README_NEXTION_UI.md) - Interfaz Nextion
- [`docs/APP_WEB_METODOLOGIA.md`](docs/APP_WEB_METODOLOGIA.md) - Aplicación web WiFi

---

## 🎯 Uso Rápido

1. **Encender** el dispositivo con el switch lateral
2. **Tocar "Comenzar"** en la pantalla de portada
3. **Seleccionar tipo de señal**: ECG, EMG o PPG
4. **Elegir condición** (Normal, Taquicardia, etc.)
5. **Presionar Play** para iniciar simulación
6. **Conectar BNC** a osciloscopio o equipo de medición
7. **Ajustar parámetros** según necesidad

---

## 👨‍💻 Autores

**Grupo #22 - Trabajo de Titulación ESPOL**

- **Scarlet Gabriela Sánchez Aguirre**
- **Rafael David Mata Puente**

**Institución:** Escuela Superior Politécnica del Litoral (ESPOL)  
**Facultad:** Ingeniería en Mecánica y Ciencias de la Producción  
**Carrera:** Ingeniería en Mecatrónica  
**Versión:** 1.0.0

---

## 🔌 Salida Analógica BNC

### Utilidad Actual

La salida analógica permite conectar el dispositivo a equipos externos mediante conector BNC:

| Aplicación | Descripción |
|------------|-------------|
| **Validación de monitores** | Verificar detección de arritmias y condiciones en monitores de paciente |
| **Calibración de osciloscopios** | Señal conocida para verificar escalas mV/div y ms/div |
| **Testing de algoritmos** | Entrada para sistemas DAQ, Arduino u otros microcontroladores |
| **Prácticas de laboratorio** | Entrenamiento en instrumentación biomédica |
| **Desarrollo de filtros** | Probar filtros analógicos con señales patológicas conocidas |

### Especificaciones

| Parámetro | Valor |
|-----------|-------|
| Rango de voltaje | 0 - 3.3V |
| Resolución | 8 bits (256 niveles) |
| Impedancia de salida | < 100Ω (buffer LM358) |
| Canales | 1 (señal activa) |

### Limitaciones

- **Rango limitado**: 0-3.3V unipolar (algunos equipos requieren ±5V o ±10V)
- **Resolución 8 bits**: Puede ser insuficiente para aplicaciones de alta precisión
- **Canal único**: Solo una señal simultánea

### Posibles Mejoras Futuras

- Amplificador con ganancia ajustable para expandir rango a ±5V
- DAC externo de 12/16 bits para mayor resolución
- Múltiples salidas BNC para señales simultáneas (ECG + PPG)

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT - ver [LICENSE](LICENSE) para detalles.
