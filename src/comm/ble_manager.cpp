#include "ble_manager.h"
#include "json_protocol.h"

// Initialize the global singleton instance
BleManager& bleManager = BleManager::getInstance();

BleManager::BleManager() {}

void ApplicationServerCallbacks::onConnect(BLEServer* pServer) {
    bleManager.setDeviceConnected(true);
    Serial.println("[BLE] Device connected.");
}

void ApplicationServerCallbacks::onDisconnect(BLEServer* pServer) {
    bleManager.setDeviceConnected(false);
    Serial.println("[BLE] Device disconnected. Restarting advertising.");
    pServer->startAdvertising(); // Restart advertising to allow reconnection
}

void CommandCallbacks::onWrite(BLECharacteristic *pCharacteristic) {
    String value = pCharacteristic->getValue().c_str();
    
    if (value.length() > 0) {
        Serial.print("[BLE] Received Command: ");
        Serial.println(value);
        JsonProtocol::parseCommand(value);
    }
}

void BleManager::begin() {
    Serial.println("[BLE] Initializing BLE Server...");

    // Create the BLE Device
    BLEDevice::init("PPG Simulator");

    // Create the BLE Server
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new ApplicationServerCallbacks());

    // Create the BLE Service
    BLEService *pService = pServer->createService(BLE_SERVICE_UUID);

    // Create a BLE Characteristic for COMMAND (WRITE)
    pCommandCharacteristic = pService->createCharacteristic(
                      BLE_CHAR_COMMAND_UUID,
                      BLECharacteristic::PROPERTY_WRITE
                    );
    pCommandCharacteristic->setCallbacks(new CommandCallbacks());

    // Create a BLE Characteristic for WAVEFORM (NOTIFY)
    pWaveformCharacteristic = pService->createCharacteristic(
                      BLE_CHAR_WAVEFORM_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
    pWaveformCharacteristic->addDescriptor(new BLE2902());

    // Create a BLE Characteristic for STATUS (NOTIFY)
    pStatusCharacteristic = pService->createCharacteristic(
                      BLE_CHAR_STATUS_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
    pStatusCharacteristic->addDescriptor(new BLE2902());

    // Start the service
    pService->start();

    // Start advertising
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(BLE_SERVICE_UUID);
    pAdvertising->setScanResponse(true);
    // Functions that help with iPhone connections issue
    pAdvertising->setMinPreferred(0x06);  
    pAdvertising->setMinPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.println("[BLE] Server initialized and advertising started!");
}

void BleManager::process() {
    if (!deviceConnected) return;

    // Send STATUS heartbeat every 500ms
    uint32_t currentMillis = millis();
    if (currentMillis - lastStatusMillis >= 500) {
        lastStatusMillis = currentMillis;
        sendStatus();
    }
}

void BleManager::sendWaveformSample(float acValue) {
    if (!deviceConnected) return;

    // We can cast the float directly to a string or send 4 raw bytes.
    // To match standard JSON/text approaches, let's send it as a lightweight string
    // Or send as binary payload for 50Hz speed. Sending as string is fine for 50Hz,
    // but a 4-byte float array is faster if the Android app is configured to parse it.
    // The user requested: "Sends current waveform sample to Android app at 50Hz."
    // Let's send the string representation.
    char buffer[16];
    snprintf(buffer, sizeof(buffer), "%.2f", acValue);
    
    pWaveformCharacteristic->setValue((uint8_t*)buffer, strlen(buffer));
    pWaveformCharacteristic->notify();
}

void BleManager::sendStatus() {
    if (!deviceConnected) return;

    String jsonStatus = JsonProtocol::buildStatusResponse();
    pStatusCharacteristic->setValue(jsonStatus.c_str());
    pStatusCharacteristic->notify();
}
