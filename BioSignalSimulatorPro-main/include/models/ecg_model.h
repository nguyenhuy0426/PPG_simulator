/**
 * @file ecg_model.h
 * @brief Modelo ECG ECGSYN (McSharry, Clifford et al. 2003)
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Implementación fiel del modelo ECGSYN de MATLAB en C++ para ESP32.
 * 
 * REFERENCIA CIENTÍFICA:
 * McSharry PE, Clifford GD, Tarassenko L, Smith LA.
 * "A dynamical model for generating synthetic electrocardiogram signals."
 * IEEE Trans Biomed Eng. 2003;50(3):289-294.
 * DOI: 10.1109/TBME.2003.808805
 * 
 * PARÁMETROS DE MUESTREO:
 * - sfint = 2000 Hz (frecuencia interna de integración)
 * - sfecg = 500 Hz (frecuencia de muestreo de salida)
 * - sfint debe ser múltiplo entero de sfecg (2000/500 = 4)
 * 
 * ESCALADO FISIOLÓGICO:
 * - Calibración silenciosa por pico R antes de mostrar señal
 * - R_objetivo = 1.0 mV (rango clínico 0.8-1.2 mV)
 * - Rango de visualización: -0.5 a +1.5 mV
 */

#ifndef ECG_MODEL_H
#define ECG_MODEL_H

#include <Arduino.h>
#include "data/signal_types.h"
#include "core/digital_filters.h"

// ============================================================================
// CONSTANTES DEL MODELO MCSHARRY
// ============================================================================
#define MCSHARRY_WAVES          5       // P, Q, R, S, T

// Frecuencias de muestreo (McSharry)
#define ECG_SFINT               2000    // Hz - frecuencia interna de integración
#define ECG_SFECG               500     // Hz - frecuencia de salida ECG
#define ECG_DOWNSAMPLE_RATIO    (ECG_SFINT / ECG_SFECG)  // = 4

// Parámetros de HRV (Task Force ESC/NASPE 1996)
#define ECG_FLO                 0.1f    // Hz - Mayer waves (barorreflejo)
#define ECG_FHI                 0.25f   // Hz - Respiración
#define ECG_FLO_STD             0.01f   // Desviación de flo
#define ECG_FHI_STD             0.01f   // Desviación de fhi

// Escalado fisiológico
#define ECG_R_TARGET_MV         1.0f    // mV - objetivo para pico R
#define ECG_DISPLAY_MIN_MV      -0.5f   // mV - piso de visualización
#define ECG_DISPLAY_MAX_MV      1.5f    // mV - techo de visualización
#define ECG_DISPLAY_RANGE_MV    2.0f    // mV - rango total

// Escalado VFib (Clayton et al. 1993 + Strohmenger 1997)
#define VFIB_RAW_MAX            4.0f    // mV - suma máxima teórica (5×0.8)
#define VFIB_TARGET_AMPLITUDE   0.5f    // mV - amplitud objetivo (coarse VFib)
#define VFIB_SCALE_FACTOR       (VFIB_TARGET_AMPLITUDE / VFIB_RAW_MAX)  // = 0.125
#define VFIB_SAFETY_CLAMP       0.6f    // mV - límite absoluto

// Calibración
#define ECG_CALIBRATION_BEATS   3       // Latidos para calibrar G
#define ECG_MIN_CALIBRATION_SAMPLES 500 // Muestras mínimas antes de calibrar

// ============================================================================
// ESTRUCTURA DE MÉTRICAS PARA DISPLAY
// ============================================================================
struct ECGDisplayMetrics {
    float bpm;              // Frecuencia cardíaca instantánea
    float rrInterval_ms;    // Intervalo RR en ms
    float prInterval_ms;    // Intervalo PR en ms
    float qrsDuration_ms;   // Duración QRS en ms
    float qtInterval_ms;    // Intervalo QT en ms (medido)
    float qtcInterval_ms;   // Intervalo QTc corregido (Bazett)
    float pAmplitude_mV;    // Amplitud onda P en mV
    float qAmplitude_mV;    // Amplitud onda Q en mV
    float rAmplitude_mV;    // Amplitud onda R en mV
    float sAmplitude_mV;    // Amplitud onda S en mV
    float tAmplitude_mV;    // Amplitud onda T en mV
    float stDeviation_mV;   // Desviación ST en mV
    uint32_t beatCount;     // Contador de latidos
    const char* conditionName;  // Nombre de la condición actual
};

