/**
 * @file signal_engine.cpp
 * @brief Implementación del motor de generación de señales
 * @version 1.1.0
 * @date 09 Enero 2026
 */

#include "core/signal_engine.h"
#include "config.h"
#include "hw/cd4051_mux.h"

// ============================================================================
// EXTERNA: Objeto MUX global (definido en cd4051_mux.cpp)
// ============================================================================
extern CD4051Mux mux;

// ============================================================================
// SINGLETON
// ============================================================================
SignalEngine* SignalEngine::instance = nullptr;

// ============================================================================
// BUFFERS EN RAM RÁPIDA
// ============================================================================
DRAM_ATTR static uint8_t signalBuffer[SIGNAL_BUFFER_SIZE];
DRAM_ATTR static float displayBuffer[SIGNAL_BUFFER_SIZE];
DRAM_ATTR static volatile uint16_t bufferReadIndex = 0;
DRAM_ATTR static volatile uint16_t bufferWriteIndex = 0;
DRAM_ATTR static volatile uint32_t isrCount = 0;
DRAM_ATTR static volatile uint32_t isrMaxTime = 0;
DRAM_ATTR static volatile uint32_t bufferUnderruns = 0;
DRAM_ATTR static volatile uint8_t lastDACValue = 128;

// Variables para timing real e interpolación
static uint32_t lastModelTick_us = 0;          // Último tick del modelo
static uint8_t currentModelSample = 128;       // Muestra actual del modelo
static uint8_t previousModelSample = 128;      // Muestra anterior (para interpolación)
static float currentModelValueMV = 0.0f;       // Último valor del modelo en mV
static float previousModelValueMV = 0.0f;      // Valor anterior en mV
static uint16_t interpolationCounter = 0;      // Contador para interpolación

// ============================================================================
// BUFFER WEBSOCKET SINCRONIZADO (frecuencia dinámica según señal)
// ============================================================================
static WSSampleData wsBuffer[WS_SAMPLE_BUFFER_SIZE];
static volatile uint8_t wsBufferReadIdx = 0;
static volatile uint8_t wsBufferWriteIdx = 0;
static uint32_t lastWSSampleTime_us = 0;
// Intervalos según tipo de señal (igual que Nextion):
// ECG: 200 Hz = 5000 us, EMG/PPG: 100 Hz = 10000 us
static uint32_t wsSampleInterval_us = 5000;  // Default ECG 200 Hz

// NOTA: El DAC escribe a 4 kHz SIN decimación para espectro correcto
// La decimación solo se aplica a Nextion y Serial Plotter (visualización)

// ============================================================================
// CONSTRUCTOR
// ============================================================================
SignalEngine::SignalEngine() {
    currentSignal.type = SignalType::NONE;
    currentSignal.state = SignalState::STOPPED;
    
    signalMutex = xSemaphoreCreateMutex();
    signalTimer = nullptr;
    generationTaskHandle = nullptr;
    
    // Inicializar salida DAC EMG en RAW por defecto
    emgDacOutput = EMGDACOutput::RAW;
}

SignalEngine* SignalEngine::getInstance() {
    if (instance == nullptr) {
        instance = new SignalEngine();
    }
    return instance;
}

// ============================================================================
// INICIALIZACIÓN
// ============================================================================
bool SignalEngine::begin() {
    DEBUG_PRINTLN("[SignalEngine] Inicializando...");
    
    // Configurar DAC
    dacWrite(DAC_SIGNAL_PIN, DAC_CENTER_VALUE);
    
    // Crear tarea de generación en Core 1
    BaseType_t taskCreated = xTaskCreatePinnedToCore(
        generationTask,
        "SignalGen",
        STACK_SIZE_SIGNAL,
        this,
        TASK_PRIORITY_SIGNAL,
        &generationTaskHandle,
        CORE_SIGNAL_GENERATION
    );
    
    if (taskCreated != pdPASS) {
        DEBUG_PRINTLN("[SignalEngine] ERROR: No se pudo crear tarea");
        return false;
    }
    
    DEBUG_PRINTLN("[SignalEngine] Inicializado correctamente");
    return true;
}

