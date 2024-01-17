#include <SPI.h>
#include "EEPROM.h"
#include "Arduino.h"
#include <OneWire.h>
#include <ArduinoJson.h>
#include "DFRobot_ESP_EC.h"
#include "DFRobot_ESP_PH_WITH_ADC.h"
#include <Adafruit_ADS1X15.h>
#include <DallasTemperature.h>

#define oneWireBus 13

// DFRobot_ESP_EC ec;
// Adafruit_ADS1115 ads;
// DFRobot_ESP_PH_WITH_ADC ph;
OneWire oneWire(oneWireBus);
DallasTemperature sensors(&oneWire);

float voltage_pH, voltage_EC, ecValue, phValue, temperature = 25;
int count = 0;
String NAME = "ESP32 Mitra";

float readTemperature()
{
  // add your code here to get the temperature from your temperature sensor
  sensors.requestTemperatures();
  return sensors.getTempCByIndex(0);
}

void setup()
{
  Serial.begin(115200);
  Serial.flush();
  EEPROM.begin(32); // Inisialisasi EEPROM untuk menyimpan k value kalibrasi EC
  pinMode(oneWireBus, INPUT_PULLUP);
  // ph.begin();
  // ec.begin(); // by default lib store calibration k since 10 change it by set ec.begin(30); to start from 30
  sensors.begin();
  // ads.setGain(GAIN_ONE);
  // ads.begin();
  delay(5000);
}

void sendData(float pH, float ec) {
  JsonDocument doc;
  doc["temperature"] = readTemperature();
  doc["ec"] = ec;
  doc["ph"] = pH;

  String jsonStr;
  serializeJson(doc, jsonStr);
  Serial.println(jsonStr);
}

// float read_voltage(int channel, String sensor)
// {
  // float voltage = ads.readADC_SingleEnded(channel) / 10;
  // Serial.print("Voltage ");
  // Serial.print(sensor);
  // Serial.print(": ");
  // Serial.print(voltage, 4);
  // Serial.print(" mV");
  // Serial.println();
  // return voltage;
// }

void loop()
{
  static unsigned long timepoint = millis();
  if (millis() - timepoint > 1500U) // time interval: 1s
  {
    timepoint = millis();
    // count++;
    // Serial.println("======================================");

    // Serial.print(count);
    // Serial.print(". ");

    // temperature = readTemperature(); // read your temperature sensor to execute temperature compensation
    // Serial.print(" temperature:");
    // Serial.print(temperature, 1);
    // Serial.println("°C");

    // voltage_EC = read_voltage(0, "EC");
    // voltage_pH = read_voltage(1, "pH");

    // ecValue = ec.readEC(voltage_EC, temperature); // convert voltage to EC with temperature compensation
    // Serial.print("EC: ");
    // Serial.print(ecValue, 4);
    // Serial.println("ms/cm");

    // Serial.print("PPM: ");
    // Serial.print(ecValue * 500, 2);
    // Serial.println("ppm");

    // phValue = ph.readPH(voltage_pH, temperature);
    // Serial.print("pH: ");
    // Serial.println(phValue, 4);

    // Serial.println("=======================================");
    // Serial.println();

    sendData(7.0, 12.188);
  }
  // ec.calibration(voltage_EC, temperature); // calibration process by Serail CMD
  // ph.calibration(voltage_pH, temperature);
}
