#pragma once
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <math.h>

// Integrate this helper into your existing ESP32 sensor sketch.
// Values must use Celsius, percent, hPa, metres, and raw ADC counts respectively.
struct AgroReadings {
  float temperature_c = NAN;
  float humidity_pct = NAN;
  float pressure_hpa = NAN;
  float altitude_m = NAN;
  int rain_raw = -1;
  int soil_raw = -1;
};

inline bool agroPostReadings(
  const char* endpoint, const char* sensorToken, const AgroReadings& values,
  const char* rootCa = nullptr
) {
  if (WiFi.status() != WL_CONNECTED || strlen(sensorToken) < 32) return false;
  String payload = "{\"device_id\":\"esp32-field-01\"";
  int fields = 0;
  auto addFloat = [&](const char* key, float value) {
    if (isfinite(value)) {
      payload += ",\""; payload += key; payload += "\":"; payload += String(value, 2);
      fields++;
    }
  };
  addFloat("temperature_c", values.temperature_c);
  addFloat("humidity_pct", values.humidity_pct);
  addFloat("pressure_hpa", values.pressure_hpa);
  addFloat("altitude_m", values.altitude_m);
  if (values.rain_raw >= 0) { payload += ",\"rain_raw\":" + String(values.rain_raw); fields++; }
  if (values.soil_raw >= 0) { payload += ",\"soil_raw\":" + String(values.soil_raw); fields++; }
  if (!fields) return false;
  payload += "}";
  HTTPClient http;
  WiFiClient plain;
  WiFiClientSecure secure;
  bool https = String(endpoint).startsWith("https://");
  if (https) {
    // Never disable certificate verification. Set the trusted root CA for your tunnel.
    if (!rootCa || !strlen(rootCa)) return false;
    secure.setCACert(rootCa);
    if (!http.begin(secure, endpoint)) return false;
  } else {
    // HTTP is intended only for your trusted local Wi-Fi, never the public Internet.
    if (!String(endpoint).startsWith("http://") || !http.begin(plain, endpoint)) return false;
  }
  http.setConnectTimeout(5000);
  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Sensor-Token", sensorToken);
  int status = http.POST(payload);
  http.end();
  return status == 201;
}
