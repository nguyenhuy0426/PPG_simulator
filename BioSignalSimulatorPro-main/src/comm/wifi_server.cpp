/**
 * @file wifi_server.cpp
 * @brief Implementación del WiFi AP y WebSocket Server
 * @version 1.0.0
 * @date 18 Diciembre 2025
 */

#include "comm/wifi_server.h"

// Instancia global
WiFiServer_BioSim wifiServer;

// ============================================================================
// CONSTRUCTOR
// ============================================================================

WiFiServer_BioSim::WiFiServer_BioSim() 
    : _server(nullptr)
    , _ws(nullptr)
    , _isActive(false)
    , _streamingEnabled(false)
    , _lastSendTime(0)
    , _lastMetricsTime(0)
    , _lastCleanupTime(0)
{
}

// ============================================================================
// INICIALIZACIÓN
// ============================================================================

bool WiFiServer_BioSim::begin() {
    Serial.println("[WiFi] Iniciando Access Point...");
    
    // Desconectar cualquier conexión previa y resetear WiFi
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    delay(100);
    
    // Inicializar SPIFFS para archivos web
    if (!SPIFFS.begin(true)) {
        Serial.println("[WiFi] ERROR: No se pudo montar SPIFFS");
        return false;
    }
    Serial.println("[WiFi] SPIFFS montado correctamente");
    
    // Configurar WiFi como Access Point
    WiFi.mode(WIFI_AP);
    delay(100);
    
    WiFi.softAPConfig(WIFI_LOCAL_IP, WIFI_GATEWAY, WIFI_SUBNET);
    
    // Recomendaciones de estabilidad
    WiFi.setSleep(false); // Desactivar sleep WiFi
    WiFi.setTxPower(WIFI_POWER_19_5dBm); // Máxima potencia

    // Usar canal definido en config (canal 6, menos saturado en 2.4GHz)
    int attempts = 0;
    while (!WiFi.softAP(WIFI_SSID, WIFI_PASSWORD, WIFI_CHANNEL, false, WIFI_MAX_CLIENTS)) {
        attempts++;
        Serial.printf("[WiFi] Intento %d de crear AP fallido\n", attempts);
        if (attempts >= 3) {
            Serial.println("[WiFi] ERROR: No se pudo crear AP después de 3 intentos");
            return false;
        }
        delay(500);
    }
    
    Serial.printf("[WiFi] AP creado: %s (canal %d)\n", WIFI_SSID, WIFI_CHANNEL);
    Serial.printf("[WiFi] IP: %s\n", WiFi.softAPIP().toString().c_str());
    
    // Crear servidor HTTP
    _server = new AsyncWebServer(HTTP_PORT);
    
    // Crear WebSocket
    _ws = new AsyncWebSocket("/ws");
    
    // Configurar evento WebSocket
    _ws->onEvent([this](AsyncWebSocket* server, AsyncWebSocketClient* client, 
                        AwsEventType type, void* arg, uint8_t* data, size_t len) {
        this->onWsEvent(server, client, type, arg, data, len);
    });
    
    // Configurar límites del WebSocket para evitar desconexiones
    // Solo limpiar clientes que estén realmente muertos (queue > 16 mensajes)
    _ws->enable(true);
    
    // Agregar WebSocket al servidor
    _server->addHandler(_ws);
    
    // Configurar rutas HTTP
    setupRoutes();
    
    // Iniciar servidor
    _server->begin();
    Serial.printf("[WiFi] Servidor HTTP iniciado en puerto %d\n", HTTP_PORT);
    Serial.println("[WiFi] WebSocket disponible en /ws");
    
    _isActive = true;
    return true;
}

// ============================================================================
// CONFIGURACIÓN DE RUTAS HTTP
// ============================================================================

