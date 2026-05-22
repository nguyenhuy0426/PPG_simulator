/**
 * @file main_debug.cpp
 * @brief Modo Debug - Réplica exacta de visualización Nextion en Serial Plotter
 * @version 4.0.0
 * @date Enero 2026
 * 
 * Firmware ESP32 - BioSignalSimulator Pro
 * 
 * PROPÓSITO:
 * Este archivo genera una salida idéntica a la visualización Nextion,
 * permitiendo validar la forma de onda digital sin necesidad del dispositivo físico.
 * Los gráficos del Serial Plotter de VS Code replican exactamente lo que se vería
 * en la pantalla Nextion 7" del dispositivo.
 * 
 * ARQUITECTURA DE VALIDACIÓN:
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │                    EQUIVALENCIA NEXTION ↔ SERIAL PLOTTER                 │
 * ├──────────────────────────────────────────────────────────────────────────┤
 * │  Pantalla Nextion 7"              Serial Plotter VS Code                 │
 * │  ┌─────────────────┐              ┌─────────────────┐                    │
 * │  │ Waveform 700×380│  ═════════   │ Gráfico tiempo  │                    │
 * │  │ 0-255 (8-bit)   │    MISMO     │ real 0-255      │                    │
 * │  │ ECG: 200 Hz     │   MAPEO      │ Misma Fs        │                    │
 * │  │ EMG/PPG: 100 Hz │              │ Mismas métricas │                    │
 * │  └─────────────────┘              └─────────────────┘                    │
 * │                                                                           │
 * │  VALIDACIÓN: Si el Serial Plotter muestra la señal correcta,             │
 * │  entonces Nextion mostrará exactamente lo mismo.                         │
 * └──────────────────────────────────────────────────────────────────────────┘
 * 
 * MAPEO DE VALORES (idéntico a funciones getWaveformValue() de modelos):
 * - ECG: [-0.5, 1.5] mV → normalizado → Nextion [0, 255] rango completo
 * - EMG RAW: ±5 mV → normalizado → Nextion [0, 255] rango completo
 * - EMG ENV: 0-2 mV → normalizado (escala raw) → Nextion [0, 255]
 * - PPG: 0-150 mV AC → Nextion [26, 255] (piso 10%)
 * 
 * FRECUENCIAS DE ENVÍO (idénticas a Nextion):
 * - ECG: 200 Hz (downsampling 2000/200 = 10:1)
 * - EMG: 100 Hz (downsampling 2000/100 = 20:1) × 2 canales
 * - PPG: 100 Hz (downsampling 2000/100 = 20:1)
 * 
 * Compilar y subir:
 * pio run -e esp32_debug --target upload
 */

#include <Arduino.h>
#include "config.h"
#include "data/signal_types.h"
#include "models/ecg_model.h"
#include "models/emg_model.h"
#include "models/ppg_model.h"

// ============================================================================
// CONFIGURACION AUTO-START
// ============================================================================

// --------------------------------------------------------------------------
// TIPO DE SENAL: 0=ECG, 1=EMG, 2=PPG
// --------------------------------------------------------------------------
#define AUTO_SIGNAL_TYPE        0

// --------------------------------------------------------------------------
// CONDICIONES ECG (solo si AUTO_SIGNAL_TYPE==0):
// 0=NORMAL, 1=TACHYCARDIA, 2=BRADYCARDIA, 3=ATRIAL_FIBRILLATION,
// 4=VENTRICULAR_FIBRILLATION, 5=AV_BLOCK_1, 6=ST_ELEVATION, 7=ST_DEPRESSION
// --------------------------------------------------------------------------
#define AUTO_ECG_CONDITION      0

// --------------------------------------------------------------------------
// CONDICIONES EMG (solo si AUTO_SIGNAL_TYPE==1):
// 0=REST, 1=LOW_CONTRACTION, 2=MODERATE_CONTRACTION, 
// 3=HIGH_CONTRACTION, 4=TREMOR, 5=FATIGUE
// --------------------------------------------------------------------------
#define AUTO_EMG_CONDITION      3

// --------------------------------------------------------------------------
// CONDICIONES PPG (solo si AUTO_SIGNAL_TYPE==2):
// 0=NORMAL, 1=ARRHYTHMIA, 2=WEAK_PERFUSION, 
// 3=VASODILATION, 4=STRONG_PERFUSION, 5=VASOCONSTRICTION
// --------------------------------------------------------------------------
#define AUTO_PPG_CONDITION      0