// ============================================================================
// ESTADO DEL SISTEMA DINÁMICO (x, y, z)
// ============================================================================
struct ECGDynamicState {
    float x;    // Posición X en círculo unitario
    float y;    // Posición Y en círculo unitario  
    float z;    // Amplitud ECG (salida del modelo)
};

// ============================================================================
// PARÁMETROS DE ONDA PQRST
// ============================================================================
struct ECGWaveParams {
    float ti[MCSHARRY_WAVES];   // Ángulos de extrema (radianes)
    float ai[MCSHARRY_WAVES];   // Amplitudes z de extrema
    float bi[MCSHARRY_WAVES];   // Anchos gaussianos
};

// ============================================================================
// VENTANAS ANGULARES PARA MEDICIÓN DE ONDAS PQRST
// ============================================================================
/**
 * Cada onda tiene una posición angular fisiológica fija en el ciclo cardíaco.
 * Las ventanas definen dónde buscar cada componente, independiente de amplitud.
 * Esto hace el sistema robusto a T hiperaguda, R pequeña, T invertida, etc.
 */
struct AngularWindows {
    // Centros angulares (radianes) - posiciones fisiológicas McSharry
    float P_center = -1.22f;   // -70° → despolarización auricular
    float Q_center = -0.26f;   // -15° → inicio QRS
    float R_center = 0.0f;     // 0° → pico QRS
    float S_center = 0.26f;    // 15° → final QRS
    float T_center = 1.75f;    // 100° → repolarización ventricular
    
    // Anchos de ventana (radianes) - tolerancia de búsqueda
    float P_width = 0.52f;     // ±30°
    float Q_width = 0.17f;     // ±10°
    float R_width = 0.17f;     // ±10°
    float S_width = 0.17f;     // ±10°
    float T_width = 0.87f;     // ±50°
};

// ============================================================================
// BUFFER DE MUESTRAS DEL CICLO ACTUAL
// ============================================================================
/**
 * Almacena cada muestra del ciclo con su ángulo y valor en mV.
 * Al final del ciclo, se analizan las muestras por ventanas angulares.
 */
struct CycleSamples {
    static const int MAX_SAMPLES = 1000;  // ~2s @ 500 Hz
    
    float theta[MAX_SAMPLES];   // Ángulo de cada muestra (radianes)
    float z_mV[MAX_SAMPLES];    // Valor en mV de cada muestra
    int count;                  // Número de muestras almacenadas
    
    void reset() {
        count = 0;
    }
    
    void add(float t, float z) {
        if (count < MAX_SAMPLES) {
            theta[count] = t;
            z_mV[count] = z;
            count++;
        }
    }
};

// ============================================================================
// MODELO ALTERNATIVO PARA FIBRILACIÓN VENTRICULAR
// ============================================================================
/**
 * VFib no puede simularse con McSharry (ondas PQRST organizadas).
 * Usamos superposición de múltiples osciladores con frecuencias
 * en el rango 4-10 Hz (coarse/fine VFib) y parámetros caóticos.
 * 
 * Ref: Clayton RH et al. "Frequency analysis of VF." IEEE Trans Biomed Eng. 1993
 */
#define VFIB_COMPONENTS 5  // Número de osciladores superpuestos

struct VFibState {
    float time;                         // Tiempo acumulado (segundos)
    uint32_t lastUpdateMs;              // Último update de parámetros
    float frequencies[VFIB_COMPONENTS]; // Frecuencias 4-10 Hz
    float amplitudes[VFIB_COMPONENTS];  // Amplitudes variables
    float phases[VFIB_COMPONENTS];      // Fases aleatorias
    float lastValue;                    // Último valor generado (mV)
};

