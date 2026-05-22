/**
 * @file main.cpp
 * @brief BioSignalSimulator Pro - Punto de entrada principal
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Sistema de generación de señales biomédicas (ECG, EMG, PPG).
 * pio run -e esp32_wroom32 --target upload
 * 
 * ARQUITECTURA:
 * - Core 0: UI (Nextion + Serial)
 * - Core 1: Generación de señales (tiempo real)
 * 
 * HARDWARE:
 * - ESP32-WROOM-32 @ 240MHz
 * - Nextion NX8048T070 (800x480)
 * - DAC salida GPIO25 (0-3.3V, 8-bit)
 */

#include <Arduino.h>
#include "config.h"
#include "data/signal_types.h"
#include "data/param_limits.h"
#include "core/signal_engine.h"
#include "core/state_machine.h"
#include "core/param_controller.h"
#include "comm/nextion_driver.h"
#include "comm/serial_handler.h"
#include "comm/wifi_server.h"
#include "hw/cd4051_mux.h"

// ============================================================================
// INSTANCIAS GLOBALES
// ============================================================================
SignalEngine* signalEngine = nullptr;
NextionDriver* nextion = nullptr;
SerialHandler* serialHandler = nullptr;
StateMachine stateMachine;
ParamController paramController;

// ============================================================================
// VARIABLES TEMPORALES PARA SLIDERS ECG
// Almacenan valores mientras el popup está abierto, se aplican al cerrar
// ============================================================================
struct ECGSliderValues {
    int hr = 75;        // Frecuencia cardíaca (BPM) - inicia en valor medio de rango
    int zoom = 100;     // Zoom visual (50-200%), NO afecta modelo ni DAC
    int noise = 0;      // Ruido × 100 (0.00) - inicia en 0
    int hrv = 0;        // Variabilidad HRV (%) - inicia en 0
    bool modified = false;  // ¿Se modificó algún valor?
} ecgSliderValues;

// ============================================================================
// VARIABLES TEMPORALES PARA SLIDERS EMG
// Almacenan valores mientras el popup está abierto, se aplican al cerrar
// ============================================================================
struct EMGSliderValues {
    int exc = 0;        // Excitación (0-100%) - inicia en 0
    int amp = 100;      // Amplitud × 100 (1.00 factor) - inicia en 100 (sin modificación)
    int noise = 0;      // Ruido × 100 (0.00) - inicia en 0
    bool modified = false;
} emgSliderValues;

// ============================================================================
// VARIABLES TEMPORALES PARA SLIDERS PPG
// Almacenan valores mientras el popup está abierto, se aplican al cerrar
// ============================================================================
struct PPGSliderValues {
    int hr = 75;        // Frecuencia cardíaca (BPM) - inicia en valor medio de rango
    int pi = 50;        // Índice perfusión × 10 (5.0%) - inicia en valor medio
    int noise = 0;      // Ruido × 100 (0.00) - inicia en 0
    int amp = 100;      // Factor amplificación (50-200%), se aplica al modelo
    bool modified = false;
} ppgSliderValues;

// ============================================================================
// PROTOTIPOS
// ============================================================================
void initializeHardware();
void initializeLED();
void setLEDState(SignalState state);
void handleUIEvent(UIEvent event, uint8_t param);
void handleSerialCommand(uint8_t cmd, uint8_t* data, uint16_t len);
void handleStateChange(SystemState oldState, SystemState newState);
void updateDisplay();

// ============================================================================
// LED RGB
// ============================================================================
void initializeLED() {
#if LED_RGB_ENABLED
    // Configurar canales PWM para control de intensidad
    ledcSetup(0, 5000, 8);  // Canal 0, 5kHz, 8 bits
    ledcSetup(1, 5000, 8);  // Canal 1, 5kHz, 8 bits
    ledcSetup(2, 5000, 8);  // Canal 2, 5kHz, 8 bits
    
    ledcAttachPin(LED_RGB_RED, 0);
    ledcAttachPin(LED_RGB_GREEN, 1);
    ledcAttachPin(LED_RGB_BLUE, 2);
    
    // Apagar todos
    ledcWrite(0, LED_RGB_COMMON_ANODE ? 255 : 0);
    ledcWrite(1, LED_RGB_COMMON_ANODE ? 255 : 0);
    ledcWrite(2, LED_RGB_COMMON_ANODE ? 255 : 0);
#endif
    pinMode(LED_STATUS, OUTPUT);
}

void setLEDState(SignalState state) {
#if LED_RGB_ENABLED
    uint8_t r = 0, g = 0, b = 0;
    
    switch (state) {
        case SignalState::STOPPED:
            // Amarillo cálido: rojo completo, verde reducido
            r = 255; g = 50; b = 0;
            break;
        case SignalState::RUNNING:
            // Verde: señal activa, generando forma de onda
            r = 0; g = 255; b = 0;
            break;
        case SignalState::PAUSED:
            // Rojo: simulación detenida o en pausa
            r = 255; g = 0; b = 0;
            break;
        case SignalState::ERROR:
            // Rojo parpadeante (por ahora solo rojo fijo)
            r = 255; g = 0; b = 0;
            break;
    }
    
    if (LED_RGB_COMMON_ANODE) {
        ledcWrite(0, 255 - r);
        ledcWrite(1, 255 - g);
        ledcWrite(2, 255 - b);
    } else {
        ledcWrite(0, r);
        ledcWrite(1, g);
        ledcWrite(2, b);
    }
#endif
}