// --------------------------------------------------------------------------
// MODO DE EJECUCION
// --------------------------------------------------------------------------
#define AUTO_CONTINUOUS         0      // 1=continuo, 0=duracion fija
#define PLOT_DURATION_MS        3500   // Duracion en ms (si no es continuo)

// ============================================================================
// INSTANCIAS GLOBALES
// ============================================================================
ECGModel ecgModel;
EMGModel emgModel;
PPGModel ppgModel;

SignalType currentSignalType = SignalType::ECG;
ECGCondition currentECGCondition = ECGCondition::NORMAL;
EMGCondition currentEMGCondition = EMGCondition::REST;
PPGCondition currentPPGCondition = PPGCondition::NORMAL;

unsigned long plotStartTime = 0;
bool isRunning = false;

// Variables para tracking
float minVal = 999.0f;
float maxVal = -999.0f;

// Contadores de muestras (igual que signal_engine y main.cpp)
uint32_t sampleCounter = 0;
uint32_t timerTickCounter = 0;

// ============================================================================
// ARQUITECTURA: Fs_timer = 2 kHz (igual que signal_engine.cpp)
// ============================================================================
const uint32_t TIMER_TICK_US = 1000000 / FS_TIMER_HZ;  // 500 us = 2 kHz

// Variables para timing real e interpolación
static uint32_t lastModelTick_us = 0;
static uint8_t currentModelSample = 128;
static uint8_t previousModelSample = 128;
static uint16_t interpolationCounter = 0;
static uint32_t lastTimerTick_us = 0;

// Downsampling para Serial Plotter (IDÉNTICO a Nextion)
// Ratio = Fs_timer / Fds - Mismo que NEXTION_DOWNSAMPLE_* en config.h
#define PLOT_DOWNSAMPLE_ECG  NEXTION_DOWNSAMPLE_ECG   // 20 (200 Hz)
#define PLOT_DOWNSAMPLE_EMG  NEXTION_DOWNSAMPLE_EMG   // 40 (100 Hz)
#define PLOT_DOWNSAMPLE_PPG  NEXTION_DOWNSAMPLE_PPG   // 40 (100 Hz)

// ============================================================================
// NOMBRES DE CONDICIONES
// ============================================================================
const char* getECGConditionName(ECGCondition cond) {
    switch (cond) {
        case ECGCondition::NORMAL:                  return "Normal";
        case ECGCondition::TACHYCARDIA:             return "Taquicardia";
        case ECGCondition::BRADYCARDIA:             return "Bradicardia";
        case ECGCondition::ATRIAL_FIBRILLATION:     return "Fibrilacion Auricular";
        case ECGCondition::VENTRICULAR_FIBRILLATION: return "Fibrilacion Ventricular";
        case ECGCondition::AV_BLOCK_1:              return "Bloqueo AV 1er Grado";
        case ECGCondition::ST_ELEVATION:            return "Elevacion ST";
        case ECGCondition::ST_DEPRESSION:           return "Depresion ST";
        default:                                    return "Desconocido";
    }
}

const char* getEMGConditionName(EMGCondition cond) {
    switch (cond) {
        case EMGCondition::REST:                 return "Reposo";
        case EMGCondition::LOW_CONTRACTION:      return "Contraccion Baja";
        case EMGCondition::MODERATE_CONTRACTION: return "Contraccion Moderada";
        case EMGCondition::HIGH_CONTRACTION:     return "Contraccion Alta";
        case EMGCondition::TREMOR:               return "Temblor";
        case EMGCondition::FATIGUE:              return "Fatiga";
        default:                                 return "Desconocido";
    }
}

const char* getPPGConditionName(PPGCondition cond) {
    switch (cond) {
        case PPGCondition::NORMAL:            return "Normal";
        case PPGCondition::ARRHYTHMIA:        return "Arritmia";
        case PPGCondition::WEAK_PERFUSION:    return "Perfusion Debil";
        case PPGCondition::VASOCONSTRICTION:  return "Vasoconstriccion";
        case PPGCondition::STRONG_PERFUSION:  return "Perfusion Fuerte";
        case PPGCondition::VASODILATION:      return "Vasodilatacion";
        default:                              return "Desconocido";
    }
}

