/**
 * @file nextion_driver.h
 * @brief Driver para pantalla Nextion NX8048T070 (7" 800x480)
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Comunicación serial con la pantalla Nextion.
 * Manejo de eventos UI, actualización de waveforms y métricas.
 */

#ifndef NEXTION_DRIVER_H
#define NEXTION_DRIVER_H

#include <Arduino.h>
#include "../config.h"
#include "../data/signal_types.h"

// ============================================================================
// PÁGINAS NEXTION (deben coincidir con el .HMI)
// ============================================================================
enum class NextionPage : uint8_t {
    PORTADA = 0,        // Splash/bienvenida
    MENU = 1,           // Selección de señal (ECG/EMG/PPG)
    ECG_SIM = 2,        // Selección condición ECG (8 condiciones)
    EMG_SIM = 3,        // Selección condición EMG (6 condiciones)
    PPG_SIM = 4,        // Selección condición PPG (6 condiciones)
    WAVEFORM_ECG = 5,   // Waveform ECG + valores integrados (281x240)
    PARAMETROS_ECG = 6, // Popup parámetros ECG
    WAVEFORM_EMG = 7,   // Waveform EMG + valores integrados (281x240)
    PARAMETROS_EMG = 8, // Popup parámetros EMG
    WAVEFORM_PPG = 9,   // Waveform PPG + valores integrados (281x240)
    PARAMETROS_PPG = 10 // Popup parámetros PPG
};

// ============================================================================
// EVENTOS DE UI
// ============================================================================
enum class UIEvent : uint8_t {
    NONE = 0,
    
    // Portada
    BUTTON_COMENZAR,        // Botón "Comenzar" en portada
    
    // Menú selección de señal
    BUTTON_ECG,             // Selección ECG
    BUTTON_EMG,             // Selección EMG
    BUTTON_PPG,             // Selección PPG
    BUTTON_IR,              // Botón "Ir" (navegar a simulación)
    
    // Simulación (común a ECG/EMG/PPG)
    BUTTON_CONDITION,       // param = índice condición (0-9)
    BUTTON_START,           // Iniciar/Play simulación
    BUTTON_PAUSE,           // Pausar simulación
    BUTTON_STOP,            // Detener y volver a menú
    BUTTON_ATRAS,           // Regresar
    
    // Popups waveform
    BUTTON_PARAMETROS,      // Mostrar popup parámetros
    BUTTON_APPLY_PARAMS,    // bt_act: Aplicar parámetros y cerrar
    BUTTON_CANCEL_PARAMS,   // bt_ex: Cancelar sin guardar
    BUTTON_RESET_PARAMS,    // bt_reset: Resetear a valores por defecto
    
    // Sliders ECG (parametros_ecg página 7)
    SLIDER_ECG_HR,          // Slider frecuencia cardíaca (ID 10)
    SLIDER_ECG_AMP,         // Slider amplitud QRS (ID 11)
    SLIDER_ECG_NOISE,       // Slider nivel de ruido (ID 12)
    SLIDER_ECG_HRV,         // Slider variabilidad HRV (ID 13)
    
    // Sliders EMG (parametros_emg página 10)
    SLIDER_EMG_EXC,         // Slider excitación (ID 8)
    SLIDER_EMG_AMP,         // Slider amplitud (ID 9)
    SLIDER_EMG_NOISE,       // Slider ruido (ID 10)
    
    // Sliders PPG (parametros_ppg página 10)
    SLIDER_PPG_HR,          // Slider frecuencia cardíaca (ID 4)
    SLIDER_PPG_PI,          // Slider índice de perfusión (ID 5)
    SLIDER_PPG_NOISE,       // Slider ruido (ID 6)
    SLIDER_PPG_AMP,         // Slider factor amplitud (ID 14)
    
    // EMG DAC Output Selection (waveform_emg página 7)
    BUTTON_EMG_DAC_RAW,     // bt1 (ID 27) - Enviar RAW al DAC
    BUTTON_EMG_DAC_ENV      // bt0 (ID 26) - Enviar Envelope al DAC
};

// ============================================================================
// ESTRUCTURA PARA MÉTRICAS EN DISPLAY
// ============================================================================
struct DisplayMetrics {
    // ECG
    float heartRate;
    float rrInterval;
    float qrsAmplitude;
    float stLevel;
    
    // EMG
    float excitationLevel;
    int activeMotorUnits;
    float rmsAmplitude;
    
    // PPG
    float perfusionIndex;
    
    // Común
    float noiseLevel;
    float amplitude;
};

// ============================================================================
// CALLBACK PARA EVENTOS
// ============================================================================
typedef void (*UIEventCallback)(UIEvent event, uint8_t param);

// ============================================================================
// CLASE NextionDriver
// ============================================================================
class NextionDriver {
private:
    HardwareSerial& serial;
    UIEventCallback eventCallback;
    