// ============================================================================
// CONTROL DE SEÑALES
// ============================================================================
bool SignalEngine::startSignal(SignalType type, uint8_t condition) {
    Serial.printf("[SignalEngine] startSignal llamado: type=%d, condition=%d\n", (int)type, condition);
    
    if (xSemaphoreTake(signalMutex, portMAX_DELAY) == pdTRUE) {
        // Detener señal actual si existe
        if (currentSignal.state == SignalState::RUNNING) {
            stopTimer();
        }
        
        // Reset buffers y variables de timing
        bufferReadIndex = 0;
        bufferWriteIndex = 0;
        isrCount = 0;
        bufferUnderruns = 0;
        lastModelTick_us = micros();
        currentModelSample = DAC_CENTER_VALUE;
        previousModelSample = DAC_CENTER_VALUE;
        currentModelValueMV = 0.0f;
        previousModelValueMV = 0.0f;
        interpolationCounter = 0;
        
        // NOTA: DAC escribe a 4 kHz SIN decimación (espectro correcto)
        // La decimación solo se usa para Nextion/Serial Plotter (visualización)
        
        // Configurar tipo de señal
        currentSignal.type = type;
        currentSignal.sampleCount = 0;
        currentSignal.lastUpdateTime = millis();
        
        // Configurar intervalo WebSocket según tipo (igual que Nextion)
        // ECG: 200 Hz = 5000 us, EMG/PPG: 100 Hz = 10000 us
        switch (type) {
            case SignalType::ECG:
                wsSampleInterval_us = 5000;   // 200 Hz
                break;
            case SignalType::EMG:
            case SignalType::PPG:
                wsSampleInterval_us = 10000;  // 100 Hz
                break;
            default:
                wsSampleInterval_us = 10000;
        }
        // Reset buffer WebSocket
        wsBufferReadIdx = 0;
        wsBufferWriteIdx = 0;
        lastWSSampleTime_us = micros();
        
        // ========================================================================
        // CONFIGURAR CANAL DE MUX SEGÚN TIPO DE SEÑAL
        // ========================================================================
        // CRÍTICO: Cada señal requiere un filtro RC diferente
        // - ECG: CH0 (R=6.8kΩ, Fc=23.4 Hz)  → Filtro paso-bajo para ECG
        // - EMG: CH1 (R=1.0kΩ, Fc=159 Hz)   → Filtro paso-bajo para EMG
        // - PPG: CH2 (R=25kΩ, Fc=6.37 Hz)   → Filtro paso-bajo para PPG
        // ========================================================================
        switch (type) {
            case SignalType::ECG:
                mux.selectChannel(MuxChannel::CH0_ECG_6K8);
                Serial.println("[MUX] Canal seleccionado: CH0 (6.8kΩ, Fc=23.4Hz) para ECG");
                break;
            case SignalType::EMG:
                mux.selectChannel(MuxChannel::CH1_EMG_1K0);
                Serial.println("[MUX] Canal seleccionado: CH1 (1.0kΩ, Fc=159Hz) para EMG");
                break;
            case SignalType::PPG:
                mux.selectChannel(MuxChannel::CH2_PPG_25K);
                Serial.println("[MUX] Canal seleccionado: CH2 (25kΩ, Fc=6.37Hz) para PPG");
                break;
            default:
                Serial.println("[MUX] ADVERTENCIA: Señal desconocida, manteniendo canal actual");
                break;
        }
        Serial.printf("[MUX] Canal activo: %d (%s), Fc=%.1f Hz\n", 
                     mux.getCurrentChannel(), 
                     mux.getChannelName(),
                     mux.getCutoffFrequency());
        
        // ========================================================================
        // Configurar modelo según tipo
        // IMPORTANTE: Llamar reset() ANTES de setParameters() para que
        // la morfología de la condición no sea sobrescrita por initializeWaveParams()
        // ========================================================================
        switch (type) {
            case SignalType::ECG: {
                ecgModel.reset();  // Primero reset (carga defaults)
                yield();  // Alimentar watchdog
                ECGParameters params;
                params.condition = (ECGCondition)condition;
                ecgModel.setParameters(params);  // Luego aplicar condición
                yield();  // Alimentar watchdog
                Serial.printf("[ECG] Condición: %d (%s)\n", 
                             condition, ecgModel.getConditionName());
                Serial.printf("[ECG] hrMean=%.0f, currentRR=%.0fms, measuredRR=%.0fms\n",
                             ecgModel.getHRMean(), 
                             ecgModel.getCurrentRRInterval(),  // currentRR * 1000
                             ecgModel.getRRInterval_ms());     // measuredRR_ms
                break;
            }
            case SignalType::EMG: {
                emgModel.reset();  // Primero reset
                yield();  // Alimentar watchdog
                EMGParameters params;
                params.condition = (EMGCondition)condition;
                emgModel.setParameters(params);  // Luego aplicar condición
                yield();  // Alimentar watchdog
                Serial.printf("[EMG] Condición: %d (%s)\n", 
                             condition, emgModel.getConditionName());
                Serial.printf("[EMG] Excitación: %.2f%%\n",
                             emgModel.getCurrentExcitation() * 100.0f);
                break;
            }
            case SignalType::PPG: {
                ppgModel.reset();  // Primero reset
                yield();  // Alimentar watchdog
                PPGParameters params;
                params.condition = (PPGCondition)condition;
                ppgModel.setParameters(params);  // Luego aplicar condición
                yield();  // Alimentar watchdog
                break;
            }
            default:
                xSemaphoreGive(signalMutex);
                return false;
        }
        
        // Pre-llenar buffer
        prefillBuffer();
        
        // Iniciar timer
        setupTimer();
        
        currentSignal.state = SignalState::RUNNING;
        
        xSemaphoreGive(signalMutex);
        return true;
    }
    return false;
}

