#ifndef JSON_PROTOCOL_H
#define JSON_PROTOCOL_H

#include <Arduino.h>
#include <ArduinoJson.h>

class JsonProtocol {
public:
    /**
     * @brief Parses a JSON command string and updates system parameters
     * @param jsonString The incoming JSON string from BLE
     */
    static void parseCommand(const String& jsonString);

    /**
     * @brief Builds a JSON status string containing current simulator parameters
     * @return Serialized JSON string
     */
    static String buildStatusResponse();
};

#endif // JSON_PROTOCOL_H