// ============================================================================
// CONFIGURAR MODELOS
// ============================================================================
void setupECG(ECGCondition cond) {
    currentSignalType = SignalType::ECG;
    currentECGCondition = cond;
    
    ECGParameters params;
    params.condition = cond;
    params.qrsAmplitude = 1.0f;
    params.noiseLevel = 0.02f;
    params.heartRate = 0;
    ecgModel.setParameters(params);
}

void setupEMG(EMGCondition cond) {
    currentSignalType = SignalType::EMG;
    currentEMGCondition = cond;
    
    EMGParameters params;
    params.condition = cond;
    params.noiseLevel = 0.02f;
    params.excitationLevel = 0.0f;
    params.amplitude = 1.0f;
    emgModel.setParameters(params);
}

void setupPPG(PPGCondition cond) {
    currentSignalType = SignalType::PPG;
    currentPPGCondition = cond;
    
    PPGParameters params;
    params.condition = cond;
    params.heartRate = 75.0f;
    params.perfusionIndex = 3.0f;
    params.noiseLevel = 0.02f;
    ppgModel.setParameters(params);
}

// ============================================================================
// SETUP
// ============================================================================
void setup() {
    Serial.begin(115200);
    delay(1000);
    
    // Inicializar DAC
    pinMode(DAC_SIGNAL_PIN, OUTPUT);
    dacWrite(DAC_SIGNAL_PIN, 128);
    
    // Banner de inicio
    Serial.println();
    Serial.println("════════════════════════════════════════════════════════════");
    Serial.println("  BIOSIGNALSIMULATOR PRO - MODO VALIDACIÓN NEXTION v4.0");
    Serial.println("════════════════════════════════════════════════════════════");
    Serial.println();
    Serial.println("  PROPÓSITO: Réplica exacta de visualización Nextion");
    Serial.println("  Los gráficos del Serial Plotter son idénticos a Nextion.");
    Serial.println();
    
    // Configurar senal segun tipo seleccionado
    #if AUTO_SIGNAL_TYPE == 0
        setupECG((ECGCondition)AUTO_ECG_CONDITION);
        Serial.printf("  Señal: ECG - %s\n", getECGConditionName(currentECGCondition));
        Serial.printf("  Modelo @ %d Hz | Nextion @ %d Hz (1:%d)\n", 
                     MODEL_SAMPLE_RATE_ECG, 
                     FS_TIMER_HZ / PLOT_DOWNSAMPLE_ECG,
                     PLOT_DOWNSAMPLE_ECG);
    #elif AUTO_SIGNAL_TYPE == 1
        setupEMG((EMGCondition)AUTO_EMG_CONDITION);
        Serial.printf("  Señal: EMG - %s\n", getEMGConditionName(currentEMGCondition));
        Serial.printf("  Modelo @ %d Hz | Nextion @ %d Hz (1:%d)\n", 
                     MODEL_SAMPLE_RATE_EMG, 
                     FS_TIMER_HZ / PLOT_DOWNSAMPLE_EMG,
                     PLOT_DOWNSAMPLE_EMG);
    #else
        setupPPG((PPGCondition)AUTO_PPG_CONDITION);
        Serial.printf("  Señal: PPG - %s\n", getPPGConditionName(currentPPGCondition));
        Serial.printf("  Modelo @ %d Hz | Nextion @ %d Hz (1:%d)\n", 
                     MODEL_SAMPLE_RATE_PPG, 
                     FS_TIMER_HZ / PLOT_DOWNSAMPLE_PPG,
                     PLOT_DOWNSAMPLE_PPG);
    #endif
    
    Serial.println();
    Serial.println("  MAPEO IDÉNTICO A NEXTION:");
    #if AUTO_SIGNAL_TYPE == 0
        Serial.println("    ECG: (mV + 0.5) / 2.0 → 20 + (norm × 215) = [20, 235]");
        Serial.println("    Rango visible: -0.5 a +1.5 mV (2.0 mV total)");
    #elif AUTO_SIGNAL_TYPE == 1
        Serial.println("    EMG RAW: valor 0-380 → [20, 235]");
        Serial.println("    EMG ENV: valor 0-380 → [20, 235]");
    #else
        Serial.println("    PPG: AC / 150 mV → 20 + (norm × 215) = [20, 235]");
    #endif
    
    Serial.println();
    #if AUTO_CONTINUOUS
        Serial.println("  Modo: CONTINUO (presiona 'r' para reiniciar)");
    #else
        Serial.printf("  Modo: DURACION FIJA - %.1f segundos\n", PLOT_DURATION_MS / 1000.0f);
    #endif
    
    Serial.println("════════════════════════════════════════════════════════════");
    Serial.println();
    delay(1500);
    
    plotStartTime = millis();
    isRunning = true;
    minVal = 999.0f;
    maxVal = -999.0f;
}

