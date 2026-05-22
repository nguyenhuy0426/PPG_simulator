/**
 * @file cd4051_mux.h
 * @brief Driver para CD4051 como DEMULTIPLEXOR con 3 salidas BNC independientes
 * @version 3.0.0
 * @date 13 Enero 2026
 * 
 * ═══════════════════════════════════════════════════════════════════════════
 * ARQUITECTURA FINAL: DAC → LM358 → CD4051 (DEMUX) → 3 FILTROS → 3 BNC
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 * Esta arquitectura usa 1 solo CD4051 como DEMULTIPLEXOR:
 * - La señal DAC entra al CD4051 por COM (pin 3)
 * - El DEMUX activa 1 de 3 caminos (CH0, CH1, CH2)
 * - Cada camino tiene su filtro RC independiente
 * - Cada filtro tiene su propia salida BNC
 * 
 * VENTAJAS:
 * - Solo 1 CD4051 necesario
 * - 3 salidas BNC independientes (ECG, EMG, PPG simultáneamente disponibles)
 * - Cada filtro completamente aislado
 * - Sin interferencia entre canales
 * - Solo el canal seleccionado recibe la señal DAC
 * 
 * ═══════════════════════════════════════════════════════════════════════════
 * DIAGRAMA DE CONEXIONES:
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 *     ESP32          LM358              CD4051
 *    ┌──────┐      ┌────────┐          (DEMUX)
 *    │      │      │        │        ┌─────────┐
 *    │GPIO25├──────┤+ Buffer├────────┤COM(pin3)│
 *    │(DAC) │      │  OUT   │        │         │
 *    │      │      └────────┘        │         │    ┌─[6.8kΩ]─┬─[1µF]─GND ──► BNC_ECG
 *    │      │                        │CH0(13)  ├────┘         │
 *    │GPIO32├────────────────────────┤S0(11)   │              │
 *    │(S0)  │                        │         │    ┌─[1.0kΩ]─┬─[1µF]─GND ──► BNC_EMG
 *    │      │                        │CH1(14)  ├────┘         │
 *    │GPIO33├────────────────────────┤S1(10)   │              │
 *    │(S1)  │                        │         │    ┌─[25kΩ]──┬─[1µF]─GND ──► BNC_PPG
 *    │      │                        │CH2(15)  ├────┘         │
 *    │      │                        │         │              │
 *    │ GND  ├────────────────────────┤S2(9)=GND│              │
 *    └──────┘                        │VCC=5V   │              │
 *                                    │GND,VEE,INH=GND         │
 *                                    └─────────┘              │
 *                                                            GND
 * 
 * ═══════════════════════════════════════════════════════════════════════════
 * FILTROS RC INDEPENDIENTES (cada uno con su propio capacitor C=1µF):
 * ═══════════════════════════════════════════════════════════════════════════
 * 
 *   DEMUX CH0 ──[R=6.8kΩ]──┬──[C=1µF]── GND  ──► BNC_ECG (Fc=23.4Hz)
 *   DEMUX CH1 ──[R=1.0kΩ]──┬──[C=1µF]── GND  ──► BNC_EMG (Fc=159Hz)
 *   DEMUX CH2 ──[R=25kΩ]───┬──[C=1µF]── GND  ──► BNC_PPG (Fc=6.37Hz)
 * 
 * NOTA: Solo se usa GPIO32 (S0) y GPIO33 (S1) para seleccionar canal activo.
 *       S2 conectado a GND permanentemente (solo usamos canales 0-2).
 */

#ifndef CD4051_MUX_H
#define CD4051_MUX_H

#include <Arduino.h>
#include "../config.h"

// ============================================================================
// CONFIGURACIÓN DE PINES (desde config.h)
// ============================================================================
// MUX_SELECT_S0 = GPIO32 - Selector A (LSB) → CD4051 pin 11
// MUX_SELECT_S1 = GPIO33 - Selector B       → CD4051 pin 10
// S2 conectado a GND (siempre 0, solo usamos CH0-CH2)

#define MUX_S0_PIN          MUX_SELECT_S0
#define MUX_S1_PIN          MUX_SELECT_S1
#define MUX_ENABLE_PIN      -1      // No usado (INH conectado a GND)