    // Buffer de recepción
    uint8_t rxBuffer[32];
    uint8_t rxIndex;
    unsigned long lastRxTime;  // Para timeout de buffer
    
    // Estado
    NextionPage currentPage;
    SignalType displayedSignal;
    
    // Métodos privados
    void sendCommand(const char* cmd);
    void sendEndSequence();
    void parseEvent();
    
public:
    NextionDriver(HardwareSerial& serialPort);
    
    // Inicialización
    bool begin();
    
    // Procesar eventos entrantes (llamar en loop)
    void process();
    
    // Navegación
    void goToPage(NextionPage page);
    NextionPage getCurrentPage() const { return currentPage; }
    
    // Actualizar botones del menú (selección de señal)
    void updateMenuButtons(SignalType selected);
    
    // Actualizar botones de condiciones ECG (página ECG_SIM)
    void updateECGConditionButtons(int selectedCondition);

    // Actualizar botones de condiciones EMG (página EMG_SIM)
    void updateEMGConditionButtons(int selectedCondition);

    // Actualizar botones de condiciones PPG (página PPG_SIM)
    void updatePPGConditionButtons(int selectedCondition);
    
    // Actualizar textos
    void setText(const char* component, const char* text);
    void setNumber(const char* component, int value);
    void setFloat(const char* component, float value, uint8_t decimals = 1);
    
    // Waveform
    void addWaveformPoint(uint8_t componentId, uint8_t channel, uint8_t value);
    void clearWaveform(uint8_t componentId, uint8_t channel);
    void setWaveformWritePosition(uint8_t componentId, uint8_t channel, uint16_t position);
    
    // Comando genérico (para casos especiales)
    void sendRawCommand(const char* cmd);
    
    // Sliders
    void setSliderValue(const char* component, int value);
    void setSliderLimits(const char* component, int minVal, int maxVal);
    int getSliderValue(const char* component);
    
    // Visibilidad
    void setVisible(const char* component, bool visible);
    
    // Configurar condiciones dinámicas (página 2)
    void setupConditionPage(SignalType signalType);
    
    // Actualizar métricas en pantalla de simulación
    void updateMetrics(const DisplayMetrics& metrics, SignalType type);
    
    // Estado de simulación
    void setSimulationState(SignalState state);
    
    // Actualizar valores en página valores_ecg (sobrecarga simple)
    void updateECGValuesPage(int bpm, int rr_ms, int rAmp_x100, int st_x100, 
                              uint32_t beats, const char* patologia);
    
    // Actualizar valores ECG con TODAS las métricas
    void updateECGValuesPage(int bpm, int rr_ms, int pr_ms, int qrs_ms, int qtc_ms,
                              int p_x100, int q_x100, int r_x100, int s_x100, 
                              int t_x100, int st_x100, const char* patologia);
    
    // Actualizar valores en página valores_emg
    void updateEMGValuesPage(int raw_x100, int env_x100, int rms_x100, int activeUnits, 
                              int freq_x10, int contraction, const char* condicion);
    
    // Actualizar valores en página valores_ppg (sobrecarga simple)
    void updatePPGValuesPage(int hr, int rr_ms, int pi_x10,
                              uint32_t beats, const char* condicion);
    
    // Actualizar valores PPG con TODAS las métricas (incluye DC para DAC)
    void updatePPGValuesPage(int ac_x10, int hr, int rr_ms, int pi_x10, 
                              int sys_ms, int dia_ms, int dc_mV, const char* condicion);
    
    // Configurar página parametros_ecg con límites según patología
    void setupECGParametersPage(int hrMin, int hrMax, int hrCurrent,
                                 int ampCurrent, int noiseCurrent, int hrvCurrent);
    
    // Actualizar escala mV/div en waveform_ecg y parametros_ecg
    void updateECGScale(int zoomPercent);
    
    // Actualizar etiquetas de escala fijas por señal (según Tabla 9.6)
    void updateECGScaleLabels();   // 0.2 mV/div, 350 ms/div
    void updateEMGScaleLabels();   // RAW: 1.0 mV/div, ENV: 0.2 mV/div, 700 ms/div
    void updatePPGScaleLabels();   // 15 mV/div, 700 ms/div
    
    // Configurar página parametros_emg
    void setupEMGParametersPage(int excCurrent, int ampCurrent, int noiseCurrent);
    
    // Configurar página parametros_ppg
    void setupPPGParametersPage(int hrCurrent, int piCurrent, int noiseCurrent, int ampCurrent);
    
    // Leer valor de un slider (retorna -1 si error)
    int readSliderValue(const char* sliderName);
    
    // Callback
    void setEventCallback(UIEventCallback callback);
};

#endif // NEXTION_DRIVER_H
