// Open this sketch folder in Arduino IDE. agroai_sender.h is included beside it.
#include "agroai_sender.h"
#include <time.h>

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* API_URL = "http://192.168.1.100:8000/api/sensors";
const char* SENSOR_TOKEN = "COPY_AGRO_SENSOR_TOKEN_FROM_LAPTOP_ENV";
// For HTTPS: paste your tunnel certificate's trusted root CA here.
const char* ROOT_CA = "";
unsigned long lastSend = 0;

bool readYourSensors(AgroReadings& reading) {
  // Replace this function with readings from your existing sensor code.
  // Do not paste example measurements: send the real sensor variables.
  //
  // reading.temperature_c = temperature;
  // reading.humidity_pct = humidity;
  // reading.pressure_hpa = pressureInPascals / 100.0f; // if sensor returns Pa
  // reading.altitude_m = altitude;
  // reading.rain_raw = rainAdc;
  // reading.soil_raw = soilAdc;
  // return true;
  return false; // No fake measurements are transmitted.
}

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  // TLS certificate validation requires a correct clock.
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  // Initialize your existing sensors here.
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    delay(500);
    return;
  }
  if (millis() - lastSend >= 5000) {
    lastSend = millis();
    AgroReadings reading;
    if (readYourSensors(reading)) {
      bool ok = agroPostReadings(API_URL, SENSOR_TOKEN, reading, ROOT_CA);
      Serial.println(ok ? "AgroAI: sent" : "AgroAI: check server, token and connection");
    }
  }
  delay(10);
}