bool SignalEngine::stopSignal() {
    if (xSemaphoreTake(signalMutex, portMAX_DELAY) == pdTRUE) {
        stopTimer();
        currentSignal.state = SignalState::STOPPED;
        currentSignal.type = SignalType::NONE;
        dacWrite(DAC_SIGNAL_PIN, DAC_CENTER_VALUE);
        xSemaphoreGive(signalMutex);
        return true;
    }
    return false;
}

bool SignalEngine::pauseSignal() {
    if (currentSignal.state == SignalState::RUNNING) {
        stopTimer();
        currentSignal.state = SignalState::PAUSED;
        return true;
    }
    return false;
}

bool SignalEngine::resumeSignal() {
    if (currentSignal.state == SignalState::PAUSED) {
        setupTimer();
        currentSignal.state = SignalState::RUNNING;
        return true;
    }
    return false;
}

// ============================================================================
// TIMER
// ============================================================================
void SignalEngine::setupTimer() {
    // Timer a Fs_timer (4 kHz)
    // Criterio: Fs_timer >= Fs_modelo_máximo (EMG=2000) con margen 2×
    signalTimer = timerBegin(0, 80, true);  // 80 prescaler = 1 MHz
    timerAttachInterrupt(signalTimer, &timerISR, true);
    timerAlarmWrite(signalTimer, 1000000 / FS_TIMER_HZ, true);  // 250 us = 4 kHz
    timerAlarmEnable(signalTimer);
    Serial.println("[DAC] Timer ISR iniciado a 4 kHz");
}

void SignalEngine::stopTimer() {
    if (signalTimer != nullptr) {
        timerAlarmDisable(signalTimer);
        timerDetachInterrupt(signalTimer);
        timerEnd(signalTimer);
        signalTimer = nullptr;
        Serial.println("[DAC] Timer ISR detenido");
    }
}

// ============================================================================
// ISR DEL TIMER (en IRAM)
// ============================================================================
// DAC escribe a Fs_timer (4 kHz) SIN decimación para espectro correcto
// - ECG: fmax=150 Hz, EMG: fmax=500 Hz → 4 kHz cumple Nyquist
// - Nextion y Serial Plotter aplican su propia decimación (son solo visualización)
// - Filtro RC analógico completa reconstrucción de señal continua
void IRAM_ATTR SignalEngine::timerISR() {
    uint32_t startTime = micros();
    
    // Leer del buffer circular y escribir DIRECTAMENTE al DAC (sin decimación)
    if (bufferReadIndex != bufferWriteIndex) {
        lastDACValue = signalBuffer[bufferReadIndex];
        bufferReadIndex = (bufferReadIndex + 1) % SIGNAL_BUFFER_SIZE;
        
        // DAC escribe a 4 kHz - espectro frecuencial correcto
        dacWrite(DAC_SIGNAL_PIN, lastDACValue);
    } else {
        bufferUnderruns++;
    }
    
    isrCount++;
    
    uint32_t elapsed = micros() - startTime;
    if (elapsed > isrMaxTime) {
        isrMaxTime = elapsed;
    }
}

