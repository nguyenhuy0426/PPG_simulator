/**
 * @file signal_engine.h
 * @brief Motor de generación de señales en tiempo real
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Gestiona la generación de señales con buffer circular y timer ISR.
 */

#ifndef SIGNAL_ENGINE_H
#define SIGNAL_ENGINE_H

#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include "config.h"
#include "data/signal_types.h"
#include "models/ecg_model.h"
#include "models/emg_model.h"
#include "models/ppg_model.h"

// ============================================================================
// ESTADÍSTICAS DE PERFORMANCE
// ============================================================================
struct PerformanceStats {
    uint32_t isrCount;
    uint32_t isrMaxTime;
    uint32_t bufferUnderruns;
    uint16_t bufferLevel;
    uint32_t freeHeap;
};

// ============================================================================
// BUFFER PARA WEBSOCKET (muestras sincronizadas a 100 Hz)
// ============================================================================
#define WS_SAMPLE_BUFFER_SIZE 128  // Buffer circular para WebSocket (128 muestras = ~640ms @ 200Hz ECG)

struct WSSampleData {
    float value;      // Valor en mV
    float envelope;   // Envelope (solo EMG)
    uint32_t timestamp;
    bool valid;
};

// ============================================================================
// CLASE SignalEngine (Singleton)
// ============================================================================
class SignalEngine {
public:
    // Enum para selección de salida DAC EMG (debe estar antes de usarse)
    enum class EMGDACOutput : uint8_t {
        RAW = 0,      // Señal cruda (por defecto)
        ENVELOPE = 1  // Señal envolvente
    };

private:
    static SignalEngine* instance;
    SignalEngine();
    
    // Modelos de señales
    ECGModel ecgModel;
    EMGModel emgModel;
    PPGModel ppgModel;
    
    // Estado actual
    SignalData currentSignal;
    
    // Configuración salida DAC EMG (RAW por defecto)
    EMGDACOutput emgDacOutput;
    
    // FreeRTOS handles
    TaskHandle_t generationTaskHandle;
    SemaphoreHandle_t signalMutex;
    
    // Timer de hardware
    hw_timer_t* signalTimer;
    
    // Métodos privados
    void setupTimer();
    void stopTimer();
    void prefillBuffer();
    uint8_t generateSample();
    
    // Tareas FreeRTOS
    static void generationTask(void* parameter);
    static void IRAM_ATTR timerISR();
    
public:
    static SignalEngine* getInstance();
    
    // Inicialización
    bool begin();
    
    // Control de señales
    bool startSignal(SignalType type, uint8_t condition);
    bool stopSignal();
    bool pauseSignal();
    bool resumeSignal();
    
    // Actualizar parámetros (Tipo A - inmediatos)
    void updateNoiseLevel(float noise);
    void updateAmplitude(float amplitude);
    
    // Actualizar parámetros (Tipo B - diferidos)
    void setECGParameters(const ECGParameters& params);
    void setEMGParameters(const EMGParameters& params);
    void setPPGParameters(const PPGParameters& params);
    
    // Configuración de salida DAC para EMG
    void setEMGDACOutput(EMGDACOutput output);
    EMGDACOutput getEMGDACOutput() const { return emgDacOutput; }
    
    // Getters
    SignalState getState() const { return currentSignal.state; }
    SignalType getCurrentType() const { return currentSignal.type; }
    uint8_t getLastDACValue() const;
    SignalData getSignalData() const { return currentSignal; }
    PerformanceStats getStats() const;
    bool getDisplaySample(uint32_t sampleIndex, float& outValue) const;
    
    // Acceso a modelos para métricas
    ECGModel& getECGModel() { return ecgModel; }
    EMGModel& getEMGModel() { return emgModel; }
    PPGModel& getPPGModel() { return ppgModel; }
    
    // Buffer WebSocket sincronizado (100 Hz)
    bool getNextWSSample(WSSampleData& outSample);
    uint8_t getWSBufferCount() const;
};

#endif // SIGNAL_ENGINE_H