// ============================================================================
// LOOP PRINCIPAL
// ============================================================================
void loop() {
    if (!isRunning) return;
    
    static unsigned long lastStats = 0;
    
    unsigned long now_us = micros();
    unsigned long now_ms = millis();
    
    // Verificar comandos serial
    if (Serial.available()) {
        char c = Serial.read();
        if (c == 'r' || c == 'R') {
            setup();
            return;
        }
    }
    
    // Verificar duracion (modo no continuo)
    #if !AUTO_CONTINUOUS
    if (now_ms - plotStartTime >= PLOT_DURATION_MS) {
        isRunning = false;
        Serial.println("\n--- FIN DE CAPTURA ---");
        return;
    }
    #endif
    
    // ========== ARQUITECTURA IGUAL A signal_engine.cpp ==========
    uint32_t modelTickInterval_us;
    uint8_t upsampleRatio;
    float modelDeltaTime;
    
    #if AUTO_SIGNAL_TYPE == 0  // ECG
        modelTickInterval_us = MODEL_TICK_US_ECG;
        upsampleRatio = UPSAMPLE_RATIO_ECG;
        modelDeltaTime = MODEL_DT_ECG;
    #elif AUTO_SIGNAL_TYPE == 1  // EMG
        modelTickInterval_us = MODEL_TICK_US_EMG;
        upsampleRatio = UPSAMPLE_RATIO_EMG;
        modelDeltaTime = MODEL_DT_EMG;
    #else  // PPG
        modelTickInterval_us = MODEL_TICK_US_PPG;
        upsampleRatio = UPSAMPLE_RATIO_PPG;
        modelDeltaTime = MODEL_DT_PPG;
    #endif
    
    // ¿Es hora de generar nueva muestra del modelo?
    if (now_us - lastModelTick_us >= modelTickInterval_us) {
        lastModelTick_us = now_us;
        
        previousModelSample = currentModelSample;
        
        #if AUTO_SIGNAL_TYPE == 0  // ECG
            currentModelSample = ecgModel.getDACValue(modelDeltaTime);
        #elif AUTO_SIGNAL_TYPE == 1  // EMG
            emgModel.tick(modelDeltaTime);
            currentModelSample = emgModel.getRawDACValue();
        #else  // PPG
            currentModelSample = ppgModel.getDACValue(modelDeltaTime);
        #endif
        
        interpolationCounter = 0;
        sampleCounter++;
    }
    
    // ========== TIMER TICK @ 2 kHz ==========
    bool timerTick = false;
    uint8_t dacValue = 128;
    
    if (now_us - lastTimerTick_us >= TIMER_TICK_US) {
        lastTimerTick_us = now_us;
        timerTick = true;
        timerTickCounter++;
        
        // Interpolación lineal
        float t = (float)interpolationCounter / (float)upsampleRatio;
        int16_t interpolated = previousModelSample + 
                               (int16_t)((currentModelSample - previousModelSample) * t);
        
        if (interpolated < 0) interpolated = 0;
        if (interpolated > 255) interpolated = 255;
        
        dacValue = (uint8_t)interpolated;
        dacWrite(DAC_SIGNAL_PIN, dacValue);
        
        interpolationCounter++;
        if (interpolationCounter >= upsampleRatio) {
            interpolationCounter = 0;
        }
    }
    
    // ========================================================================
    // ENVIO A SERIAL PLOTTER - MAPEO IDÉNTICO A NEXTION (getWaveformValue())
    // ========================================================================
    // Formato VS Code Serial Plotter: >var:val,var2:val2\r\n
    // El valor "wave" representa exactamente lo que Nextion muestra:
    // - ECG: [0, 255] rango completo (igual que ecg_model.cpp)
    // - EMG: [0, 255] rango completo (igual que emg_model.cpp)
    // - PPG: [26, 255] con piso 10% (igual que ppg_model.cpp)
    // ========================================================================
    
    if (timerTick) {
        
        #if AUTO_SIGNAL_TYPE == 0  // ECG @ 200 Hz (igual que Nextion)
        if (timerTickCounter % PLOT_DOWNSAMPLE_ECG == 0) {
            // === MAPEO IDÉNTICO A ecg_model.cpp getWaveformValue() ===
            float mV_value = ecgModel.getCurrentValueMV();
            
            // Normalización: [-0.5, 1.5] mV → [0, 1] (rango 2.0 mV)
            float normalized = (mV_value + 0.5f) / 2.0f;
            if (normalized < 0.0f) normalized = 0.0f;
            if (normalized > 1.0f) normalized = 1.0f;
            
            // Mapeo a rango Nextion: [0, 255] rango completo
            int waveValue = (int)(normalized * 255.0f);
            
            // Track min/max en mV
            if (mV_value < minVal) minVal = mV_value;
            if (mV_value > maxVal) maxVal = mV_value;
            
            // Métricas ECG
            ECGDisplayMetrics m = ecgModel.getDisplayMetrics();
            
            // Formato Serial Plotter con valor Nextion (wave) como canal principal
            Serial.print(">wave:");
            Serial.print(waveValue);
            Serial.print(",mV:");
            Serial.print(mV_value, 2);
            Serial.print(",hr:");
            Serial.print(m.bpm, 0);
            Serial.print(",rr:");
            Serial.print(m.rrInterval_ms, 0);
            Serial.print(",pr:");
            Serial.print(m.prInterval_ms, 0);
            Serial.print(",qrs:");
            Serial.print(m.qrsDuration_ms, 0);
            Serial.print(",qtc:");
            Serial.print(m.qtcInterval_ms, 0);
            Serial.print(",r:");
            Serial.print(m.rAmplitude_mV, 2);
            Serial.print(",st:");
            Serial.print(m.stDeviation_mV, 2);
            Serial.println();
        }
            
        #elif AUTO_SIGNAL_TYPE == 1  // EMG @ 100 Hz (igual que Nextion)
        if (timerTickCounter % PLOT_DOWNSAMPLE_EMG == 0) {
            // === MAPEO IDÉNTICO A emg_model.cpp getWaveformValue_Ch0/Ch1() ===
            
            // Canal 0: Señal RAW bipolar (-5 a +5 mV) → [0, 255]
            uint8_t ch0_mapped = emgModel.getWaveformValue_Ch0();
            
            // Canal 1: Envolvente RMS unipolar (0 a +2 mV) → [0, 255] en escala raw
            uint8_t ch1_mapped = emgModel.getWaveformValue_Ch1();
            
            // Valores originales para tracking
            float rawMV = emgModel.getRawSample();
            float envMV = emgModel.getProcessedSample();
            
            if (rawMV < minVal) minVal = rawMV;
            if (rawMV > maxVal) maxVal = rawMV;
            
            // Formato Serial Plotter con valores Nextion (raw_wave, env_wave)
            Serial.print(">raw_wave:");
            Serial.print(ch0_mapped);
            Serial.print(",env_wave:");
            Serial.print(ch1_mapped);
            Serial.print(",raw_mV:");
            Serial.print(rawMV, 2);
            Serial.print(",env_mV:");
            Serial.print(envMV, 2);
            Serial.print(",rms:");
            Serial.print(emgModel.getRMSAmplitude(), 3);
            Serial.print(",mus:");
            Serial.print(emgModel.getActiveMotorUnits());
            Serial.print(",fr:");
            Serial.print(emgModel.getMeanFiringRate(), 1);
            Serial.print(",mvc:");
            Serial.print(emgModel.getContractionLevel(), 0);
            Serial.println();
        }
            
        #else  // PPG @ 100 Hz (igual que Nextion)
        if (timerTickCounter % PLOT_DOWNSAMPLE_PPG == 0) {
            // === MAPEO IDÉNTICO A ppg_model.cpp getWaveformValue() ===
            float acValue_mV = ppgModel.getLastACValue();
            
            // Mapeo unipolar: 0 → 26 (piso 10%), 150 mV → 255
            const float AC_DISPLAY_MAX = 150.0f;
            const uint8_t WAVEFORM_MIN = 26;       // Piso: 26/255 ≈ 10%
            const uint8_t WAVEFORM_RANGE = 229;    // 255 - 26 = 229 niveles útiles
            float normalized = acValue_mV / AC_DISPLAY_MAX;
            if (normalized < 0.0f) normalized = 0.0f;
            if (normalized > 1.0f) normalized = 1.0f;
            
            int waveValue = WAVEFORM_MIN + (int)(normalized * WAVEFORM_RANGE);
            
            if (acValue_mV < minVal) minVal = acValue_mV;
            if (acValue_mV > maxVal) maxVal = acValue_mV;
            
            // Formato Serial Plotter con valor Nextion (wave)
            Serial.print(">wave:");
            Serial.print(waveValue);
            Serial.print(",ac_mV:");
            Serial.print(acValue_mV, 1);
            Serial.print(",hr:");
            Serial.print(ppgModel.getMeasuredHR(), 0);
            Serial.print(",rr:");
            Serial.print(ppgModel.getMeasuredRRInterval(), 0);
            Serial.print(",pi:");
            Serial.print(ppgModel.getMeasuredPI(), 2);
            Serial.print(",sys:");
            Serial.print(ppgModel.getMeasuredSystoleTime(), 0);
            Serial.print(",dia:");
            Serial.print(ppgModel.getMeasuredDiastoleTime(), 0);
            Serial.println();
        }
        #endif
    }
    
    // ========== ESTADISTICAS PERIODICAS (cada 4 segundos) ==========
    if (now_ms - lastStats >= 4000) {
        lastStats = now_ms;
        
        Serial.println();
        Serial.println("════════════════════════════════════════════════════════════");
        Serial.printf("  [%lu s] MÉTRICAS NEXTION - %lu muestras modelo\n", 
                     (now_ms - plotStartTime) / 1000, sampleCounter);
        Serial.println("────────────────────────────────────────────────────────────");
        
        #if AUTO_SIGNAL_TYPE == 0  // ECG
            ECGDisplayMetrics m = ecgModel.getDisplayMetrics();
            Serial.printf("  HR: %.0f BPM | RR: %.0f ms\n", m.bpm, m.rrInterval_ms);
            Serial.printf("  PR: %.0f ms | QRS: %.0f ms | QTc: %.0f ms\n",
                         m.prInterval_ms, m.qrsDuration_ms, m.qtcInterval_ms);
            Serial.printf("  Amplitudes: P=%.2f | Q=%.2f | R=%.2f | S=%.2f | T=%.2f mV\n",
                         m.pAmplitude_mV, m.qAmplitude_mV, m.rAmplitude_mV, 
                         m.sAmplitude_mV, m.tAmplitude_mV);
            Serial.printf("  ST: %.2f mV | Latidos: %lu\n", m.stDeviation_mV, m.beatCount);
            Serial.printf("  Rango señal: [%.2f, %.2f] mV\n", minVal, maxVal);
                         
        #elif AUTO_SIGNAL_TYPE == 1  // EMG
            Serial.printf("  RMS: %.3f mV | Contracción: %.0f%% MVC\n", 
                         emgModel.getRMSAmplitude(), emgModel.getContractionLevel());
            Serial.printf("  MUs activas: %d/100 | FR media: %.1f Hz\n", 
                         emgModel.getActiveMotorUnits(), emgModel.getMeanFiringRate());
            Serial.printf("  Fatiga MDF: %.0f Hz | MFL: %.2f\n",
                         emgModel.getFatigueMDF(), emgModel.getFatigueMFL());
            Serial.printf("  Rango RAW: [%.3f, %.3f] mV\n", minVal, maxVal);
            
        #else  // PPG
            Serial.printf("  HR: %.0f BPM | RR: %.0f ms\n", 
                         ppgModel.getMeasuredHR(), ppgModel.getMeasuredRRInterval());
            Serial.printf("  PI: %.2f%% | AC: %.1f mV\n", 
                         ppgModel.getMeasuredPI(), ppgModel.getMeasuredACAmplitude());
            Serial.printf("  Sístole: %.0f ms | Diástole: %.0f ms\n",
                         ppgModel.getMeasuredSystoleTime(), ppgModel.getMeasuredDiastoleTime());
            Serial.printf("  Latidos: %lu | Rango AC: [%.1f, %.1f] mV\n", 
                         ppgModel.getBeatCount(), minVal, maxVal);
        #endif
        
        Serial.println("════════════════════════════════════════════════════════════");
        Serial.println();
    }
}