// ============================================================================
// CLASE ECGModel - Implementación ECGSYN (McSharry 2003)
// ============================================================================
class ECGModel {
private:
    // =========================================================================
    // ESTADO DEL SISTEMA DINÁMICO
    // =========================================================================
    ECGDynamicState state;              // Estado actual (x, y, z)
    ECGDynamicState k1, k2, k3, k4, temp;  // Para integración RK4
    
    // =========================================================================
    // PARÁMETROS DEL MODELO
    // =========================================================================
    ECGWaveParams waveParams;           // Parámetros ti, ai, bi actuales
    ECGWaveParams baseParams;           // Parámetros base (sin ajuste hrfact)
    
    float hrMean;                       // BPM medio (default 60)
    float hrStd;                        // Desviación estándar HR (default 1)
    float lfhfRatio;                    // Relación LF/HF (default 0.5)
    float noiseLevel;                   // Amplitud de ruido (default 0)
    
    // =========================================================================
    // VARIABLES DE CONTROL TEMPORAL
    // =========================================================================
    float currentRR;                    // Intervalo RR actual (segundos)
    float lastTheta;                    // Ángulo theta del paso anterior
    uint32_t beatCount;                 // Contador de latidos
    uint32_t sampleCount;               // Contador de muestras totales
    
    // =========================================================================
    // GENERADOR DE PROCESOS RR (HRV)
    // =========================================================================
    float* rrProcess;                   // Serie RR interpolada
    int rrProcessLength;                // Longitud del proceso RR
    int rrProcessIndex;                 // Índice actual en proceso RR
    
    // =========================================================================
    // CALIBRACIÓN Y ESCALADO (por pico R únicamente)
    // =========================================================================
    bool isCalibrated;                  // ¿Ya se completó la calibración?
    float physiologicalGain;            // Factor G = R_objetivo / R_model
    float rModelValue;                  // R_model = promedio de picos R crudos
    float baselineZ;                    // Línea isoeléctrica estimada (z crudo)
    
    // Buffer para picos R detectados durante calibración
    static const int MAX_CALIBRATION_PEAKS = 10;
    float calibrationRPeaks[MAX_CALIBRATION_PEAKS];  // Picos R crudos detectados
    int calibrationPeakCount;           // Número de picos R en buffer
    int calibrationBeatCount;           // Latidos durante calibración
    
    // Tracking de ciclo para calibración
    float calibrationCycleZMax;         // Máximo z en ciclo de calibración
    float calibrationCycleZMin;         // Mínimo z en ciclo de calibración
    
    // =========================================================================
    // MEDICIONES DEL CICLO ACTUAL
    // =========================================================================
    float currentCycleZMax;             // Máximo z en ciclo actual (pico R)
    float currentCycleZMin;             // Mínimo z en ciclo actual
    float currentCycleTime;             // Tiempo acumulado en ciclo actual (segundos)
    int currentCycleSamples;            // Muestras en ciclo actual
    
    // =========================================================================
    // SISTEMA DE VENTANAS ANGULARES
    // =========================================================================
    AngularWindows windows;             // Ventanas angulares para medición PQRST
    CycleSamples cycleSamples;          // Buffer de muestras del ciclo actual
    
    // =========================================================================
    // MÉTRICAS CLÍNICAS MEDIDAS
    // =========================================================================
    float measuredRR_ms;                // Intervalo RR medido (ms)
    float measuredPR_ms;                // Intervalo PR (ms)
    float measuredQRS_ms;               // Duración QRS (ms)
    float measuredQT_ms;                // Intervalo QT (ms)
    float measuredQTc_ms;               // QTc corregido Bazett (ms)
    float measuredP_mV;                 // Amplitud P (mV)
    float measuredQ_mV;                 // Amplitud Q (mV)
    float measuredR_mV;                 // Amplitud R (mV)
    float measuredS_mV;                 // Amplitud S (mV)
    float measuredT_mV;                 // Amplitud T (mV)
    float measuredST_mV;                // Desviación ST (mV)
    float lastMeasuredST_mV;            // Último ST válido (para fallback)
    float currentBaseline_mV;           // Baseline actual para corrección de señal
    float stOffset_mV;                  // Desplazamiento ST vertical (STEMI/Isquemia)
    