// ============================================================================
// CALLBACKS
// ============================================================================
void handleUIEvent(UIEvent event, uint8_t param) {
    switch (event) {
        // Portada
        case UIEvent::BUTTON_COMENZAR:
            stateMachine.processEvent(SystemEvent::GO_TO_MENU);
            nextion->goToPage(NextionPage::MENU);
            break;
        
        // Menú - Selección de señal (solo selecciona, NO navega)
        case UIEvent::BUTTON_ECG:
            stateMachine.processEvent(SystemEvent::SELECT_ECG);
            nextion->updateMenuButtons(SignalType::ECG);
            break;
            
        case UIEvent::BUTTON_EMG:
            Serial.println("[UI] BUTTON_EMG presionado");
            stateMachine.processEvent(SystemEvent::SELECT_EMG);
            nextion->updateMenuButtons(SignalType::EMG);
            break;
            
        case UIEvent::BUTTON_PPG:
            Serial.println("[UI] BUTTON_PPG presionado");
            stateMachine.processEvent(SystemEvent::SELECT_PPG);
            nextion->updateMenuButtons(SignalType::PPG);
            break;
        
        case UIEvent::BUTTON_IR:
            if (stateMachine.getState() == SystemState::MENU) {
                SignalType selected = stateMachine.getSelectedSignal();
                switch (selected) {
                    case SignalType::ECG:
                        nextion->goToPage(NextionPage::ECG_SIM);
                        delay(60); // dar tiempo a que la página cargue antes de pintar botones
                        nextion->updateECGConditionButtons(stateMachine.getSelectedCondition());
                        break;
                    case SignalType::EMG:
                        nextion->goToPage(NextionPage::EMG_SIM);
                        delay(60);
                        nextion->updateEMGConditionButtons(stateMachine.getSelectedCondition());
                        break;
                    case SignalType::PPG:
                        nextion->goToPage(NextionPage::PPG_SIM);
                        delay(60);
                        nextion->updatePPGConditionButtons(stateMachine.getSelectedCondition());
                        break;
                    default:
                        break;
                }
                if (selected != SignalType::NONE) {
                    stateMachine.processEvent(SystemEvent::GO_TO_CONDITION);
                }
            } else if (stateMachine.getState() == SystemState::SELECT_CONDITION) {
                // Leer la condición seleccionada del Nextion antes de navegar
                int selectedCondition = -1;
                switch (stateMachine.getSelectedSignal()) {
                    case SignalType::ECG: {
                        int hmiButtonIndex = nextion->readSliderValue("sel_ecg");
                        Serial.printf("[UI] Leyendo sel_ecg del Nextion (botón HMI): %d\n", hmiButtonIndex);
                        // Convertir índice de botón HMI a ECGCondition enum:
                        // HMI: 0=Normal, 1=Taq, 2=Bra, 3=Bloqueo, 4=FA, 5=FV, 6=STEMI, 7=Isquemia
                        // Enum: 0=NORMAL, 1=TACH, 2=BRAD, 3=AFIB, 4=VFIB, 5=AVB1, 6=STE, 7=STD
                        switch (hmiButtonIndex) {
                            case 0: selectedCondition = 0; break;  // Normal → NORMAL
                            case 1: selectedCondition = 1; break;  // Taq → TACHYCARDIA
                            case 2: selectedCondition = 2; break;  // Bra → BRADYCARDIA
                            case 3: selectedCondition = 5; break;  // Bloqueo → AV_BLOCK_1
                            case 4: selectedCondition = 3; break;  // FA → ATRIAL_FIBRILLATION
                            case 5: selectedCondition = 4; break;  // FV → VENTRICULAR_FIBRILLATION
                            case 6: selectedCondition = 6; break;  // STEMI → ST_ELEVATION
                            case 7: selectedCondition = 7; break;  // Isquemia → ST_DEPRESSION
                            default: selectedCondition = -1; break;
                        }
                        Serial.printf("[UI] Convertido a ECGCondition enum: %d\n", selectedCondition);
                        break;
                    }
                    case SignalType::EMG:
                        Serial.println("[DEBUG] Antes de leer sel_emg");
                        selectedCondition = nextion->readSliderValue("sel_emg");
                        Serial.printf("[DEBUG] sel_emg leído: %d\n", selectedCondition);
                        Serial.printf("[UI] Leyendo sel_emg del Nextion: %d\n", selectedCondition);
                        break;
                    case SignalType::PPG:
                        selectedCondition = nextion->readSliderValue("sel_ppg");
                        Serial.printf("[UI] Leyendo sel_ppg del Nextion: %d\n", selectedCondition);
                        break;
                    default:
                        break;
                }
                
                // Actualizar condición en stateMachine si se leyó correctamente
                if (selectedCondition >= 0) {
                    stateMachine.processEvent(SystemEvent::SELECT_CONDITION, selectedCondition);
                    Serial.printf("[UI] Condición actualizada en stateMachine: %d\n", stateMachine.getSelectedCondition());
                }
                
                NextionPage waveformPage = NextionPage::WAVEFORM_ECG;
                switch (stateMachine.getSelectedSignal()) {
                    case SignalType::ECG: 
                        waveformPage = NextionPage::WAVEFORM_ECG; 
                        break;
                    case SignalType::EMG: 
                        waveformPage = NextionPage::WAVEFORM_EMG; 
                        break;
                    case SignalType::PPG: 
                        waveformPage = NextionPage::WAVEFORM_PPG; 
                        break;
                    default: break;
                }
                nextion->goToPage(waveformPage);
                nextion->clearWaveform(WAVEFORM_COMPONENT_ID, 0);
                
                // Actualizar etiquetas de escala fijas según Tabla 9.6
                switch (stateMachine.getSelectedSignal()) {
                    case SignalType::ECG: 
                        nextion->updateECGScaleLabels();  // 0.2 mV/div, 350 ms/div
                        break;
                    case SignalType::EMG: 
                        nextion->updateEMGScaleLabels();  // RAW: 1.0 mV/div, ENV: 1.0 mV/div, 700 ms/div
                        break;
                    case SignalType::PPG: 
                        nextion->updatePPGScaleLabels();  // 15 mV/div, 700 ms/div
                        break;
                    default: break;
                }
                
                // NO iniciar automáticamente - esperar a que usuario presione PLAY
                // El estado queda en SELECT_CONDITION hasta que presione PLAY
                Serial.println("[UI] Navegando a waveform - esperando PLAY para iniciar");
            }
            break;
            
        case UIEvent::BUTTON_ATRAS:
            stateMachine.processEvent(SystemEvent::BACK);
            // Navegar a la página correspondiente según el nuevo estado
            switch (stateMachine.getState()) {
                case SystemState::PORTADA:
                    nextion->goToPage(NextionPage::PORTADA);
                    break;
                case SystemState::MENU:
                    nextion->goToPage(NextionPage::MENU);
                    // Despintar todos los botones al volver al menú
                    nextion->updateMenuButtons(SignalType::NONE);
                    break;
                default:
                    break;
            }
            break;
            
        // Selección de condición
        case UIEvent::BUTTON_CONDITION:
            Serial.printf("[UI] BUTTON_CONDITION presionado - param=%d\n", param);
            stateMachine.processEvent(SystemEvent::SELECT_CONDITION, param);
            Serial.printf("[UI] Condición guardada en stateMachine: %d\n", stateMachine.getSelectedCondition());
            // Actualizar botones según el tipo de señal
            if (stateMachine.getSelectedSignal() == SignalType::ECG) {
                nextion->updateECGConditionButtons(param);
            } else if (stateMachine.getSelectedSignal() == SignalType::EMG) {
                nextion->updateEMGConditionButtons(param);
            } else if (stateMachine.getSelectedSignal() == SignalType::PPG) {
                nextion->updatePPGConditionButtons(param);
            }
            break;
            
        // Controles de simulación (en páginas waveform)
        case UIEvent::BUTTON_START:
            Serial.printf("[UI] BUTTON_START recibido - Estado actual: %d\n", (int)stateMachine.getState());
            // Si estamos en SELECT_CONDITION, leer la condición del Nextion antes de continuar
            if (stateMachine.getState() == SystemState::SELECT_CONDITION) {
                int selectedCondition = -1;
                switch (stateMachine.getSelectedSignal()) {
                    case SignalType::ECG: {
                        int hmiButtonIndex = nextion->readSliderValue("sel_ecg");
                        Serial.printf("[UI] PLAY - Leyendo sel_ecg (botón HMI): %d\n", hmiButtonIndex);
                        // Convertir índice de botón HMI a ECGCondition enum
                        switch (hmiButtonIndex) {
                            case 0: selectedCondition = 0; break;  // Normal → NORMAL
                            case 1: selectedCondition = 1; break;  // Taq → TACHYCARDIA
                            case 2: selectedCondition = 2; break;  // Bra → BRADYCARDIA
                            case 3: selectedCondition = 5; break;  // Bloqueo → AV_BLOCK_1
                            case 4: selectedCondition = 3; break;  // FA → ATRIAL_FIBRILLATION
                            case 5: selectedCondition = 4; break;  // FV → VENTRICULAR_FIBRILLATION
                            case 6: selectedCondition = 6; break;  // STEMI → ST_ELEVATION
                            case 7: selectedCondition = 7; break;  // Isquemia → ST_DEPRESSION
                            default: selectedCondition = -1; break;
                        }
                        Serial.printf("[UI] Convertido a ECGCondition: %d\n", selectedCondition);
                        break;
                    }
                    case SignalType::EMG:
                        Serial.println("[DEBUG] PLAY - Antes de leer sel_emg");
                        selectedCondition = nextion->readSliderValue("sel_emg");
                        Serial.printf("[DEBUG] PLAY - sel_emg leído: %d\n", selectedCondition);
                        Serial.printf("[UI] PLAY - Leyendo sel_emg del Nextion: %d\n", selectedCondition);
                        break;
                    case SignalType::PPG: {
                        int hmiButtonIndex = nextion->readSliderValue("sel_ppg");
                        Serial.printf("[UI] PLAY - Leyendo sel_ppg (botón HMI): %d\n", hmiButtonIndex);
                        // Mapeo directo: botones HMI coinciden con enum PPGCondition
                        // HMI y Enum: 0=Normal, 1=Arritmia, 2=PerfDébil, 3=Vasoconstr, 4=PerfFuerte, 5=Vasodil
                        if (hmiButtonIndex >= 0 && hmiButtonIndex <= 5) {
                            selectedCondition = hmiButtonIndex;  // Mapeo directo 1:1
                        } else {
                            selectedCondition = -1;
                        }
                        Serial.printf("[UI] Convertido a PPGCondition: %d\n", selectedCondition);
                        break;
                    }
                    default:
                        break;
                }
                
                // Actualizar condición en stateMachine si se leyó correctamente
                if (selectedCondition >= 0) {
                    stateMachine.processEvent(SystemEvent::SELECT_CONDITION, selectedCondition);
                    Serial.printf("[UI] Condición actualizada: %d\n", stateMachine.getSelectedCondition());
                }
                
                Serial.println("[DEBUG] Llamando GO_TO_WAVEFORM");
                stateMachine.processEvent(SystemEvent::GO_TO_WAVEFORM);
                Serial.printf("[DEBUG] Estado después de GO_TO_WAVEFORM: %d\n", (int)stateMachine.getState());
            }
            
            // PLAY: Si está pausado, reanudar. Si está corriendo, reiniciar.
            if (stateMachine.getState() == SystemState::PAUSED) {
                // Reanudar desde donde se pausó (continuar onda)
                stateMachine.processEvent(SystemEvent::RESUME);
                wifiServer.setStreamingEnabled(true);  // Reanudar streaming WiFi
                Serial.println("[UI] PLAY: Reanudando señal");
            } else {
                // Reiniciar desde cero (limpiar waveform)
                nextion->clearWaveform(WAVEFORM_COMPONENT_ID, 0);
                stateMachine.processEvent(SystemEvent::START_SIMULATION);
                wifiServer.setStreamingEnabled(true);  // Habilitar streaming WiFi
                Serial.println("[UI] PLAY: Iniciando/Reiniciando señal");
            }
            break;
            
        case UIEvent::BUTTON_PAUSE:
            // PAUSE: Solo pausar (no alternar)
            if (stateMachine.getState() == SystemState::SIMULATING) {
                stateMachine.processEvent(SystemEvent::PAUSE);
                Serial.println("[UI] PAUSE: Pausando señal");
            }
            break;
            
        case UIEvent::BUTTON_STOP:
            // Serial.println("[UI] STOP presionado");
            stateMachine.processEvent(SystemEvent::STOP);
            // Deshabilitar streaming WiFi
            wifiServer.setStreamingEnabled(false);
            // Resetear sliders a valores del modelo (no guardar cambios)
            switch (stateMachine.getSelectedSignal()) {
                case SignalType::ECG: {
                    ECGModel& ecg = signalEngine->getECGModel();
                    ecgSliderValues.hr = (int)ecg.getHRMean();
                    ecgSliderValues.noise = (int)(ecg.getNoiseLevel() * 100);
                    ecgSliderValues.hrv = (int)(ecg.getHRStd() / ecg.getHRMean() * 100);
                    ecgSliderValues.modified = false;
                    nextion->goToPage(NextionPage::ECG_SIM);
                    delay(60);
                    nextion->updateECGConditionButtons(stateMachine.getSelectedCondition());
                    break;
                }
                case SignalType::EMG: {
                    EMGModel& emg = signalEngine->getEMGModel();
                    emgSliderValues.exc = (int)(emg.getExcitation() * 100);
                    emgSliderValues.amp = (int)(emg.getAmplitude() * 100);
                    emgSliderValues.noise = (int)(emg.getNoiseLevel() * 100);
                    emgSliderValues.modified = false;
                    nextion->goToPage(NextionPage::EMG_SIM);
                    delay(60);
                    nextion->updateEMGConditionButtons(stateMachine.getSelectedCondition());
                    break;
                }
                case SignalType::PPG: {
                    PPGModel& ppg = signalEngine->getPPGModel();
                    ppgSliderValues.hr = (int)ppg.getCurrentHeartRate();
                    ppgSliderValues.pi = (int)(ppg.getPerfusionIndex() * 10);
                    ppgSliderValues.noise = (int)(ppg.getNoiseLevel() * 100);
                    ppgSliderValues.modified = false;
                    nextion->goToPage(NextionPage::PPG_SIM);
                    delay(60);
                    nextion->updatePPGConditionButtons(stateMachine.getSelectedCondition());
                    break;
                }
                default:
                    break;
            }
            break;
        
        // Popups (páginas waveform)
        // NOTA: BUTTON_VALORES eliminado - valores ahora integrados en waveform
            
        case UIEvent::BUTTON_PARAMETROS:
            // Ir a página parametros y configurar sliders
            if (stateMachine.getSelectedSignal() == SignalType::ECG) {
                nextion->goToPage(NextionPage::PARAMETROS_ECG);
                ECGModel& ecg = signalEngine->getECGModel();
                // NO leer del modelo - mantener valores del slider
                // Los valores en ecgSliderValues representan la posición del slider
                ecgSliderValues.modified = false;
                
                float hrMin, hrMax;
                ecg.getHRRange(hrMin, hrMax);
                nextion->setupECGParametersPage(
                    (int)hrMin, (int)hrMax,
                    ecgSliderValues.hr,
                    ecgSliderValues.zoom,  // Zoom visual (50-200%)
                    ecgSliderValues.noise,
                    ecgSliderValues.hrv
                );
            } else if (stateMachine.getSelectedSignal() == SignalType::EMG) {
                nextion->goToPage(NextionPage::PARAMETROS_EMG);
                // NO leer del modelo - mantener valores del slider
                // Los valores en emgSliderValues representan la posición del slider
                emgSliderValues.modified = false;
                
                nextion->setupEMGParametersPage(
                    emgSliderValues.exc,
                    emgSliderValues.amp,
                    emgSliderValues.noise
                );
            } else if (stateMachine.getSelectedSignal() == SignalType::PPG) {
                nextion->goToPage(NextionPage::PARAMETROS_PPG);
                // NO leer del modelo - mantener valores del slider
                // Los valores en ppgSliderValues representan la posición del slider
                ppgSliderValues.modified = false;
                
                nextion->setupPPGParametersPage(
                    ppgSliderValues.hr,
                    ppgSliderValues.pi,
                    ppgSliderValues.noise,
                    ppgSliderValues.amp
                );
            }
            break;
        
        // NOTA: BUTTON_BACK_POPUP eliminado - no hay popups de valores separados
        
        case UIEvent::BUTTON_APPLY_PARAMS:
            // bt_act: Aplicar cambios de sliders - usar métodos directos para no resetear secuencias
            if (stateMachine.getSelectedSignal() == SignalType::ECG) {
                if (ecgSliderValues.modified) {
                    ECGModel& ecg = signalEngine->getECGModel();
                    // Métodos directos - no resetea el modelo
                    ecg.setHeartRate((float)ecgSliderValues.hr);
                    ecg.setNoiseLevel(ecgSliderValues.noise / 100.0f);
                    ecg.setWaveformGain(ecgSliderValues.zoom / 100.0f);  // 50-200% → 0.5-2.0
                    nextion->updateECGScale(ecgSliderValues.zoom);
                    Serial.printf("[UI] ECG: HR=%d, Ruido=%d%%, Ganancia=%d%%\n", 
                                  ecgSliderValues.hr, ecgSliderValues.noise, ecgSliderValues.zoom);
                }
                ecgSliderValues.modified = false;
                nextion->goToPage(NextionPage::WAVEFORM_ECG);
                nextion->updateECGScaleLabels();
            } else if (stateMachine.getSelectedSignal() == SignalType::EMG) {
                if (emgSliderValues.modified) {
                    EMGModel& emg = signalEngine->getEMGModel();
                    // Métodos directos - NO resetea secuencias de contracción
                    emg.setExcitationLevel(emgSliderValues.exc / 100.0f);
                    emg.setNoiseLevel(emgSliderValues.noise / 100.0f);
                    emg.setWaveformGain(emgSliderValues.amp / 100.0f);  // 50-200% → 0.5-2.0
                    Serial.printf("[UI] EMG: Exc=%d%%, Ruido=%d%%, Ganancia=%d%%\n", 
                                  emgSliderValues.exc, emgSliderValues.noise, emgSliderValues.amp);
                }
                emgSliderValues.modified = false;
                nextion->goToPage(NextionPage::WAVEFORM_EMG);
                nextion->updateEMGScaleLabels();
            } else if (stateMachine.getSelectedSignal() == SignalType::PPG) {
                if (ppgSliderValues.modified) {
                    PPGModel& ppg = signalEngine->getPPGModel();
                    // Métodos directos
                    ppg.setHeartRate((float)ppgSliderValues.hr);
                    ppg.setNoiseLevel(ppgSliderValues.noise / 100.0f);
                    ppg.setWaveformGain(ppgSliderValues.amp / 100.0f);  // 50-200% → 0.5-2.0
                    Serial.printf("[UI] PPG: HR=%d, Ruido=%d%%, Ganancia=%d%%\n", 
                                  ppgSliderValues.hr, ppgSliderValues.noise, ppgSliderValues.amp);
                }
                ppgSliderValues.modified = false;
                nextion->goToPage(NextionPage::WAVEFORM_PPG);
                nextion->updatePPGScaleLabels();
            }
            break;
        
        case UIEvent::BUTTON_CANCEL_PARAMS:
            // bt_ex: Cancelar sin guardar - restaurar valores originales del modelo
            if (stateMachine.getSelectedSignal() == SignalType::ECG) {
                // Restaurar valores desde el modelo (descartar cambios temporales)
                ECGModel& ecg = signalEngine->getECGModel();
                ecgSliderValues.hr = (int)ecg.getHRMean();
                ecgSliderValues.noise = (int)(ecg.getNoiseLevel() * 100);
                ecgSliderValues.hrv = (int)(ecg.getHRStd() / ecg.getHRMean() * 100);
                // zoom se mantiene (es solo visual)
                ecgSliderValues.modified = false;
                Serial.println("[UI] Cambios ECG descartados - valores restaurados");
                nextion->goToPage(NextionPage::WAVEFORM_ECG);
                nextion->updateECGScaleLabels();
            } else if (stateMachine.getSelectedSignal() == SignalType::EMG) {
                // Restaurar valores desde el modelo
                EMGModel& emg = signalEngine->getEMGModel();
                emgSliderValues.exc = (int)(emg.getCurrentExcitation() * 100);
                emgSliderValues.amp = (int)(emg.getAmplitude() * 100);
                emgSliderValues.noise = (int)(emg.getNoiseLevel() * 100);
                emgSliderValues.modified = false;
                Serial.println("[UI] Cambios EMG descartados - valores restaurados");
                nextion->goToPage(NextionPage::WAVEFORM_EMG);
                nextion->updateEMGScaleLabels();
            } else if (stateMachine.getSelectedSignal() == SignalType::PPG) {
                // Restaurar valores desde el modelo
                PPGModel& ppg = signalEngine->getPPGModel();
                ppgSliderValues.hr = (int)ppg.getCurrentHeartRate();
                ppgSliderValues.pi = (int)(ppg.getPerfusionIndex() * 10);
                ppgSliderValues.noise = (int)(ppg.getNoiseLevel() * 100);
                // amp se mantiene (es solo visual)
                ppgSliderValues.modified = false;
                Serial.println("[UI] Cambios PPG descartados - valores restaurados");
                nextion->goToPage(NextionPage::WAVEFORM_PPG);
                nextion->updatePPGScaleLabels();
            }
            break;
        
        case UIEvent::BUTTON_RESET_PARAMS:
            // Resetear modelo a valores por defecto de la patología
            if (stateMachine.getSelectedSignal() == SignalType::ECG) {
                ECGModel& ecg = signalEngine->getECGModel();
                ECGCondition currentCond = ecg.getCondition();
                ecg.reset();
                ECGParameters params;
                params.condition = currentCond;
                ecg.setParameters(params);
                
                ecgSliderValues.hr = (int)ecg.getHRMean();
                ecgSliderValues.zoom = 100;  // Reset zoom a 100%
                ecgSliderValues.noise = (int)(ecg.getNoiseLevel() * 100);
                ecgSliderValues.hrv = (int)(ecg.getHRStd() / ecg.getHRMean() * 100);
                ecgSliderValues.modified = false;
                
                float hrMin, hrMax;
                ecg.getHRRange(hrMin, hrMax);
                nextion->setupECGParametersPage(
                    (int)hrMin, (int)hrMax,
                    ecgSliderValues.hr,
                    ecgSliderValues.zoom,
                    ecgSliderValues.noise,
                    ecgSliderValues.hrv
                );
                nextion->updateECGScale(ecgSliderValues.zoom);
                Serial.println("[UI] Parámetros ECG reseteados, Zoom: 100%");
            } else if (stateMachine.getSelectedSignal() == SignalType::EMG) {
                EMGModel& emg = signalEngine->getEMGModel();
                EMGCondition currentCond = emg.getCondition();
                emg.reset();
                EMGParameters params;
                params.condition = currentCond;
                emg.setParameters(params);
                
                emgSliderValues.exc = (int)(emg.getCurrentExcitation() * 100);
                emgSliderValues.amp = (int)(emg.getAmplitude() * 100);
                emgSliderValues.noise = (int)(emg.getNoiseLevel() * 100);
                emgSliderValues.modified = false;
                
                nextion->setupEMGParametersPage(
                    emgSliderValues.exc,
                    emgSliderValues.amp,
                    emgSliderValues.noise
                );
                Serial.println("[UI] Parámetros EMG reseteados");
            } else if (stateMachine.getSelectedSignal() == SignalType::PPG) {
                PPGModel& ppg = signalEngine->getPPGModel();
                PPGCondition currentCond = ppg.getCondition();
                ppg.reset();
                PPGParameters params;
                params.condition = currentCond;
                ppg.setParameters(params);
                
                ppgSliderValues.hr = (int)ppg.getCurrentHeartRate();
                ppgSliderValues.pi = (int)(ppg.getPerfusionIndex() * 10);
                ppgSliderValues.noise = (int)(ppg.getNoiseLevel() * 100);
                ppgSliderValues.amp = 100;  // Reset amp a 100%
                ppgSliderValues.modified = false;
                
                nextion->setupPPGParametersPage(
                    ppgSliderValues.hr,
                    ppgSliderValues.pi,
                    ppgSliderValues.noise,
                    ppgSliderValues.amp
                );
                Serial.println("[UI] Parámetros PPG reseteados, Amp: 100%");
            }
            break;
        
        // Sliders ECG - Aplican límites según condición actual
        case UIEvent::SLIDER_ECG_HR:
            {
                int hrValue = nextion->readSliderValue("h_hr");
                if (hrValue > 0) {
                    // Aplicar límites según condición actual
                    ECGCondition cond = signalEngine->getECGModel().getCondition();
                    ECGLimits limits = getECGLimits(cond);
                    int minHR = (int)limits.heartRate.min;
                    int maxHR = (int)limits.heartRate.max;
                    hrValue = constrain(hrValue, minHR, maxHR);
                    ecgSliderValues.hr = hrValue;
                    ecgSliderValues.modified = true;
                    Serial.printf("[UI] Slider HR: %d BPM (límites %d-%d, pendiente aplicar)\n", 
                                 hrValue, minHR, maxHR);
                }
            }
            break;
            
        case UIEvent::SLIDER_ECG_AMP:
            {
                int zoomValue = nextion->readSliderValue("h_amp");
                if (zoomValue >= 50 && zoomValue <= 200) {
                    ecgSliderValues.zoom = zoomValue;
                    ecgSliderValues.modified = true;
                    // Actualizar etiqueta de escala en tiempo real
                    nextion->updateECGScale(zoomValue);
                    Serial.printf("[UI] Slider Zoom: %d%% (pendiente aplicar)\n", zoomValue);
                }
            }
            break;
            
        case UIEvent::SLIDER_ECG_NOISE:
            {
                int noiseValue = nextion->readSliderValue("h_noise");
                if (noiseValue >= 0) {
                    // Ruido: límite global 0-10%
                    noiseValue = constrain(noiseValue, 0, 10);
                    ecgSliderValues.noise = noiseValue;
                    ecgSliderValues.modified = true;
                    Serial.printf("[UI] Slider Ruido ECG: %d%% (pendiente aplicar)\n", noiseValue);
                }
            }
            break;
            
        case UIEvent::SLIDER_ECG_HRV:
            {
                int hrvValue = nextion->readSliderValue("h_hrv");
                if (hrvValue >= 0) {
                    // Aplicar límites HRV según condición actual
                    ECGCondition cond = signalEngine->getECGModel().getCondition();
                    HRVRange hrvLimits = getHRVLimits(cond);
                    int minHRV = (int)hrvLimits.minVar;
                    int maxHRV = (int)hrvLimits.maxVar;
                    hrvValue = constrain(hrvValue, minHRV, maxHRV);
                    ecgSliderValues.hrv = hrvValue;
                    ecgSliderValues.modified = true;
                    Serial.printf("[UI] Slider HRV: %d%% (límites %d-%d%%, pendiente aplicar)\n", 
                                 hrvValue, minHRV, maxHRV);
                }
            }
            break;
        
        // Sliders EMG - Aplican límites según condición actual
        case UIEvent::SLIDER_EMG_EXC:
            {
                int excValue = nextion->readSliderValue("h_exc");
                if (excValue >= 0) {
                    // Aplicar límites según condición actual
                    EMGCondition cond = signalEngine->getEMGModel().getCondition();
                    EMGLimits limits = getEMGLimits(cond);
                    int minExc = (int)(limits.excitationLevel.min * 100);
                    int maxExc = (int)(limits.excitationLevel.max * 100);
                    excValue = constrain(excValue, minExc, maxExc);
                    emgSliderValues.exc = excValue;
                    emgSliderValues.modified = true;
                    Serial.printf("[UI] Slider Excitación: %d%% (límites %d-%d%%, pendiente aplicar)\n", 
                                 excValue, minExc, maxExc);
                }
            }
            break;
            
        case UIEvent::SLIDER_EMG_AMP:
            {
                int ampValue = nextion->readSliderValue("h_amp");
                if (ampValue > 0) {
                    // Aplicar límites según condición actual
                    EMGCondition cond = signalEngine->getEMGModel().getCondition();
                    EMGLimits limits = getEMGLimits(cond);
                    int minAmp = (int)(limits.amplitude.min * 100);
                    int maxAmp = (int)(limits.amplitude.max * 100);
                    ampValue = constrain(ampValue, minAmp, maxAmp);
                    emgSliderValues.amp = ampValue;
                    emgSliderValues.modified = true;
                    Serial.printf("[UI] Slider Amplitud EMG: %d (límites %d-%d, pendiente aplicar)\n", 
                                 ampValue, minAmp, maxAmp);
                }
            }
            break;
            
        case UIEvent::SLIDER_EMG_NOISE:
            {
                int noiseValue = nextion->readSliderValue("h_noise");
                if (noiseValue >= 0) {
                    // Ruido: límite global 0-10%
                    noiseValue = constrain(noiseValue, 0, 10);
                    emgSliderValues.noise = noiseValue;
                    emgSliderValues.modified = true;
                    Serial.printf("[UI] Slider Ruido EMG: %d%% (pendiente aplicar)\n", noiseValue);
                }
            }
            break;
        
        // Sliders PPG - Aplican límites según condición actual
        case UIEvent::SLIDER_PPG_HR:
            {
                int hrValue = nextion->readSliderValue("h_hr");
                if (hrValue > 0) {
                    // Aplicar límites según condición actual
                    PPGCondition cond = signalEngine->getPPGModel().getCondition();
                    PPGLimits limits = getPPGLimits(cond);
                    int minHR = (int)limits.heartRate.min;
                    int maxHR = (int)limits.heartRate.max;
                    hrValue = constrain(hrValue, minHR, maxHR);
                    ppgSliderValues.hr = hrValue;
                    ppgSliderValues.modified = true;
                    Serial.printf("[UI] Slider HR PPG: %d BPM (límites %d-%d, pendiente aplicar)\n", 
                                 hrValue, minHR, maxHR);
                }
            }
            break;
            
        case UIEvent::SLIDER_PPG_PI:
            {
                int piValue = nextion->readSliderValue("h_pi");
                if (piValue > 0) {
                    // Aplicar límites según condición actual (PI × 10)
                    PPGCondition cond = signalEngine->getPPGModel().getCondition();
                    PPGLimits limits = getPPGLimits(cond);
                    int minPI = (int)(limits.perfusionIndex.min * 10);
                    int maxPI = (int)(limits.perfusionIndex.max * 10);
                    piValue = constrain(piValue, minPI, maxPI);
                    ppgSliderValues.pi = piValue;
                    ppgSliderValues.modified = true;
                    Serial.printf("[UI] Slider PI: %d (%.1f%%, límites %.1f-%.1f%%, pendiente aplicar)\n", 
                                 piValue, piValue/10.0f, limits.perfusionIndex.min, limits.perfusionIndex.max);
                }
            }
            break;
            
        case UIEvent::SLIDER_PPG_NOISE:
            {
                int noiseValue = nextion->readSliderValue("h_noise");
                if (noiseValue >= 0) {
                    // Ruido: límite global 0-10%
                    noiseValue = constrain(noiseValue, 0, 10);
                    ppgSliderValues.noise = noiseValue;
                    ppgSliderValues.modified = true;
                    Serial.printf("[UI] Slider Ruido PPG: %d%% (pendiente aplicar)\n", noiseValue);
                }
            }
            break;
            
        case UIEvent::SLIDER_PPG_AMP:
            {
                int ampValue = nextion->readSliderValue("h_amp");
                if (ampValue >= 50 && ampValue <= 200) {
                    // Factor de amplificación: 50-200% (se aplica al modelo)
                    ppgSliderValues.amp = ampValue;
                    ppgSliderValues.modified = true;
                    Serial.printf("[UI] Slider Amplificación PPG: %d%% (pendiente aplicar)\n", ampValue);
                }
            }
            break;
        
        // Botones EMG DAC Output Selection (waveform_emg página 7)
        case UIEvent::BUTTON_EMG_DAC_RAW:
            // bt1 (ID 27): Seleccionar señal RAW para salida DAC
            signalEngine->setEMGDACOutput(SignalEngine::EMGDACOutput::RAW);
            // Desactivar bt0 (ENVELOPE) para exclusión mutua
            nextion->sendRawCommand("bt0.val=0");
            Serial.println("[UI] EMG DAC Output: RAW");
            break;
            
        case UIEvent::BUTTON_EMG_DAC_ENV:
            // bt0 (ID 26): Seleccionar señal ENVELOPE para salida DAC
            signalEngine->setEMGDACOutput(SignalEngine::EMGDACOutput::ENVELOPE);
            // Desactivar bt1 (RAW) para exclusión mutua
            nextion->sendRawCommand("bt1.val=0");
            Serial.println("[UI] EMG DAC Output: ENVELOPE");
            break;
            
        default:
            break;
    }
}

