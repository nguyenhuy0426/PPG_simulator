#include "json_protocol.h"
#include "../core/signal_engine.h"
#include "../core/state_machine.h"
#include "../hw/tft_display.h"

extern StateMachine stateMachine;

void JsonProtocol::parseCommand(const String& jsonString) {
    SignalEngine* engine = SignalEngine::getInstance();
    if (!engine) return;

    // ================================
    // Parse JSON BLE packet
    // ================================
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, jsonString);

    if (error) {
        Serial.print("[JSON ERROR] ");
        Serial.println(error.c_str());
        return;
    }

    Serial.print("[BLE JSON RX] ");
    Serial.println(jsonString);

    // ================================
    // Ensure simulator is running
    // ================================
    if (stateMachine.getState() != SystemState::SIMULATING) {
        stateMachine.processEvent(SystemEvent::START_SIMULATION);
    }

    // ================================
    // CONDITION update
    // ================================
    if (doc.containsKey("condition")) {
        uint8_t cond = doc["condition"].as<uint8_t>();

        stateMachine.setSelectedCondition(cond);
        stateMachine.setEditMode(UIEditMode::CONDITION_SELECT);

        engine->changeCondition(cond);
        tftDisplay.clearWaveform();

        Serial.printf("[BLE] Condition -> %d\n", cond);
    }

    // ================================
    // HEART RATE update
    // ================================
    if (doc.containsKey("hr")) {
        float hr = doc["hr"].as<float>();

        stateMachine.setEditMode(UIEditMode::EDIT_HR);
        engine->updateHeartRate(hr);

        Serial.printf("[BLE] HR -> %.0f\n", hr);
    }

    // ================================
    // PERFUSION INDEX update
    // ================================
    if (doc.containsKey("pi")) {
        float pi = doc["pi"].as<float>();

        stateMachine.setEditMode(UIEditMode::EDIT_PI);
        engine->updatePerfusionIndex(pi);

        Serial.printf("[BLE] PI -> %.2f\n", pi);
    }

    // ================================
    // NOISE update
    // ================================
    if (doc.containsKey("noise")) {
        float noise = doc["noise"].as<float>();

        stateMachine.setEditMode(UIEditMode::EDIT_NOISE);
        engine->updateNoiseLevel(noise);

        Serial.printf("[BLE] Noise -> %.2f\n", noise);
    }

    // ================================
    // Future parameters
    // ================================
    if (doc.containsKey("spo2")) {
        float spo2 = doc["spo2"].as<float>();
        Serial.printf("[BLE] SpO2 -> %.0f\n", spo2);
        // engine->updateSpO2(spo2);   // nếu có sau này
    }

    if (doc.containsKey("rr")) {
        float rr = doc["rr"].as<float>();
        Serial.printf("[BLE] RR -> %.0f\n", rr);
        // engine->updateRR(rr);       // nếu có sau này
    }

    Serial.println("[JSON] BLE parameters applied.");
}

String JsonProtocol::buildStatusResponse() {
    SignalEngine* engine = SignalEngine::getInstance();
    if (!engine) return "{}";

    PPGParameters p = engine->getPPGParams();

    StaticJsonDocument<256> doc;
    doc["hr"] = p.heartRate;
    doc["pi"] = p.perfusionIndex;
    doc["noise"] = p.noiseLevel;
    doc["condition"] = (uint8_t)p.condition;
    
    // Fallback constants if not supported yet in engine Params
    doc["spo2"] = 98; 
    doc["rr"] = 16;   

    String output;
    serializeJson(doc, output);
    return output;
}