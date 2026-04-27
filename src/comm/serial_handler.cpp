/**
 * @file serial_handler.cpp
 * @brief Serial communication handler implementation
 * @version 2.0.0
 * @date 25 April 2026
 */

#include "comm/serial_handler.h"
#include "config.h"

// ============================================================================
// CONSTRUCTOR
// ============================================================================
SerialHandler::SerialHandler(Stream& serialPort) : serial(serialPort) {
    commandCallback = nullptr;
    streamingEnabled = false;
    lastStreamTime = 0;
    rxIndex = 0;
}

// ============================================================================
// INITIALIZATION
// ============================================================================
void SerialHandler::begin(unsigned long baud) {
    // Serial already initialized in main.cpp
}

// ============================================================================
// PROCESS DATA
// ============================================================================
void SerialHandler::process() {
    while (serial.available()) {
        char c = serial.read();

        if (c == 'h' || c == 'H') {
            printHelp();
        } else if (c == 'i' || c == 'I') {
            printSystemInfo();
        }
    }
}

// ============================================================================
// STREAMING
// ============================================================================
void SerialHandler::startStreaming() {
    streamingEnabled = true;
    serial.println("[Stream] Started");
}

void SerialHandler::stopStreaming() {
    streamingEnabled = false;
    serial.println("[Stream] Stopped");
}

// ============================================================================
// SEND PACKET
// ============================================================================
void SerialHandler::sendPacket(uint8_t cmd, const uint8_t* data, uint16_t len) {
    SerialPacket packet;
    packet.header = CMD_HEADER;
    packet.cmd = cmd;
    packet.signalType = 0;
    packet.dataLen = len;

    if (len > 0 && data != nullptr) {
        memcpy(packet.data, data, min((size_t)len, sizeof(packet.data)));
    }

    packet.checksum = calculateChecksum(packet);
    serial.write((uint8_t*)&packet, 5 + len + 1);
}

uint8_t SerialHandler::calculateChecksum(const SerialPacket& packet) {
    uint8_t checksum = packet.header ^ packet.cmd ^ packet.signalType;
    checksum ^= (packet.dataLen >> 8) ^ (packet.dataLen & 0xFF);
    for (uint16_t i = 0; i < packet.dataLen; i++) {
        checksum ^= packet.data[i];
    }
    return checksum;
}

void SerialHandler::sendAck(uint8_t cmd) {
    uint8_t data[1] = {cmd};
    sendPacket(CMD_ACK, data, 1);
}

void SerialHandler::sendError(uint8_t errorCode) {
    uint8_t data[1] = {errorCode};
    sendPacket(CMD_ERROR, data, 1);
}

// ============================================================================
// DEBUG
// ============================================================================
void SerialHandler::printHelp() {
    serial.println("\n======== " DEVICE_NAME " v" FIRMWARE_VERSION " ========");
    serial.println("COMMANDS:");
    serial.println("h - Show this help");
    serial.println("i - System information");
    serial.println("\nUse the physical buttons for parameter control.");
    serial.println("BTN_MODE (GPIO14): Cycle edit mode");
    serial.println("BTN_UP   (GPIO15): Increment / Next");
    serial.println("BTN_DOWN (GPIO16): Decrement / Prev");
}

void SerialHandler::printSystemInfo() {
    serial.println("\n--- System Information ---");
    serial.printf("Firmware: %s\n", FIRMWARE_VERSION);
    serial.printf("Hardware: %s\n", HARDWARE_MODEL);
    serial.printf("Free Heap: %d bytes\n", ESP.getFreeHeap());
    serial.printf("CPU Freq: %d MHz\n", ESP.getCpuFreqMHz());
    serial.printf("Sample Rate: %d Hz\n", SAMPLE_RATE_HZ);
    serial.printf("DAC: MCP4725 (12-bit, I2C 0x%02X)\n", MCP4725_I2C_ADDR);
    serial.printf("Display: TFT ST7735 (160x128)\n");
    serial.println("--------------------------------\n");
}

// ============================================================================
// CALLBACK
// ============================================================================
void SerialHandler::setCommandCallback(SerialCommandCallback callback) {
    commandCallback = callback;
}