void handleSerialCommand(uint8_t cmd, uint8_t* data, uint16_t len) {
    // TODO: Implementar protocolo binario
    Serial.printf("[Serial] Comando: 0x%02X, Len: %d\n", cmd, len);
}

void handleStateChange(SystemState oldState, SystemState newState) {
    Serial.printf("[State] Cambio de estado: %d -> %d\n", (int)oldState, (int)newState);
    
    // Verificar que signalEngine está inicializado
    if (!signalEngine) {
        Serial.println("[State] ERROR: SignalEngine no inicializado!");
        return;
    }
    
    switch (newState) {
        case SystemState::PORTADA:
            // No navegamos aquí, la navegación se maneja en handleUIEvent
            signalEngine->stopSignal();
            setLEDState(SignalState::STOPPED);
            break;
            
        case SystemState::MENU:
            // No navegamos aquí, la navegación se maneja en handleUIEvent
            signalEngine->stopSignal();
            setLEDState(SignalState::STOPPED);
            break;
            
        case SystemState::SELECT_CONDITION:
            // Detener la señal al volver a la pantalla de condiciones
            signalEngine->stopSignal();
            setLEDState(SignalState::STOPPED);
            break;
            
        case SystemState::SIMULATING:
            // Verificar si venimos de PAUSED (RESUME) o de otro estado (START)
            if (oldState == SystemState::PAUSED) {
                // RESUME: Reanudar sin reiniciar - mantener continuidad de onda
                signalEngine->resumeSignal();
                setLEDState(SignalState::RUNNING);
                // NO resetear contadores para mantener continuidad
                // NO llamar startSignal() para no reiniciar desde cero
            } else {
                // START: Iniciar nueva simulación desde cero
                Serial.printf("[State] Iniciando señal: Tipo=%d, Condición=%d\n",
                             (int)stateMachine.getSelectedSignal(),
                             stateMachine.getSelectedCondition());
                signalEngine->startSignal(
                    stateMachine.getSelectedSignal(),
                    stateMachine.getSelectedCondition()
                );
                delay(100);  // Dar tiempo al sistema para estabilizarse después de cambiar señal
                setLEDState(SignalState::RUNNING);
                // Resetear contador de display para forzar redibujado desde cero
                extern void resetDisplayCounters();
                resetDisplayCounters();
                // Actualizar escalas de visualización según tipo de señal
                if (stateMachine.getSelectedSignal() == SignalType::ECG) {
                    nextion->updateECGScale(ecgSliderValues.zoom);
                }
            }
            // Serial.printf("[State] Estado SignalEngine: %d (0=STOPPED, 1=RUNNING)\n", 
            //              (int)signalEngine->getState());
            break;
            
        case SystemState::PAUSED:
            signalEngine->pauseSignal();
            setLEDState(SignalState::PAUSED);
            break;
            
        default:
            break;
    }
}