void WiFiServer_BioSim::setupRoutes() {
    // Página principal
    _server->on("/", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(SPIFFS, "/index.html", "text/html");
    });
    
    // =========================================================================
    // CAPTIVE PORTAL DETECTION - Evita que Windows/Android desconecten
    // Responde "success" a las peticiones de detección de conectividad
    // =========================================================================
    
    // Windows 10/11 connectivity check
    _server->on("/connecttest.txt", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(200, "text/plain", "Microsoft Connect Test");
    });
    _server->on("/ncsi.txt", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(200, "text/plain", "Microsoft NCSI");
    });
    _server->on("/redirect", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->redirect("/");
    });
    
    // Android connectivity check
    _server->on("/generate_204", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(204);
    });
    _server->on("/gen_204", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(204);
    });
    
    // Apple iOS/macOS connectivity check
    _server->on("/hotspot-detect.html", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(200, "text/html", "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>");
    });
    _server->on("/library/test/success.html", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(200, "text/html", "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>");
    });
    
    // Firefox connectivity check
    _server->on("/success.txt", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(200, "text/plain", "success\n");
    });
    
    // =========================================================================
    
    // Archivos estáticos
    _server->on("/app.js", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(SPIFFS, "/app.js", "application/javascript");
    });
    
    _server->on("/styles.css", HTTP_GET, [](AsyncWebServerRequest* request) {
        request->send(SPIFFS, "/styles.css", "text/css");
    });
    
    // API de estado
    _server->on("/api/status", HTTP_GET, [this](AsyncWebServerRequest* request) {
        StaticJsonDocument<256> doc;
        doc["device"] = "BioSignalSimulator Pro";
        doc["version"] = "1.0.0";
        doc["clients"] = _ws->count();
        doc["streaming"] = _streamingEnabled;
        
        String response;
        serializeJson(doc, response);
        request->send(200, "application/json", response);
    });
    
    // 404
    _server->onNotFound([](AsyncWebServerRequest* request) {
        request->send(404, "text/plain", "Not Found");
    });
}

// ============================================================================
// EVENTOS WEBSOCKET
// ============================================================================

void WiFiServer_BioSim::onWsEvent(AsyncWebSocket* server, AsyncWebSocketClient* client,
                                   AwsEventType type, void* arg, uint8_t* data, size_t len) {
    switch (type) {
        case WS_EVT_CONNECT:
            Serial.printf("[WS] Cliente #%u conectado desde %s\n", 
                         client->id(), client->remoteIP().toString().c_str());
            client->setCloseClientOnQueueFull(false); // preferimos descartar frames que cerrar conexión
            client->keepAlivePeriod(15); // ping/pong cada 15s para mantener viva la sesión
            // Enviar mensaje de bienvenida
            {
                StaticJsonDocument<128> doc;
                doc["type"] = "welcome";
                doc["message"] = "Conectado a BioSignalSimulator Pro";
                doc["clientId"] = client->id();
                String msg;
                serializeJson(doc, msg);
                client->text(msg);
            }
            break;
            
        case WS_EVT_DISCONNECT:
            Serial.printf("[WS] Cliente #%u desconectado\n", client->id());
            break;
            
        case WS_EVT_ERROR:
            Serial.printf("[WS] Error en cliente #%u\n", client->id());
            break;
            
        case WS_EVT_DATA:
            // Manejar ping del cliente para mantener conexión activa
            {
                AwsFrameInfo* info = (AwsFrameInfo*)arg;
                if (info->opcode == WS_TEXT && len >= 4) {
                    if (strncmp((char*)data, "ping", 4) == 0) {
                        client->text("{\"type\":\"pong\"}");
                    }
                }
            }
            break;
            
        default:
            break;
    }
}

// ============================================================================
// ENVÍO DE DATOS
// ============================================================================

void WiFiServer_BioSim::sendSignalData(const WSSignalData& data) {
    if (!_isActive || !_streamingEnabled || !_ws) return;
    
    // Verificar si hay clientes antes de enviar
    uint8_t clientCount = _ws->count();
    if (clientCount == 0) return;
    
    uint32_t now = millis();
    
    // Cleanup muy conservador: solo cada 10 segundos
    if (now - _lastCleanupTime >= WS_CLEANUP_INTERVAL_MS) {
        _lastCleanupTime = now;
        _ws->cleanupClients();
    }
    
    String json = buildDataJson(data);
    _ws->textAll(json);
}

void WiFiServer_BioSim::sendMetrics(const WSSignalMetrics& metrics) {
    if (!_isActive || !_ws || _ws->count() == 0) return;
    
    uint32_t now = millis();
    if (now - _lastMetricsTime < WS_METRICS_INTERVAL_MS) return;
    _lastMetricsTime = now;
    
    String json = buildMetricsJson(metrics);
    _ws->textAll(json);
}

