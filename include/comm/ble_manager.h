#ifndef BLE_MANAGER_H
#define BLE_MANAGER_H

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Service and Characteristics UIIDs
#define BLE_SERVICE_UUID           "12345678-1234-5678-1234-56789abcdef0"
#define BLE_CHAR_COMMAND_UUID      "12345678-1234-5678-1234-56789abcdef1"
#define BLE_CHAR_WAVEFORM_UUID     "12345678-1234-5678-1234-56789abcdef2"
#define BLE_CHAR_STATUS_UUID       "12345678-1234-5678-1234-56789abcdef3"

class BleManager {
public:
    static BleManager& getInstance() {
        static BleManager instance;
        return instance;
    }

    void begin();
    void process();
    void sendWaveformSample(float acValue);
    void sendStatus();

    bool isDeviceConnected() const { return deviceConnected; }

    // Callbacks need access to state
    void setDeviceConnected(bool connected) { deviceConnected = connected; }

private:
    BleManager(); // Singleton pattern
    
    BLEServer* pServer = nullptr;
    BLECharacteristic* pCommandCharacteristic = nullptr;
    BLECharacteristic* pWaveformCharacteristic = nullptr;
    BLECharacteristic* pStatusCharacteristic = nullptr;

    bool deviceConnected = false;
    uint32_t lastStatusMillis = 0;
};

// Expose a convenient global reference
extern BleManager& bleManager;

// Custom callback class for connection events
class ApplicationServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) override;
    void onDisconnect(BLEServer* pServer) override;
};

// Custom callback class for Characteristic Writes
class CommandCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) override;
};

#endif // BLE_MANAGER_H