// ============================================================================
// ACTUALIZACIÓN DE DISPLAY
// ============================================================================
// Variable estática para tracking de muestras
static uint32_t lastSampleCount = 0;

// NOTA: Sin interpolación - envío directo 1 muestra = 1 punto Nextion
// Escalas: ECG 350 ms/div (3.5s), EMG/PPG 700 ms/div (7.0s)

// Función para resetear contadores (llamada al iniciar nueva simulación)
void resetDisplayCounters() {
    lastSampleCount = 0;
}

void updateDisplay() {
    static unsigned long lastUpdate = 0;
    
    unsigned long now = millis();
    
    // =========================================================================
    // WAVEFORM: Arquitectura unificada con signal_engine (contador de ticks)
    // Downsampling respecto a Fs_timer (2kHz) usando NEXTION_DOWNSAMPLE_*
    // ECG: 2000/200 = 10:1 → 200 Hz efectivo
    // EMG: 2000/100 = 20:1 → 100 Hz efectivo
    // PPG: 2000/100 = 20:1 → 100 Hz efectivo
    // =========================================================================
    if (signalEngine->getState() == SignalState::RUNNING) {
        uint32_t currentSampleCount = signalEngine->getSignalData().sampleCount;
        SignalType type = signalEngine->getCurrentType();
        
        // Determinar ratio de downsampling según tipo de señal
        uint8_t downsampleRatio;
        switch (type) {
            case SignalType::ECG: downsampleRatio = NEXTION_DOWNSAMPLE_ECG; break;
            case SignalType::EMG: downsampleRatio = NEXTION_DOWNSAMPLE_EMG; break;
            case SignalType::PPG: downsampleRatio = NEXTION_DOWNSAMPLE_PPG; break;
            default: downsampleRatio = 10; break;
        }
        
        // Enviar puntos cada vez que crucemos el múltiplo del ratio, incluso si se acumularon muestras
        if (currentSampleCount > lastSampleCount) {
            uint32_t samplesProcessed = currentSampleCount - lastSampleCount;

            // Limitar el procesamiento para evitar bloqueos si hubo un gran retraso
            const uint32_t maxSamples = downsampleRatio * 4;  // ≈20 ms de búfer para ECG
            if (samplesProcessed > maxSamples) {
                samplesProcessed = maxSamples;
                lastSampleCount = currentSampleCount - samplesProcessed;
            }

            for (uint32_t i = 1; i <= samplesProcessed; ++i) {
                uint32_t sampleIndex = lastSampleCount + i;
                if (sampleIndex % downsampleRatio != 0) {
                    continue;
                }
                
                float mV_value = 0.0f;
                bool hasSample = signalEngine->getDisplaySample(sampleIndex, mV_value);

                if (type == SignalType::ECG && hasSample) {
                    // ECG: Un solo canal - SIN interpolación (prueba directa)
                    ECGModel& ecg = signalEngine->getECGModel();
                    uint8_t waveValue = ecg.getWaveformValue();
                    nextion->addWaveformPoint(WAVEFORM_COMPONENT_ID, 0, waveValue);
                    
                } else if (type == SignalType::EMG) {
                    // EMG: DOS canales - SIN interpolación (prueba directa)
                    EMGModel& emg = signalEngine->getEMGModel();
                    uint8_t ch0_value = emg.getWaveformValue_Ch0();
                    uint8_t ch1_value = emg.getWaveformValue_Ch1();
                    nextion->addWaveformPoint(WAVEFORM_COMPONENT_ID, 0, ch0_value);
                    nextion->addWaveformPoint(WAVEFORM_COMPONENT_ID, 1, ch1_value);
                    
                } else if (type == SignalType::PPG) {
                    // PPG: Un solo canal - SIN interpolación (prueba directa)
                    PPGModel& ppg = signalEngine->getPPGModel();
                    uint8_t waveValue = ppg.getWaveformValue();
                    nextion->addWaveformPoint(WAVEFORM_COMPONENT_ID, 0, waveValue);
                    
                } else {
                    continue; // sin muestra disponible
                }
            }

            lastSampleCount = currentSampleCount;
        }
    }
    
    // Actualizar métricas y valores en pantalla a 4 Hz
    if (now - lastUpdate >= METRICS_UPDATE_MS) {
        SystemState sysState = stateMachine.getState();
        if (sysState == SystemState::SIMULATING || sysState == SystemState::PAUSED) {
            SignalType type = signalEngine->getCurrentType();
            
            // Actualizar valores integrados en waveforms
            switch (type) {
                case SignalType::ECG: {
                    ECGModel& ecg = signalEngine->getECGModel();
                    // HR: 3 enteros (ws0=3, ws1=0)
                    int bpm = (int)ecg.getCurrentBPM();
                    
                    // RR: 4 enteros (ws0=4, ws1=0)
                    int rr = (int)ecg.getCurrentRR_ms();
                    
                    // PR, QRS, QTc: 3 enteros (ws0=3, ws1=0)
                    int pr = (int)ecg.getPRInterval_ms();
                    int qrs = (int)ecg.getQRSDuration_ms();
                    int qtc = (int)ecg.getQTcInterval_ms();
                    
                    // Amplitudes: 1 entero + 2 decimales (ws0=3, ws1=2) → enviar × 100
                    int p_x100 = (int)(ecg.getPAmplitude_mV() * 100);
                    int q_x100 = (int)(ecg.getQAmplitude_mV() * 100);
                    int r_x100 = (int)(ecg.getRAmplitude_mV() * 100);
                    int s_x100 = (int)(ecg.getSAmplitude_mV() * 100);
                    int t_x100 = (int)(ecg.getTAmplitude_mV() * 100);
                    int st_x100 = (int)(ecg.getSTDeviation_mV() * 100);
                    
                    nextion->updateECGValuesPage(bpm, rr, pr, qrs, qtc,
                                                p_x100, q_x100, r_x100, s_x100, t_x100, st_x100,
                                                ecg.getConditionName());
                    
                    // Debug: Imprimir cada 4 segundos
                    static unsigned long lastDebug = 0;
                    if (millis() - lastDebug > 4000) {
                        Serial.printf("[ECG] BPM=%d, RR=%d, PR=%d, QRS=%d, QTc=%d, P=%.2f, Q=%.2f, R=%.2f, S=%.2f, T=%.2f, ST=%.2f\n", 
                                     bpm, rr, pr, qrs, qtc,
                                     ecg.getPAmplitude_mV(), ecg.getQAmplitude_mV(), ecg.getRAmplitude_mV(),
                                     ecg.getSAmplitude_mV(), ecg.getTAmplitude_mV(), ecg.getSTDeviation_mV());
                        lastDebug = millis();
                    }
                    break;
                }
                case SignalType::EMG: {
                    EMGModel& emg = signalEngine->getEMGModel();
                    
                    // Raw signal, Envolvente, RMS: 1 entero + 2 decimales (ws0=3, ws1=2) → enviar × 100
                    float rawValue = emg.getCurrentValueMV();
                    float envValue = emg.getProcessedSample();  // Envolvente procesada
                    int raw_x100 = (int)(rawValue * 100);
                    int env_x100 = (int)(envValue * 100);
                    int rms_x100 = (int)(emg.getRMSAmplitude() * 100);
                    
                    // Unidades motoras: 3 enteros (ws0=3, ws1=0)
                    int mu = emg.getActiveMotorUnits();
                    
                    // Frecuencia de disparo: 3 enteros + 1 decimal (ws0=4, ws1=1) → enviar × 10
                    int fr_x10 = (int)(emg.getMeanFiringRate() * 10);
                    
                    // Contracción %: 3 enteros (ws0=3, ws1=0)
                    int mvc = (int)emg.getContractionLevel();
                    
                    nextion->updateEMGValuesPage(raw_x100, env_x100, rms_x100, mu, fr_x10, mvc, emg.getConditionName());
                    
                    // Debug: Imprimir cada 4 segundos
                    static unsigned long lastDebugEMG = 0;
                    if (millis() - lastDebugEMG > 4000) {
                        Serial.printf("[EMG] RAW=%.2f, ENV=%.2f, RMS=%.2f mV, MU=%d, FR=%.1f Hz, MVC=%d%%, Cond=%s\n", 
                                     rawValue, envValue, emg.getRMSAmplitude(),
                                     mu, emg.getMeanFiringRate(), mvc,
                                     emg.getConditionName());
                        lastDebugEMG = millis();
                    }
                    break;
                }
                case SignalType::PPG: {
                    PPGModel& ppg = signalEngine->getPPGModel();
                    
                    // Señal AC: 3 enteros + 1 decimal (ws0=4, ws1=1) → enviar × 10
                    int ac_x10 = (int)(ppg.getPerfusionIndex() * 15.0f * 10);  // AC = PI × 15 mV, × 10
                    
                    // HR: 3 enteros (ID14, variable nhr)
                    int hr = (int)ppg.getCurrentHeartRate();
                    
                    // Intervalo RR: 4 enteros (ID15, variable nrr)
                    int rr = (int)ppg.getMeasuredRRInterval();
                    
                    // Índice de perfusión %: 2 enteros + 1 decimal (ws0=3, ws1=1) → enviar × 10
                    int pi_x10 = (int)(ppg.getPerfusionIndex() * 10);
                    
                    // Rangos sistólico y diastólico: 4 enteros (ws0=4, ws1=0)
                    int sys = (int)ppg.getMeasuredSystoleTime();
                    int dia = (int)ppg.getMeasuredDiastoleTime();
                    
                    // DC Baseline: 0 porque el DAC solo envía componente AC
                    // (El modelo interno usa DC=1000mV pero no se envía al DAC)
                    int dc = 0;
                    
                    nextion->updatePPGValuesPage(ac_x10, hr, rr, pi_x10, sys, dia, dc, ppg.getConditionName());
                    
                    // Debug: Imprimir cada 4 segundos
                    static unsigned long lastDebugPPG = 0;
                    if (millis() - lastDebugPPG > 4000) {
                        Serial.printf("[PPG] AC=%.1f mV, HR=%d, RR=%d, PI=%.1f%%, Sys=%d ms, Dia=%d ms\n", 
                                     ppg.getPerfusionIndex() * 15.0f, hr, rr, ppg.getPerfusionIndex(),
                                     sys, dia);
                        lastDebugPPG = millis();
                    }
                    break;
                }
                default:
                    break;
            }
        }
        lastUpdate = now;
    }
}

