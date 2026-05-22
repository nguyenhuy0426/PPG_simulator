/**
 * @file config.h
 * @brief Configuración global del sistema BioSignalSimulator Pro
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Configuración de hardware, pines, frecuencias y constantes del sistema.
 * 
 * Hardware: ESP32-WROOM-32 + Nextion NX8048T070 (7" 800x480)
 * Alimentación: 2S 18650 (7.4V) + Buck 5V
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// ============================================================================
// IDENTIFICACIÓN DEL SISTEMA
// ============================================================================
#define DEVICE_NAME             "BioSignalSimulator Pro"
#define FIRMWARE_VERSION        "1.0.0"
#define FIRMWARE_DATE           "18 Diciembre 2025"
#define HARDWARE_MODEL          "ESP32-WROOM-32"
#define HAS_PSRAM               false
#define SRAM_SIZE_KB            520
#define FLASH_SIZE_MB           4

// ============================================================================
// CONFIGURACIÓN DE PINES - DAC Y MULTIPLEXOR
// ============================================================================
#define DAC_SIGNAL_PIN          25      // GPIO25 - DAC1 (Salida a LM358 buffer)

// Multiplexor CD4051 (selección de atenuación)
// CHA (S0) → GPIO32, CHB (S1) → GPIO33
#define MUX_SELECT_S0           32      // GPIO32 - CD4051 pin 11 (Selector A)
#define MUX_SELECT_S1           33      // GPIO33 - CD4051 pin 10 (Selector B)
// CD4051 S2 (pin 9) conectado a GND

// ============================================================================
// CONFIGURACIÓN DE PINES - NEXTION
// ============================================================================
#define NEXTION_SERIAL          Serial2
#define NEXTION_RX_PIN          16      // RX2
#define NEXTION_TX_PIN          17      // TX2
#define NEXTION_BAUD            115200  // Mismo baud que Nextion Editor

// ============================================================================
// CONFIGURACIÓN DE PINES - LED RGB
// ============================================================================
// Nota: se restablece LED RGB a GPIO21/22/23 (bus I2C/VSPI se mantiene libre por ahora)
#define LED_RGB_ENABLED         true
#define LED_RGB_RED             21      // GPIO21 - I2C SDA (no usado)
#define LED_RGB_GREEN           22      // GPIO22 - I2C SCL (no usado)
#define LED_RGB_BLUE            23      // GPIO23 - VSPI MOSI (no usado)
#define LED_RGB_COMMON_ANODE    false   // false = cátodo común

// ============================================================================
// CONFIGURACIÓN DE PINES - LED STATUS
// ============================================================================
#define LED_STATUS              2       // GPIO2 (LED interno)

// ============================================================================
// CONFIGURACIÓN DE PINES - ADC LOOPBACK (DEBUG)
// ============================================================================
#define DEBUG_ADC_LOOPBACK      true   // true = leer GPIO34 y enviar a Serial
#define ADC_LOOPBACK_PIN        34      // GPIO34 - ADC1_CH6

// ============================================================================
// CONFIGURACIÓN DE SEÑALES
// ============================================================================

// ============================================================================
// FRECUENCIAS DE MUESTREO - METODOLOGÍA DE SÍNTESIS DIGITAL
// ============================================================================
// NOTA: Este sistema GENERA señales sintéticas, NO digitaliza señales analógicas.
// Por lo tanto, Nyquist (para ADC) NO aplica directamente aquí.
//
// TÉCNICA: Oversampling + Decimación
// 1. Modelo genera muestras a Fs_modelo (según criterios de síntesis)
// 2. Interpolación lineal sube a Fs_timer (oversampling)
// 3. Decimación baja a Fds para salidas (DAC y Nextion)
// 4. Filtro RC completa la reconstrucción analógica
//
// Criterios para Fs_timer:
// 1. Fs_timer > Fs_modelo_máximo (EMG @ 1000 Hz)
// 2. Factor de seguridad 2× → 2000 Hz
// 3. Divisible por Fds (200, 100) para decimación entera
// Conclusión: Fs_timer = 2000 Hz

// Timer maestro (frecuencia de buffer interno)
const uint16_t FS_TIMER_HZ = 2000;             // Hz - Timer ISR @ 2 kHz
const uint16_t SAMPLE_RATE_HZ = FS_TIMER_HZ;   // Alias legacy

// ============================================================================
// FRECUENCIAS DE MUESTREO DEL MODELO (Fs_modelo)
// ============================================================================
// Basadas en Nyquist de estándares clínicos: Fs = 2 × Fmax_clínico
//
// | Señal | BW clínico | Fmax  | Fs_Nyquist | Fs_modelo |
// |-------|------------|-------|------------|-----------|
// | ECG   | 0.05-150Hz | 150Hz | 300 Hz     | 300 Hz    |
// | EMG   | 20-500Hz   | 500Hz | 1000 Hz    | 1000 Hz   |
// | PPG   | 0.5-10Hz   | 10Hz  | 20 Hz      | 100 Hz*   |
//
// *NOTA PPG: Aunque Nyquist solo requiere 20 Hz para BW de 10 Hz, se usa
// 100 Hz para evitar escalones visibles en el display Nextion. Con 20 Hz
// y upsampling 100:1 a 2 kHz, la interpolación lineal genera "escalones"
// perceptibles. Al usar 100 Hz (igual a la tasa de refresco del display),
// cada punto enviado es una muestra real del modelo, no una interpolación.
// Esto no afecta el contenido frecuencial ya que 100 Hz >> 2×10 Hz de BW.
//
// Luego se interpola a FS_TIMER_HZ (2000 Hz) para salida al DAC.
// ============================================================================

const uint16_t MODEL_SAMPLE_RATE_ECG = 300;    // Hz - 2×150Hz (BW clínico ECG)
const uint16_t MODEL_SAMPLE_RATE_EMG = 1000;   // Hz - 2×500Hz (BW clínico EMG)
const uint16_t MODEL_SAMPLE_RATE_PPG = 100;    // Hz - 5×Nyquist (evita escalones display)

// deltaTime para cada modelo (segundos)
const float MODEL_DT_ECG = 1.0f / MODEL_SAMPLE_RATE_ECG;  // 3.333 ms
const float MODEL_DT_EMG = 1.0f / MODEL_SAMPLE_RATE_EMG;  // 1.0 ms
const float MODEL_DT_PPG = 1.0f / MODEL_SAMPLE_RATE_PPG;  // 10 ms

// Intervalo de tick en microsegundos (para timing real)
const uint32_t MODEL_TICK_US_ECG = 1000000 / MODEL_SAMPLE_RATE_ECG;  // 3333 us
const uint32_t MODEL_TICK_US_EMG = 1000000 / MODEL_SAMPLE_RATE_EMG;  // 1000 us
const uint32_t MODEL_TICK_US_PPG = 1000000 / MODEL_SAMPLE_RATE_PPG;  // 10000 us

// Ratios de upsampling: interpolación de Fs_modelo a Fs_timer
// Ratio = Fs_timer / Fs_modelo
const uint8_t UPSAMPLE_RATIO_ECG = FS_TIMER_HZ / MODEL_SAMPLE_RATE_ECG;  // 2000/300 ≈ 6
const uint8_t UPSAMPLE_RATIO_EMG = FS_TIMER_HZ / MODEL_SAMPLE_RATE_EMG;  // 2000/1000 = 2
const uint8_t UPSAMPLE_RATIO_PPG = FS_TIMER_HZ / MODEL_SAMPLE_RATE_PPG;  // 2000/100 = 20

// Frecuencias de salida a displays
const uint16_t FDS_ECG = 200;                  // Hz - display ECG
const uint16_t FDS_EMG = 100;                  // Hz - display EMG
const uint16_t FDS_PPG = 100;                  // Hz - display PPG

// Ratios de downsampling para display (respecto a Fs_timer)
// Ratio = Fs_timer / Fds
const uint8_t NEXTION_DOWNSAMPLE_ECG = FS_TIMER_HZ / FDS_ECG;   // 2000/200 = 10
const uint8_t NEXTION_DOWNSAMPLE_PPG = FS_TIMER_HZ / FDS_PPG;   // 2000/100 = 20
const uint8_t NEXTION_DOWNSAMPLE_EMG = FS_TIMER_HZ / FDS_EMG;   // 2000/100 = 20

// Alias para compatibilidad
const uint16_t NEXTION_SEND_RATE = 200;
const uint16_t SERIAL_PLOTTER_RATE_ECG = FDS_ECG;
const uint16_t SERIAL_PLOTTER_RATE_PPG = FDS_PPG;
const uint16_t SERIAL_PLOTTER_RATE_EMG = FDS_EMG;

// ============================================================================
// CONFIGURACIÓN DAC
// ============================================================================
#define DAC_RESOLUTION          8       // 8 bits (0-255)
#define DAC_MAX_VALUE           255
#define DAC_CENTER_VALUE        128
#define DAC_VOLTAGE_MAX         3.3f    // Voltios
#define DAC_MV_PER_STEP         (DAC_VOLTAGE_MAX * 1000.0f / 256.0f)  // ~12.9 mV

// ============================================================================
// CONFIGURACIÓN DE BUFFERS
// ============================================================================
#define SIGNAL_BUFFER_SIZE      2048    // Muestras (~2 segundos)
#define PRECALC_BUFFER_SIZE     512     // Bloques de pre-cálculo

// ============================================================================
// CONFIGURACIÓN DE TAREAS FREERTOS
// ============================================================================
#define CORE_SIGNAL_GENERATION  1       // Core 1: Generación tiempo real
#define CORE_UI_COMMUNICATION   0       // Core 0: UI y comunicación

#define STACK_SIZE_SIGNAL       4096
#define STACK_SIZE_UI           4096
#define STACK_SIZE_MONITOR      2048

#define TASK_PRIORITY_SIGNAL    5       // Alta prioridad
#define TASK_PRIORITY_UI        2       // Media prioridad
#define TASK_PRIORITY_MONITOR   1       // Baja prioridad

// ============================================================================
// CONFIGURACIÓN DE TIEMPOS (UI - basado en millis(), NO en timer)
// ============================================================================
// Las métricas de TEXTO (HR, RR, PI, etc.) se actualizan a baja frecuencia
// porque los humanos no perciben cambios de texto >5 Hz y ahorrar serial.
// Esto NO tiene relación con Fs_timer ni downsampling de waveform.
#define METRICS_UPDATE_MS       250     // 4 Hz actualización métricas texto

// NOTA: El WAVEFORM usa contador de ticks del timer @ 2kHz
// con los ratios NEXTION_DOWNSAMPLE_* (ECG 10:1, EMG/PPG 20:1)

// ============================================================================
// CONFIGURACION NEXTION WAVEFORM (7" Basic)
// ============================================================================
#define NEXTION_WAVEFORM_WIDTH  700     // Ancho del waveform en pixeles
#define NEXTION_WAVEFORM_HEIGHT 380     // Altura del waveform en pixeles
#define WAVEFORM_COMPONENT_ID   1       // ID del componente waveform
#define WAVEFORM_CHANNEL        0       // Canal del waveform (solo usamos 1)

// Tiempo visible en Nextion (depende de Fds):
// - ECG @ 200 Hz: 700px / 200Hz = 3.5 segundos (~4 latidos @ 75 BPM)
// - EMG @ 100 Hz: 700px / 100Hz = 7.0 segundos
// - PPG @ 100 Hz: 700px / 100Hz = 7.0 segundos (~9 latidos @ 75 BPM)

// ============================================================================
// CONFIGURACIÓN DE DEBUG
// ============================================================================
#ifdef DEBUG_ENABLED
    #define DEBUG_PRINT(x)      Serial.print(x)
    #define DEBUG_PRINTLN(x)    Serial.println(x)
    #define DEBUG_PRINTF(...)   Serial.printf(__VA_ARGS__)
#else
    #define DEBUG_PRINT(x)
    #define DEBUG_PRINTLN(x)
    #define DEBUG_PRINTF(...)
#endif

// Macro para verificar memoria
#define CHECK_HEAP(min_kb) (ESP.getFreeHeap() >= ((min_kb) * 1024))

#endif // CONFIG_H