    // =========================================================================
    // CONFIGURACIÓN
    // =========================================================================
    ECGCondition currentCondition;      // Condición actual
    ECGParameters params;               // Parámetros del usuario
    
    // =========================================================================
    // GANANCIA WAVEFORM (para visualización en Nextion)
    // =========================================================================
    float waveformGain;                 // Factor de amplificación (0.1-2.0 = 10-200%)
    
    // =========================================================================
    // GENERADOR ALEATORIO (Box-Muller)
    // =========================================================================
    bool gaussHasSpare;
    float gaussSpare;
    
    // =========================================================================
    // MODELO VFIB ALTERNATIVO (espectral caótico)
    // =========================================================================
    VFibState vfibState;                // Estado del modelo VFIB alternativo
    
    // =========================================================================
    // FILTRADO DIGITAL (Pan-Tompkins 1985)
    // =========================================================================
    SignalFilterChain filterChain;      // Cadena de filtros HP + LP + Notch
    bool filteringEnabled;              // Control de filtrado
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Sistema dinámico
    // =========================================================================
    void computeDerivatives(const ECGDynamicState& s, ECGDynamicState& ds, float omega);
    void rungeKutta4Step(float dt, float omega);
    void detectNewBeat();
    
    // =========================================================================
    // MÉTODOS PRIVADOS - HRV
    // =========================================================================
    void generateRRProcess(int numBeats);
    float generateNextRR();
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Calibración
    // =========================================================================
    void performCalibration();
    void updateCalibrationBuffer(float zValue);
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Escalado
    // =========================================================================
    float applyScaling(float zRaw) const;
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Utilidades
    // =========================================================================
    float gaussianRandom(float mean, float std);
    float randomFloat();
    void applyHRFactCorrection();
    void initializeWaveParams();
    void resetMetricsForCondition();
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Análisis por ventanas angulares
    // =========================================================================
    void initializeAngularWindows();
    float normalizeAngle(float theta);
    float findPeakInWindow(float centerAngle, float widthAngle, bool findMax);
    float averageInWindow(float startAngle, float endAngle);
    float findAngleAtPeak(float centerAngle, float widthAngle, bool findMax);
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Morfología por condición (stubs para patologías)
    // =========================================================================
    void setNormalMorphology();
    void setTachycardiaMorphology();
    void setBradycardiaMorphology();
    void setAFibMorphology();
    void setVFibMorphology();
    void setAVBlock1Morphology();
    
    void setSTElevationMorphology();
    void setSTDepressionMorphology();
    
    // =========================================================================
    // MÉTODOS PRIVADOS - Modelo VFIB alternativo (espectral caótico)
    // =========================================================================
    void initVFibModel();
    float generateVFibSample(float deltaTime);
    void updateVFibParameters();
    
public:
    // =========================================================================
    // CONSTRUCTOR / DESTRUCTOR
    // =========================================================================
    ECGModel();
    ~ECGModel();
    
    // =========================================================================
    // CONFIGURACIÓN
    // =========================================================================
    void setParameters(const ECGParameters& newParams);
    void setPendingParameters(const ECGParameters& newParams);  // Para aplicación diferida
    void reset();
    
    // Parámetros de aplicación inmediata (Tipo A)
    void setNoiseLevel(float noise) { noiseLevel = noise; }
    void setAmplitude(float amp);
    void setHeartRate(float hr) { hrMean = constrain(hr, 30.0f, 220.0f); }
    void setWaveformGain(float gain) { waveformGain = constrain(gain, 0.5f, 2.0f); }
    float getWaveformGain() const { return waveformGain; }
    