// ============================================================================
// SETUP
// ============================================================================
void setup() {
    // Iniciar Serial para debug
    Serial.begin(115200);
    delay(100);
    
    Serial.println("\n╔═══════════════════════════════════════════════╗");
    Serial.println("║     " DEVICE_NAME " v" FIRMWARE_VERSION "     ║");
    Serial.println("╚═══════════════════════════════════════════════╝");
    Serial.printf("Hardware: %s\n", HARDWARE_MODEL);
    Serial.printf("Free Heap: %d KB\n", ESP.getFreeHeap() / 1024);
    Serial.printf("Build: %s %s [EMG FIX]", __DATE__, __TIME__);
    
    // Inicializar LED
    initializeLED();
    setLEDState(SignalState::STOPPED);
    
    // Inicializar Nextion
    nextion = new NextionDriver(NEXTION_SERIAL);
    if (!nextion->begin()) {
        Serial.println("[ERROR] No se pudo inicializar Nextion");
    }
    nextion->setEventCallback(handleUIEvent);
    
    // Inicializar SerialHandler
    serialHandler = new SerialHandler(Serial);
    serialHandler->setCommandCallback(handleSerialCommand);
    
    // Inicializar multiplexor CD4051
    if (!mux.begin()) {
        Serial.println("[ERROR] No se pudo inicializar multiplexor CD4051");
    }
    
    // Inicializar motor de señales
    signalEngine = SignalEngine::getInstance();
    if (!signalEngine->begin()) {
        Serial.println("[ERROR] No se pudo inicializar SignalEngine");
        setLEDState(SignalState::ERROR);
        return;
    }
    
    // Configurar máquina de estados
    stateMachine.setStateChangeCallback(handleStateChange);
    stateMachine.processEvent(SystemEvent::INIT_COMPLETE);
    
    // Navegar a página inicial
    nextion->goToPage(NextionPage::PORTADA);
    
    // Inicializar WiFi Server
    Serial.println("\n[WiFi] Iniciando servidor web...");
    if (wifiServer.begin()) {
        Serial.println("[WiFi] Servidor iniciado correctamente");
        Serial.println("[WiFi] SSID: BioSignalSimulator_Pro");
        Serial.println("[WiFi] Pass: biosignal123");
        Serial.println("[WiFi] URL: http://192.168.4.1");
    } else {
        Serial.println("[WiFi] ERROR: No se pudo iniciar servidor");
    }
    
    // LED verde: listo
    digitalWrite(LED_RGB_RED, LED_RGB_COMMON_ANODE ? HIGH : LOW);
    digitalWrite(LED_RGB_GREEN, LED_RGB_COMMON_ANODE ? LOW : HIGH);
    digitalWrite(LED_RGB_BLUE, LED_RGB_COMMON_ANODE ? HIGH : LOW);
    
    Serial.println("\n[OK] Sistema inicializado correctamente");
    Serial.println("Presione 'h' para ayuda\n");
}

