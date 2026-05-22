/**
 * @file cd4051_mux.cpp
 * @brief Implementación del driver para CD4051 DEMULTIPLEXOR con 3 BNC
 * @version 3.0.0
 * @date 13 Enero 2026
 * 
 * ARQUITECTURA FINAL:
 * - 1 CD4051 como DEMUX: DAC → Buffer → DEMUX → 3 filtros → 3 BNC
 * - Cada canal tiene su filtro RC independiente y su propia salida BNC
 * - Solo el canal seleccionado recibe la señal DAC
 */

#include "hw/cd4051_mux.h"

// ============================================================================
// INSTANCIA GLOBAL
// ============================================================================
CD4051Mux mux;

// ============================================================================
// CONSTRUCTOR
// ============================================================================
CD4051Mux::CD4051Mux() : currentChannel(0), initialized(false) {
    // Canal 0 (ECG 6.8kΩ) por defecto
}

// ============================================================================
// INICIALIZACIÓN
// ============================================================================
bool CD4051Mux::begin() {
    // Configurar pines como salidas para control del DEMUX
    pinMode(MUX_S0_PIN, OUTPUT);
    pinMode(MUX_S1_PIN, OUTPUT);
    
    // Si hay pin de enable, configurarlo
    if (MUX_ENABLE_PIN >= 0) {
        pinMode(MUX_ENABLE_PIN, OUTPUT);
        digitalWrite(MUX_ENABLE_PIN, LOW);  // Enable activo bajo
    }
    
    // Seleccionar canal por defecto (ECG)
    selectChannel(MuxChannel::CH0_ECG_6K8);
    
    initialized = true;
    Serial.println("[CD4051] DEMUX inicializado - 3 salidas BNC independientes");
    Serial.printf("[CD4051] Control: S0=GPIO%d, S1=GPIO%d\n", MUX_S0_PIN, MUX_S1_PIN);
    Serial.printf("[CD4051] Canal activo: %s\n", getChannelName());
    Serial.println("[CD4051] Salidas: BNC_ECG | BNC_EMG | BNC_PPG");
    
    return true;
}

// ============================================================================
// SELECCIÓN DE CANAL
// ============================================================================
void CD4051Mux::selectChannel(uint8_t channel) {
    if (channel > 7) {
        channel = 7;  // Limitar a rango válido
    }
    
    // Solo canales 0-2 están conectados físicamente
    if (channel > 2) {
        Serial.printf("[CD4051] ADVERTENCIA: Canal %d no está conectado\n", channel);
    }
    
    currentChannel = channel;
    applyChannelBits(channel);
    
    Serial.printf("[CD4051] Canal seleccionado: %d (%s)\n", channel, getChannelName());
}

void CD4051Mux::selectChannel(MuxChannel channel) {
    selectChannel(static_cast<uint8_t>(channel));
}

// ============================================================================
// CONFIGURACIÓN DE ATENUACIÓN
// ============================================================================
void CD4051Mux::setAttenuation(AttenuationLevel level) {
    switch (level) {
        case AttenuationLevel::ATTEN_NONE:
            selectChannel(MuxChannel::CH1_EMG_1K0);  // EMG: menor R, mayor Fc
            break;
        case AttenuationLevel::ATTEN_MEDIUM:
            selectChannel(MuxChannel::CH0_ECG_6K8);  // ECG: R media
            break;
        case AttenuationLevel::ATTEN_HIGH:
            selectChannel(MuxChannel::CH2_PPG_25K);  // PPG: mayor R, menor Fc
            break;
    }
}

AttenuationLevel CD4051Mux::getCurrentAttenuation() const {
    switch (currentChannel) {
        case 0: return AttenuationLevel::ATTEN_MEDIUM;
        case 1: return AttenuationLevel::ATTEN_NONE;
        case 2: return AttenuationLevel::ATTEN_HIGH;
        default: return AttenuationLevel::ATTEN_NONE;
    }
}

// ============================================================================
// INFORMACIÓN DEL CANAL
// ============================================================================
const char* CD4051Mux::getChannelName() const {
    switch (currentChannel) {
        case 0: return "ECG → BNC_ECG (6.8k, Fc=23Hz)";
        case 1: return "EMG → BNC_EMG (1.0k, Fc=159Hz)";
        case 2: return "PPG → BNC_PPG (25k, Fc=6.37Hz)";
        case 3: return "CH3 (No conectado)";
        case 4: return "CH4 (No accesible)";
        case 5: return "CH5 (No accesible)";
        case 6: return "CH6 (No accesible)";
        case 7: return "CH7 (No accesible)";
        default: return "Desconocido";
    }
}

float CD4051Mux::getCutoffFrequency() const {
    // Frecuencia de corte del filtro RC: Fc = 1/(2π×R×C)
    // Cada filtro tiene su propio C=1µF (independientes)
    switch (currentChannel) {
        case 0: return 23.4f;   // ECG: 6.8kΩ + 1µF → Fc = 23.4 Hz
        case 1: return 159.0f;  // EMG: 1.0kΩ + 1µF → Fc = 159 Hz
        case 2: return 6.37f;   // PPG: 25kΩ + 1µF  → Fc = 6.37 Hz
        default: return 0.0f;   // Canales no conectados
    }
}

// ============================================================================
// APLICAR BITS DE SELECCIÓN (controla el DEMUX CD4051)
// ============================================================================
void CD4051Mux::applyChannelBits(uint8_t channel) {
    // CD4051 usa 3 bits de selección (A, B, C)
    // S2 (C) está conectado a GND permanentemente
    // Solo usamos S0 y S1 para canales 0, 1, 2
    // 
    // Canal | S2(C) | S1(B) | S0(A) | Señal DAC va a  | Salida BNC
    // ------+-------+-------+-------+-----------------+-----------
    //   0   |   0   |   0   |   0   | Filtro 6.8kΩ    | BNC_ECG
    //   1   |   0   |   0   |   1   | Filtro 1.0kΩ    | BNC_EMG
    //   2   |   0   |   1   |   0   | Filtro 25kΩ     | BNC_PPG
    //   3   |   0   |   1   |   1   | (no usado)      | ---
    
    uint8_t s0 = (channel >> 0) & 0x01;  // Bit 0 → S0 (GPIO32)
    uint8_t s1 = (channel >> 1) & 0x01;  // Bit 1 → S1 (GPIO33)
    // S2 = GND permanente
    
    digitalWrite(MUX_S0_PIN, s0);
    digitalWrite(MUX_S1_PIN, s1);
}