    // =========================================================================
    // GENERACIÓN DE SEÑAL
    // =========================================================================
    /**
     * @brief Genera una muestra de ECG
     * @param deltaTime Tiempo desde última muestra (segundos)
     * @return Valor ECG en mV (escalado fisiológico)
     */
    float generateSample(float deltaTime);
    
    /**
     * @brief Genera valor DAC 8-bit para salida analógica
     */
    uint8_t getDACValue(float deltaTime);
    
    /**
     * @brief Genera valor para Nextion waveform (rango útil 20-235)
     * @return Valor escalado para visualización en Nextion
     */
    uint8_t getWaveformValue() const;
    
    /**
     * @brief Indica si la calibración está completa y la señal es válida
     */
    bool isOutputReady() const { return isCalibrated; }
    
    /**
     * @brief Obtiene el progreso de calibración
     * @return Número de picos R detectados durante calibración (0-5)
     */
    int getCalibrationProgress() const { return calibrationPeakCount; }
    
    /**
     * @brief Verifica si el modelo está calibrado y listo para mostrar
     */
    bool isReadyForDisplay() const { return isCalibrated; }
    
    // =========================================================================
    // GETTERS - Métricas clínicas
    // =========================================================================
    float getCurrentBPM() const;
    float getCurrentRR_ms() const;
    float getHeartRate_bpm() const { return getCurrentBPM(); }
    float getRRInterval_ms() const { return measuredRR_ms; }
    float getPRInterval_ms() const { return measuredPR_ms; }
    float getQRSDuration_ms() const { return measuredQRS_ms; }
    float getQTInterval_ms() const { return measuredQT_ms; }
    float getQTcInterval_ms() const { return measuredQTc_ms; }  // QTc Bazett
    
    // Amplitudes
    float getPAmplitude_mV() const { return measuredP_mV; }
    float getQAmplitude_mV() const { return measuredQ_mV; }
    float getRAmplitude_mV() const { return measuredR_mV; }
    float getSAmplitude_mV() const { return measuredS_mV; }
    float getTAmplitude_mV() const { return measuredT_mV; }
    float getSTDeviation_mV() const { return measuredST_mV; }
    float getRWaveAmplitude_mV() const { return measuredR_mV; }
    
    // Estado
    uint32_t getBeatCount() const { return beatCount; }
    const char* getConditionName() const;
    ECGCondition getCondition() const { return currentCondition; }
    bool isInBeat() const;
    
    // Compatibilidad
    float getHRMean() const { return hrMean; }
    float getHRStd() const { return hrStd; }
    float getQRSAmplitude() const { return params.qrsAmplitude; }
    float getNoiseLevel() const { return noiseLevel; }
    float getCurrentHeartRate() const { return hrMean; }
    float getCurrentRRInterval() const { return currentRR * 1000.0f; }
    float getCurrentValueMV() const;
    
    void getHRRange(float& minHR, float& maxHR) const;
    void getOutputRange(float* minMV, float* maxMV) const;
    ECGDisplayMetrics getDisplayMetrics() const;
    
    // =========================================================================
    // CONTROL DE FILTRADO DIGITAL
    // =========================================================================
    /**
     * @brief Habilita/deshabilita el filtrado digital
     * @param enable true para filtrar, false para señal cruda
     */
    void setFilteringEnabled(bool enable) { filteringEnabled = enable; }
    bool isFilteringEnabled() const { return filteringEnabled; }
    
    /**
     * @brief Configura frecuencia del filtro notch (50 Hz Europa, 60 Hz USA)
     */
    void setNotchFrequency(float freq);
    
    /**
     * @brief Habilita/deshabilita filtros individuales
     */
    void enableHighpassFilter(bool en);
    void enableLowpassFilter(bool en);
    void enableNotchFilter(bool en);
    
    /**
     * @brief Acceso a la cadena de filtros para configuración avanzada
     */
    SignalFilterChain& getFilterChain() { return filterChain; }
};

#endif // ECG_MODEL_H
