/**
 * @file serial_handler.h
 * @brief Manejador de comunicación serial con PC
 * @version 1.0.0
 * 
 * Comandos serial y streaming de datos.
 */

#ifndef SERIAL_HANDLER_H
#define SERIAL_HANDLER_H

#include <Arduino.h>
#include "../data/signal_types.h"

// ============================================================================
// COMANDOS DEL PROTOCOLO
// ============================================================================
#define CMD_HEADER          0xAA

// Comandos de control
#define CMD_START_SIGNAL    0x01
#define CMD_STOP_SIGNAL     0x02
#define CMD_PAUSE_SIGNAL    0x03
#define CMD_RESUME_SIGNAL   0x04

// Comandos de parámetros
#define CMD_SET_PARAMS      0x10
#define CMD_GET_PARAMS      0x11
#define CMD_GET_DEFAULTS    0x12

// Comandos de streaming
#define CMD_START_STREAM    0x20
#define CMD_STOP_STREAM     0x21
#define CMD_GET_METRICS     0x22

// Respuestas
#define CMD_ACK             0xF0
#define CMD_ERROR           0xFF

// ============================================================================
// ESTRUCTURA DE PAQUETE
// ============================================================================
struct SerialPacket {
    uint8_t header;
    uint8_t cmd;
    uint8_t signalType;
    uint16_t dataLen;
    uint8_t data[256];
    uint8_t checksum;
};

// ============================================================================
// CALLBACK PARA COMANDOS
// ============================================================================
typedef void (*SerialCommandCallback)(uint8_t cmd, uint8_t* data, uint16_t len);

// ============================================================================
// CLASE SerialHandler
// ============================================================================
class SerialHandler {
private:
    HardwareSerial& serial;
    SerialCommandCallback commandCallback;
    
    // Estado de streaming
    bool streamingEnabled;
    unsigned long lastStreamTime;
    
    // Buffer de recepción
    uint8_t rxBuffer[280];
    uint16_t rxIndex;
    
    // Métodos privados
    void parsePacket();
    uint8_t calculateChecksum(const SerialPacket& packet);
    void sendAck(uint8_t cmd);
    void sendError(uint8_t errorCode);
    
public:
    SerialHandler(HardwareSerial& serialPort);
    
    // Inicialización
    void begin(unsigned long baud = 115200);
    
    // Procesar datos entrantes (llamar en loop)
    void process();
    
    // Streaming de datos
    void startStreaming();
    void stopStreaming();
    bool isStreaming() const { return streamingEnabled; }
    void streamSample(uint8_t dacValue, uint16_t flags);
    
    // Enviar paquete
    void sendPacket(uint8_t cmd, const uint8_t* data, uint16_t len);
    
    // Enviar métricas
    void sendMetrics(SignalType type, const void* metrics);
    
    // Debug
    void printHelp();
    void printSystemInfo();
    
    // Callback
    void setCommandCallback(SerialCommandCallback callback);
};

#endif // SERIAL_HANDLER_H