void WiFiServer_BioSim::sendStateChange(const char* signalType, const char* condition, const char* state) {
    if (!_isActive || _ws->count() == 0) return;
    
    String json = buildStateJson(signalType, condition, state);
    
    if (!_ws->availableForWriteAll()) {
        return;
    }
    
    auto status = _ws->textAll(json);
    if (status == AsyncWebSocket::SendStatus::DISCARDED) {
        Serial.println("[WS] estado descartado por cola llena");
    }
}

// ============================================================================
// CONSTRUCCIÓN DE JSON
// ============================================================================

String WiFiServer_BioSim::buildDataJson(const WSSignalData& data) {
    // JSON con valores float directos para mayor precisión
    StaticJsonDocument<192> doc;
    doc["type"] = "data";
    doc["signal"] = data.signalType;
    doc["condition"] = data.condition;
    doc["state"] = data.state;
    doc["t"] = data.timestamp;
    doc["value"] = data.value;
    doc["dac"] = data.dacValue;
    if (data.envelope != 0) {
        doc["env"] = data.envelope;
    }
    
    String json;
    serializeJson(doc, json);
    return json;
}

String WiFiServer_BioSim::buildMetricsJson(const WSSignalMetrics& metrics) {
    StaticJsonDocument<512> doc;
    doc["type"] = "metrics";
    
    JsonObject m = doc.createNestedObject("m");
    // ECG
    m["hr"] = metrics.hr;
    m["rr"] = metrics.rr;
    m["qrs"] = metrics.qrs;
    m["st"] = metrics.st;
    m["hrv"] = metrics.hrv;
    m["pr"] = metrics.pr;
    m["qtc"] = metrics.qtc;
    m["p"] = metrics.p;
    m["r"] = metrics.r;
    m["t"] = metrics.t;
    // EMG
    m["rms"] = metrics.rms;
    m["exc"] = metrics.excitation;
    m["mus"] = metrics.activeUnits;
    m["freq"] = metrics.freq;
    m["mvc"] = metrics.mvc;
    m["raw"] = metrics.raw;
    // PPG
    m["pi"] = metrics.pi;
    m["dc"] = metrics.dcLevel;
    m["ac"] = metrics.ac;
    m["sys"] = metrics.sys;
    m["dia"] = metrics.dia;
    
    String json;
    serializeJson(doc, json);
    return json;
}

String WiFiServer_BioSim::buildStateJson(const char* signalType, const char* condition, const char* state) {
    StaticJsonDocument<192> doc;
    doc["type"] = "state";
    doc["signal"] = signalType;
    doc["condition"] = condition;
    doc["state"] = state;
    
    String json;
    serializeJson(doc, json);
    return json;
}

// ============================================================================
// UTILIDADES
// ============================================================================

uint8_t WiFiServer_BioSim::getClientCount() {
    return _ws ? _ws->count() : 0;
}

void WiFiServer_BioSim::loop() {
    // NO hacer cleanup aquí - ya se hace en sendSignalData() cada 3 segundos
    // Cleanup duplicado causa desconexiones erráticas
    
    // Verificar que el WiFi AP sigue activo cada 10 segundos
    static uint32_t lastCheck = 0;
    if (millis() - lastCheck > 10000) {
        lastCheck = millis();
        
        // Si el WiFi no está en modo AP, reiniciar
        if (WiFi.getMode() != WIFI_AP && WiFi.getMode() != WIFI_AP_STA) {
            Serial.println("[WiFi] AP no activo, reiniciando...");
            WiFi.mode(WIFI_AP);
            delay(100);
            WiFi.softAPConfig(WIFI_LOCAL_IP, WIFI_GATEWAY, WIFI_SUBNET);
            WiFi.softAP(WIFI_SSID, WIFI_PASSWORD, WIFI_CHANNEL, false, WIFI_MAX_CLIENTS);
            Serial.printf("[WiFi] AP reiniciado: %s\n", WIFI_SSID);
        }
    }
}

void WiFiServer_BioSim::stop() {
    if (_ws) {
        _ws->closeAll();
    }
    WiFi.softAPdisconnect(true);
    _isActive = false;
    Serial.println("[WiFi] Servidor detenido");
}