// ============================================================================
// CANALES DEL DEMULTIPLEXOR CD4051
// ============================================================================
// Un solo CD4051 distribuye la señal DAC a 3 caminos independientes:
// - CH0 → Filtro ECG (6.8kΩ) → BNC_ECG
// - CH1 → Filtro EMG (1.0kΩ) → BNC_EMG  
// - CH2 → Filtro PPG (25kΩ)  → BNC_PPG
enum class MuxChannel : uint8_t {
    CH0_ECG_6K8     = 0,    // Canal 0: R=6.8kΩ, C=1µF, Fc=23.4Hz → BNC_ECG
    CH1_EMG_1K0     = 1,    // Canal 1: R=1.0kΩ, C=1µF, Fc=159Hz  → BNC_EMG
    CH2_PPG_25K     = 2,    // Canal 2: R=25kΩ,  C=1µF, Fc=6.37Hz → BNC_PPG
    CH3_UNUSED      = 3,    // Canal 3: No conectado
    CH4_UNUSED      = 4,    // Canal 4: No accesible (S2=GND)
    CH5_UNUSED      = 5,    // Canal 5: No accesible
    CH6_UNUSED      = 6,    // Canal 6: No accesible
    CH7_UNUSED      = 7     // Canal 7: No accesible
};

// Alias para tipo de señal (más semántico)
#define MUX_CHANNEL_ECG     MuxChannel::CH0_ECG_6K8   // 6.8kΩ → Fc=23.4Hz
#define MUX_CHANNEL_EMG     MuxChannel::CH1_EMG_1K0   // 1.0kΩ → Fc=159Hz
#define MUX_CHANNEL_PPG     MuxChannel::CH2_PPG_25K   // 25kΩ  → Fc=6.37Hz

// ============================================================================
// NIVELES DE ATENUACIÓN PREDEFINIDOS
// ============================================================================
enum class AttenuationLevel : uint8_t {
    ATTEN_NONE    = 0,    // Sin atenuación (CH1 directo) - Máxima amplitud
    ATTEN_MEDIUM  = 1,    // Atenuación media (CH0: 6.8kΩ)
    ATTEN_HIGH    = 2     // Atenuación alta (CH2: 25kΩ) - Mínima amplitud
};

// ============================================================================
// CLASE CD4051 MULTIPLEXER
// ============================================================================
class CD4051Mux {
public:
    /**
     * @brief Constructor
     */
    CD4051Mux();
    
    /**
     * @brief Inicializa los pines GPIO para control del multiplexor
     * @return true si la inicialización fue exitosa
     */
    bool begin();
    
    /**
     * @brief Selecciona un canal del multiplexor (0-7)
     * @param channel Canal a seleccionar (0-7, pero solo 0-2 están conectados)
     */
    void selectChannel(uint8_t channel);
    
    /**
     * @brief Selecciona un canal usando el enum MuxChannel
     * @param channel Canal a seleccionar
     */
    void selectChannel(MuxChannel channel);
    
    /**
     * @brief Configura el nivel de atenuación
     * @param level Nivel de atenuación deseado
     */
    void setAttenuation(AttenuationLevel level);
    
    /**
     * @brief Obtiene el canal actualmente seleccionado
     * @return Canal actual (0-7)
     */
    uint8_t getCurrentChannel() const { return currentChannel; }
    
    /**
     * @brief Obtiene el nivel de atenuación actual
     * @return Nivel de atenuación
     */
    AttenuationLevel getCurrentAttenuation() const;
    
    /**
     * @brief Obtiene el nombre del canal actual
     * @return String con descripción del canal
     */
    const char* getChannelName() const;
    
    /**
     * @brief Obtiene la frecuencia de corte del filtro RC activo
     * @return Frecuencia de corte en Hz (Fc = 1/(2πRC))
     * @note C = 1µF compartido, R depende del canal seleccionado
     */
    float getCutoffFrequency() const;

private:
    uint8_t currentChannel;
    bool initialized;
    
    /**
     * @brief Aplica los bits de selección a los pines GPIO
     * @param channel Canal (0-7)
     */
    void applyChannelBits(uint8_t channel);
};

// ============================================================================
// INSTANCIA GLOBAL (SINGLETON)
// ============================================================================
extern CD4051Mux mux;

#endif // CD4051_MUX_H