// ============================================================================
// TAREA DE GENERACIÓN CON TIMING REAL
// ============================================================================
// Arquitectura correcta:
// 1. Cada modelo genera a su propia Fs (ECG@750, EMG@2000, PPG@100 Hz)
// 2. Las muestras se interpolan linealmente para llenar buffer a Fs_timer
// 3. Timer ISR consume buffer a Fs_timer (4 kHz)
// 4. Downsampling para display = Fs_timer / Fds
void SignalEngine::generationTask(void* parameter) {
    SignalEngine* engine = (SignalEngine*)parameter;
    
    // Inicializar timing
    lastModelTick_us = micros();
    interpolationCounter = 0;
    
    while (true) {
        if (engine->currentSignal.state == SignalState::RUNNING) {
            uint32_t now_us = micros();
            
            // Obtener parámetros según tipo de señal
            uint32_t modelTickInterval_us;
            uint8_t upsampleRatio;
            float modelDeltaTime;
            
            switch (engine->currentSignal.type) {
                case SignalType::ECG:
                    modelTickInterval_us = MODEL_TICK_US_ECG;
                    upsampleRatio = UPSAMPLE_RATIO_ECG;
                    modelDeltaTime = MODEL_DT_ECG;
                    break;
                case SignalType::EMG:
                    modelTickInterval_us = MODEL_TICK_US_EMG;
                    upsampleRatio = UPSAMPLE_RATIO_EMG;
                    modelDeltaTime = MODEL_DT_EMG;
                    break;
                case SignalType::PPG:
                    modelTickInterval_us = MODEL_TICK_US_PPG;
                    upsampleRatio = UPSAMPLE_RATIO_PPG;
                    modelDeltaTime = MODEL_DT_PPG;
                    break;
                default:
                    modelTickInterval_us = 1000;
                    upsampleRatio = 1;
                    modelDeltaTime = 0.001f;
            }
            
            // ¿Es hora de generar nueva muestra del modelo?
            if (now_us - lastModelTick_us >= modelTickInterval_us) {
                lastModelTick_us = now_us;
                
                // Guardar muestra anterior para interpolación
                previousModelSample = currentModelSample;
                
                // Generar nueva muestra del modelo con su deltaTime correcto
                switch (engine->currentSignal.type) {
                    case SignalType::ECG: {
                        currentModelSample = engine->ecgModel.getDACValue(modelDeltaTime);
                        currentModelValueMV = engine->ecgModel.getCurrentValueMV();
                        break;
                    }
                    case SignalType::EMG: {
                        // Usar tick() para actualizar secuencia + generar muestra
                        engine->emgModel.tick(modelDeltaTime);
                        
                        // Seleccionar salida DAC según configuración (RAW o ENVELOPE)
                        if (engine->emgDacOutput == EMGDACOutput::ENVELOPE) {
                            currentModelSample = engine->emgModel.getProcessedDACValue();
                            currentModelValueMV = engine->emgModel.getProcessedSample();
                        } else {
                            // Por defecto: RAW
                            currentModelSample = engine->emgModel.getRawDACValue();
                            currentModelValueMV = engine->emgModel.getRawSample();
                        }
                        break;
                    }
                    case SignalType::PPG: {
                        currentModelSample = engine->ppgModel.getDACValue(modelDeltaTime);
                        // Guardar valor AC para interpolación (evita escalones en Nextion)
                        currentModelValueMV = engine->ppgModel.getLastACValue();
                        break;
                    }
                    default:
                        currentModelSample = DAC_CENTER_VALUE;
                        currentModelValueMV = 0.0f;
                }
                
                // Resetear contador de interpolación
                interpolationCounter = 0;
            }
            
            // Llenar buffer con muestras interpoladas a Fs_timer
            uint16_t readIdx = bufferReadIndex;
            uint16_t writeIdx = bufferWriteIndex;
            uint16_t available = (readIdx - writeIdx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE;
            
            while (available > 0) {
                // Interpolación lineal: sample = prev + (curr - prev) * t
                float t = (float)interpolationCounter / (float)upsampleRatio;
                int16_t interpolated = previousModelSample + 
                                       (int16_t)((currentModelSample - previousModelSample) * t);
                float interpolatedMV = previousModelValueMV + 
                                       (currentModelValueMV - previousModelValueMV) * t;
                
                // Clamp a rango DAC
                if (interpolated < 0) interpolated = 0;
                if (interpolated > 255) interpolated = 255;
                
                // Guardar en buffer para DAC a 4 kHz
                // El suavizado se logra mediante:
                // 1. Interpolación lineal (upsampling de modelo a 4kHz)
                // 2. Filtro RC analógico (fc=159 Hz)
                signalBuffer[writeIdx] = (uint8_t)interpolated;
                displayBuffer[writeIdx] = interpolatedMV;
                writeIdx = (writeIdx + 1) % SIGNAL_BUFFER_SIZE;
                bufferWriteIndex = writeIdx;
                available--;
                engine->currentSignal.sampleCount++;
                
                // Avanzar contador de interpolación
                interpolationCounter++;
                if (interpolationCounter >= upsampleRatio) {
                    interpolationCounter = 0;
                    previousModelValueMV = currentModelValueMV;
                }
            }
            
            // ================================================================
            // LLENAR BUFFER WEBSOCKET (frecuencia igual a Nextion)
            // ECG: 200 Hz, EMG/PPG: 100 Hz
            // ================================================================
            uint32_t now_ws = micros();
            if (now_ws - lastWSSampleTime_us >= wsSampleInterval_us) {
                lastWSSampleTime_us = now_ws;
                
                // Calcular siguiente índice de escritura
                uint8_t nextWriteIdx = (wsBufferWriteIdx + 1) % WS_SAMPLE_BUFFER_SIZE;
                
                // Solo escribir si hay espacio (evitar sobrescribir datos no leídos)
                if (nextWriteIdx != wsBufferReadIdx) {
                    WSSampleData& sample = wsBuffer[wsBufferWriteIdx];
                    sample.timestamp = millis();
                    sample.valid = true;
                    
                    // Obtener valor según tipo de señal
                    switch (engine->currentSignal.type) {
                        case SignalType::ECG:
                            sample.value = engine->ecgModel.getCurrentValueMV();
                            sample.envelope = 0;
                            break;
                        case SignalType::EMG:
                            sample.value = engine->emgModel.getCurrentValueMV();
                            sample.envelope = engine->emgModel.getProcessedSample();
                            break;
                        case SignalType::PPG:
                            sample.value = engine->ppgModel.getLastACValue();
                            sample.envelope = 0;
                            break;
                        default:
                            sample.value = 0;
                            sample.envelope = 0;
                    }
                    
                    wsBufferWriteIdx = nextWriteIdx;
                }
            }
        }
        
        // Pequeño delay para no saturar CPU
        vTaskDelay(1);
    }
}

// ============================================================================
// GENERACIÓN DE MUESTRA (legacy, para compatibilidad)
// ============================================================================
uint8_t SignalEngine::generateSample() {
    return currentModelSample;
}

// ============================================================================
// PRE-LLENADO DE BUFFER
// ============================================================================
void SignalEngine::prefillBuffer() {
    for (int i = 0; i < SIGNAL_BUFFER_SIZE / 2; i++) {
        signalBuffer[i] = generateSample();
        displayBuffer[i] = 0.0f;
    }
    bufferWriteIndex = SIGNAL_BUFFER_SIZE / 2;
}

// ============================================================================
// GETTERS
// ============================================================================
uint8_t SignalEngine::getLastDACValue() const {
    return lastDACValue;
}

PerformanceStats SignalEngine::getStats() const {
    PerformanceStats stats;
    stats.isrCount = isrCount;
    stats.isrMaxTime = isrMaxTime;
    stats.bufferUnderruns = bufferUnderruns;
    stats.bufferLevel = (bufferWriteIndex - bufferReadIndex + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE;
    stats.freeHeap = ESP.getFreeHeap();
    return stats;
}

bool SignalEngine::getDisplaySample(uint32_t sampleIndex, float& outValue) const {
    uint32_t currentCount = currentSignal.sampleCount;
    if (sampleIndex == 0 || sampleIndex > currentCount) {
        return false;
    }
    
    uint32_t delta = currentCount - sampleIndex;
    if (delta >= SIGNAL_BUFFER_SIZE) {
        return false;
    }
    
    int32_t idx = (int32_t)bufferWriteIndex - (int32_t)delta - 1;
    if (idx < 0) {
        idx += SIGNAL_BUFFER_SIZE;
    }
    
    outValue = displayBuffer[idx];
    return true;
}

// ============================================================================
// ACTUALIZACIÓN DE PARÁMETROS
// ============================================================================
void SignalEngine::updateNoiseLevel(float noise) {
    // Parámetro Tipo A: aplicación inmediata
    noise = constrain(noise, 0.0f, 1.0f);
    
    switch (currentSignal.type) {
        case SignalType::ECG:
            currentSignal.ecg.noiseLevel = noise;
            ecgModel.setNoiseLevel(noise);
            break;
        case SignalType::EMG:
            currentSignal.emg.noiseLevel = noise;
            emgModel.setNoiseLevel(noise);
            break;
        case SignalType::PPG:
            currentSignal.ppg.noiseLevel = noise;
            ppgModel.setNoiseLevel(noise);
            break;
        default:
            break;
    }
}

void SignalEngine::updateAmplitude(float amplitude) {
    // Parámetro Tipo A: aplicación inmediata
    switch (currentSignal.type) {
        case SignalType::ECG:
            currentSignal.ecg.qrsAmplitude = amplitude;
            ecgModel.setAmplitude(amplitude);
            break;
        case SignalType::EMG:
            currentSignal.emg.amplitude = amplitude;
            emgModel.setAmplitude(amplitude);
            break;
        case SignalType::PPG:
            currentSignal.ppg.perfusionIndex = amplitude;
            ppgModel.setAmplitude(amplitude);
            break;
        default:
            break;
    }
}

void SignalEngine::setECGParameters(const ECGParameters& params) {
    ecgModel.setPendingParameters(params);
}

void SignalEngine::setEMGParameters(const EMGParameters& params) {
    emgModel.setPendingParameters(params);
}

void SignalEngine::setPPGParameters(const PPGParameters& params) {
    ppgModel.setPendingParameters(params);
}

// ============================================================================
// CONFIGURACIÓN SALIDA DAC EMG
// ============================================================================
void SignalEngine::setEMGDACOutput(EMGDACOutput output) {
    emgDacOutput = output;
    Serial.printf("[SignalEngine] EMG DAC Output: %s\n", 
                  output == EMGDACOutput::RAW ? "RAW" : "ENVELOPE");
}

// ============================================================================
// BUFFER WEBSOCKET SINCRONIZADO
// ============================================================================
bool SignalEngine::getNextWSSample(WSSampleData& outSample) {
    // Verificar si hay datos disponibles
    if (wsBufferReadIdx == wsBufferWriteIdx) {
        return false;  // Buffer vacío
    }
    
    // Leer muestra del buffer
    outSample = wsBuffer[wsBufferReadIdx];
    
    // Avanzar índice de lectura
    wsBufferReadIdx = (wsBufferReadIdx + 1) % WS_SAMPLE_BUFFER_SIZE;
    
    return outSample.valid;
}

uint8_t SignalEngine::getWSBufferCount() const {
    if (wsBufferWriteIdx >= wsBufferReadIdx) {
        return wsBufferWriteIdx - wsBufferReadIdx;
    } else {
        return WS_SAMPLE_BUFFER_SIZE - wsBufferReadIdx + wsBufferWriteIdx;
    }
}