// ============================================================================
// LOOP
// ============================================================================
void loop() {
    // Procesar eventos de Nextion
    nextion->process();
    
    // Procesar comandos serial
    serialHandler->process();
    
    // Actualizar display
    updateDisplay();
    
    // ============================================================================
    // DEBUG: ADC LOOPBACK CON DOWNSAMPLING PARA VISUALIZACIÓN
    // ============================================================================
    // ARQUITECTURA DE MUESTREO:
    // ┌─────────────────────────────────────────────────────────────────────────┐
    // │  Timer ISR @ 2000 Hz (FS_TIMER_HZ)                                      │
    // │  └─> DAC escribe señal a máxima resolución temporal                     │
    // │       └─> Filtro RC analógico suaviza escalones del DAC                 │
    // │            └─> Señal analógica lista para osciloscopio/ECG real         │
    // │                                                                          │
    // │  VISUALIZACIÓN (Serial Plotter):                                        │
    // │  └─> Downsampling + promediado (igual que Nextion)                      │
    // │       └─> ECG: 200 Hz (5ms) - Captura QRS de ~80ms con 16 puntos       │
    // │       └─> EMG/PPG: 100 Hz (10ms) - Señales más lentas, menos puntos    │
    // │                                                                          │
    // │  JUSTIFICACIÓN TÉCNICA:                                                 │
    // │  - DAC @ 2kHz: Suficiente para señales biomédicas (BW < 500 Hz)        │
    // │  - Visualización @ 100-200 Hz: Suficiente para percepción humana       │
    // │  - Promediado: Actúa como filtro anti-aliasing natural                  │
    // │  - Nyquist: ECG tiene componentes hasta ~150 Hz, 200 Hz es suficiente  │
    // └─────────────────────────────────────────────────────────────────────────┘
#if DEBUG_ADC_LOOPBACK
    if (signalEngine->getState() == SignalState::RUNNING) {
        static unsigned long lastADCRead_ms = 0;
        static float dacAccum = 0.0f;
        static float adcAccum = 0.0f;
        static uint8_t sampleCount = 0;
        
        // Acumular muestras a 2000 Hz para promediar (igual que Timer ISR)
        static unsigned long lastSample_us = 0;
        if (micros() - lastSample_us >= 500) {  // 500 µs = 2000 Hz
            lastSample_us = micros();
            
            uint16_t adcRaw = analogRead(ADC_LOOPBACK_PIN);
            float adcVoltage = (adcRaw / 4095.0f) * 3.3f;
            uint8_t lastDAC = signalEngine->getLastDACValue();
            float dacVoltage = (lastDAC / 255.0f) * 3.3f;
            
            dacAccum += dacVoltage;
            adcAccum += adcVoltage;
            sampleCount++;
        }
        
        // Determinar intervalo de downsampling según tipo de señal
        // ECG: 200 Hz (5ms) - Mayor resolución para QRS rápido
        // EMG/PPG: 100 Hz (10ms) - Señales más lentas
        uint8_t downsampleInterval_ms = 5;  // Default ECG @ 200 Hz
        SignalType currentType = signalEngine->getCurrentType();
        if (currentType == SignalType::EMG || currentType == SignalType::PPG) {
            downsampleInterval_ms = 10;  // EMG/PPG @ 100 Hz
        }
        
        // Enviar promedio al intervalo correspondiente
        if (millis() - lastADCRead_ms >= downsampleInterval_ms) {
            lastADCRead_ms = millis();
            
            if (sampleCount > 0) {
                float dacAvg = dacAccum / sampleCount;
                float adcAvg = adcAccum / sampleCount;
                
                // Formato VS Code Serial Plotter: >var1:value1,var2:value2\r\n
                Serial.print(">dac:");
                Serial.print(dacAvg, 3);
                Serial.print(",adc:");
                Serial.println(adcAvg, 3);
                
                // Reset acumuladores
                dacAccum = 0.0f;
                adcAccum = 0.0f;
                sampleCount = 0;
            }
        }
    }
#endif
    
    // Procesar WiFi Server
    wifiServer.loop();
    
    // Enviar datos a clientes WebSocket si hay señal activa
    // USAR BUFFER SINCRONIZADO para evitar aliasing y pausas
    if (wifiServer.getClientCount() > 0 && stateMachine.getState() == SystemState::SIMULATING) {
        SignalType type = signalEngine->getCurrentType();
        
        // Consumir TODAS las muestras disponibles del buffer sincronizado (100 Hz)
        WSSampleData wsSample;
        while (signalEngine->getNextWSSample(wsSample)) {
            WSSignalData wsData;
            memset(&wsData, 0, sizeof(wsData));
            
            // Usar valores del buffer sincronizado (no del modelo directamente)
            wsData.value = wsSample.value;
            wsData.envelope = wsSample.envelope;
            wsData.timestamp = wsSample.timestamp;
            wsData.dacValue = signalEngine->getLastDACValue();
            wsData.state = "RUNNING";
            
            switch (type) {
                case SignalType::ECG:
                    wsData.signalType = "ECG";
                    wsData.condition = signalEngine->getECGModel().getConditionName();
                    break;
                case SignalType::EMG:
                    wsData.signalType = "EMG";
                    wsData.condition = signalEngine->getEMGModel().getConditionName();
                    break;
                case SignalType::PPG:
                    wsData.signalType = "PPG";
                    wsData.condition = signalEngine->getPPGModel().getConditionName();
                    break;
                default:
                    break;
            }
            
            wifiServer.sendSignalData(wsData);
        }
        
        // Métricas se envían a menor frecuencia (controlado por wifi_server)
        WSSignalMetrics wsMetrics;
        memset(&wsMetrics, 0, sizeof(wsMetrics));
        
        switch (type) {
            case SignalType::ECG: {
                ECGModel& ecg = signalEngine->getECGModel();
                wsMetrics.hr = (int)ecg.getCurrentHeartRate();
                wsMetrics.rr = (int)ecg.getCurrentRRInterval();
                wsMetrics.qrs = ecg.getQRSAmplitude();
                wsMetrics.st = ecg.getSTDeviation_mV();
                wsMetrics.hrv = ecg.getHRStd();
                wsMetrics.pr = (int)ecg.getPRInterval_ms();
                wsMetrics.qtc = (int)ecg.getQTcInterval_ms();
                wsMetrics.p = ecg.getPAmplitude_mV();
                wsMetrics.r = ecg.getRAmplitude_mV();
                wsMetrics.t = ecg.getTAmplitude_mV();
                break;
            }
            case SignalType::EMG: {
                EMGModel& emg = signalEngine->getEMGModel();
                wsMetrics.rms = emg.getRMSAmplitude();
                wsMetrics.excitation = (int)(emg.getExcitation() * 100);
                wsMetrics.activeUnits = emg.getActiveMotorUnits();
                wsMetrics.freq = (int)emg.getFatigueMDF();
                wsMetrics.mvc = (int)emg.getContractionLevel();
                wsMetrics.raw = emg.getCurrentValueMV();
                break;
            }
            case SignalType::PPG: {
                PPGModel& ppg = signalEngine->getPPGModel();
                wsMetrics.hr = (int)ppg.getCurrentHeartRate();
                wsMetrics.rr = (int)ppg.getCurrentRRInterval();
                wsMetrics.pi = ppg.getPerfusionIndex();
                wsMetrics.ac = ppg.getLastACValue();
                wsMetrics.sys = (int)ppg.getMeasuredSystoleTime();
                wsMetrics.dia = (int)ppg.getMeasuredDiastoleTime();
                break;
            }
            default:
                break;
        }
        
        wifiServer.sendMetrics(wsMetrics);
    }
    
    // Pequeño delay para no saturar
    delay(1);
}
