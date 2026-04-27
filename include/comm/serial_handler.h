/**
 * @file serial_handler.h
 * @brief Serial communication handler for PPG Signal Simulator
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Provides serial debug commands and data streaming for Serial Plotter.
 */

#ifndef SERIAL_HANDLER_H
#define SERIAL_HANDLER_H

#include <Arduino.h>

// Protocol constants
#define CMD_HEADER      0xAA
#define CMD_ACK         0x01
#define CMD_ERROR       0x02
#define CMD_DATA        0x10

// Serial packet structure
struct SerialPacket {
    uint8_t header;
    uint8_t cmd;
    uint8_t signalType;
    uint16_t dataLen;
    uint8_t data[64];
    uint8_t checksum;
};

// Callback type
typedef void (*SerialCommandCallback)(uint8_t cmd, const uint8_t* data, uint16_t len);

class SerialHandler {
private:
    Stream& serial;
    SerialCommandCallback commandCallback;
    bool streamingEnabled;
    uint32_t lastStreamTime;
    uint8_t rxBuffer[128];
    uint16_t rxIndex;

    uint8_t calculateChecksum(const SerialPacket& packet);

public:
    SerialHandler(Stream& serialPort);

    void begin(unsigned long baud = 115200);
    void process();

    // Streaming
    void startStreaming();
    void stopStreaming();
    bool isStreaming() const { return streamingEnabled; }

    // Data sending
    void sendPacket(uint8_t cmd, const uint8_t* data, uint16_t len);
    void sendAck(uint8_t cmd);
    void sendError(uint8_t errorCode);

    // Debug
    void printHelp();
    void printSystemInfo();

    // Callback
    void setCommandCallback(SerialCommandCallback callback);
};

#endif // SERIAL_HANDLER_H
