#include "map"
#include <SPI.h>
#include "EEPROM.h"
#include "Arduino.h"
#include <OneWire.h>
#include <ArduinoJson.h>
#include "DFRobot_ESP_EC.h"
#include "DFRobot_ESP_PH_WITH_ADC.h"
#include <Adafruit_ADS1X15.h>
#include <DallasTemperature.h>

// pH channel 1
// EC channel 3
#define oneWireBus 13 // Sensor Suhu
#define waterflowAir 15
#define waterflowAsam 2
#define waterflowA 4
#define waterflowB 5
#define waterflowDistribusi 18

DFRobot_ESP_EC ec;
Adafruit_ADS1115 ads;
DFRobot_ESP_PH_WITH_ADC ph;
OneWire oneWire(oneWireBus);
DallasTemperature sensors(&oneWire);

const String NAME = "ESP32 Mitra";

float voltage_pH, voltage_EC, ecValue, phValue, temperature = 25;
float calibrationFactor = 4.5;

bool isMixing = false;
bool isDistribusi = false;
bool penyesuaianPpm = false;
bool penyesuaianPh = false;

String monitorWaterflow = "";

std::map<String, int> pulseCount = {
    {"air", 0},
    {"a", 0},
    {"b", 0},
    {"asam", 0},
    {"distribusi", 0}};

std::map<String, float> flowRate = {
    {"air", 0},
    {"a", 0},
    {"b", 0},
    {"asam", 0},
    {"distribusi", 0}};

std::map<String, float> flowML = {
    {"air", 0},
    {"a", 0},
    {"b", 0},
    {"asam", 0},
    {"distribusi", 0}};

std::map<String, float> totalML = {
    {"air", 0},
    {"a", 0},
    {"b", 0},
    {"asam", 0},
    {"distribusi", 0}};

void pulseCounter(const String &cairan)
{
  pulseCount[cairan]++;
}

void setup()
{
  Serial.begin(115200);
  Serial.flush();
  EEPROM.begin(32); // Inisialisasi EEPROM untuk menyimpan k value kalibrasi EC
  pinMode(oneWireBus, INPUT_PULLUP);
  pinMode(waterflowAir, INPUT_PULLUP);
  pinMode(waterflowAsam, INPUT_PULLUP);
  pinMode(waterflowA, INPUT_PULLUP);
  pinMode(waterflowB, INPUT_PULLUP);
  pinMode(waterflowDistribusi, INPUT_PULLUP);
  ph.begin();
  ec.begin(); // by default lib store calibration k since 10 change it by set ec.begin(30); to start from 30
  ads.setGain(GAIN_ONE);
  ads.begin();
  sensors.begin();
}

float read_voltage(int channel, String sensor)
{
    float voltage = ads.readADC_SingleEnded(channel) / 10;
    Serial.print("Voltage ");
    Serial.print(sensor);
    Serial.print(": ");
    Serial.print(voltage, 4);
    Serial.print(" mV");
    Serial.println();
    return voltage;
  return 0.0;
}

void readTemp()
{
  sensors.requestTemperatures();
  temperature = sensors.getTempCByIndex(0); // read your temperature sensor to execute temperature compensation
  Serial.print(" temperature:");
  Serial.print(temperature, 1);
  Serial.println("°C");
}

void readEC()
{
  voltage_pH = read_voltage(3, "EC");
  ecValue = ec.readEC(voltage_EC, temperature); // convert voltage to EC with temperature compensation
  Serial.print("EC: ");
  Serial.print(ecValue, 4);
  Serial.println("ms/cm");

  Serial.print("PPM: ");
  Serial.print(ecValue * 500, 2);
  Serial.println("ppm");
}

void readpH()
{
  voltage_EC = read_voltage(0, "PH");
  phValue = ph.readPH(voltage_pH, temperature);
  Serial.print("pH: ");
  Serial.println(phValue, 4);
}

void startMixing()
{
  attachInterrupt(
      digitalPinToInterrupt(waterflowAir), []()
      { pulseCounter("air"); },
      FALLING);
  attachInterrupt(
      digitalPinToInterrupt(waterflowAsam), []()
      { pulseCounter("asam"); },
      FALLING);
  attachInterrupt(
      digitalPinToInterrupt(waterflowA), []()
      { pulseCounter("a"); },
      FALLING);
  attachInterrupt(
      digitalPinToInterrupt(waterflowB), []()
      { pulseCounter("b"); },
      FALLING);

  isMixing = true;
}

void stopMixing()
{
  JsonDocument doc;
  doc["volume"]["peracikan"] = totalML["air"] + totalML["a"] + totalML["b"];
  String volume;
  serializeJson(doc, volume);
  Serial.println(volume);

  for (const auto &fluid : {"air", "a", "b", "asam"})
  {
    totalML[fluid] = 0;
  }
  detachInterrupt(digitalPinToInterrupt(waterflowAir));
  detachInterrupt(digitalPinToInterrupt(waterflowAsam));
  detachInterrupt(digitalPinToInterrupt(waterflowA));
  detachInterrupt(digitalPinToInterrupt(waterflowB));

  isMixing = false;
}

void distribusi()
{
  attachInterrupt(
      digitalPinToInterrupt(waterflowDistribusi), []()
      { pulseCounter("distribusi"); },
      FALLING);

  isDistribusi = true;
}

void stopDistribusi()
{
  detachInterrupt(digitalPinToInterrupt(waterflowDistribusi));
  isDistribusi = false;
  JsonDocument doc;
  doc["volume"]["distribusi"] = totalML["distribusi"];
  String volume;
  serializeJson(doc, volume);
  Serial.println(volume);
}

void ppmAdjustment() {
  attachInterrupt(
      digitalPinToInterrupt(waterflowA), []()
      { pulseCounter("a"); },
      FALLING);
  attachInterrupt(
      digitalPinToInterrupt(waterflowB), []()
      { pulseCounter("b"); },
      FALLING);

  penyesuaianPpm = true;
}

void stopPpmAdjustment() {
  detachInterrupt(digitalPinToInterrupt(waterflowA));
  detachInterrupt(digitalPinToInterrupt(waterflowB));

  for (const auto &fluid : {"a", "b"})
  {
    totalML[fluid] = 0;
  }

  penyesuaianPpm = false;
}

void phAdjusment() {
  attachInterrupt(
      digitalPinToInterrupt(waterflowAsam), []()
      { pulseCounter("asam"); },
      FALLING);

  penyesuaianPh = true;
}

void stopPhAdjustment() {
  detachInterrupt(digitalPinToInterrupt(waterflowAsam));

  totalML["asam"] = 0;

  penyesuaianPh = false;
}

void readWaterflowPeracikan(unsigned long timepoint)
{
  for (const auto &fluid : {"air", "a", "b", "asam"})
  {
    byte pulse1Sec = pulseCount[fluid];
    pulseCount[fluid] = 0;
    flowRate[fluid] = ((1000.0 / (millis() - timepoint)) * pulse1Sec) / calibrationFactor;
    flowML[fluid] = (flowRate[fluid] / 60) * 1000;
    totalML[fluid] += flowML[fluid];

    Serial.print(String(fluid) + " Flow rate: ");
    Serial.print(flowRate[fluid], 2); // Print nilai dengan dua digit di belakang koma
    Serial.print(" L/min\t");         // Tab space

    Serial.print("Output Liquid Quantity: ");
    Serial.print(totalML[fluid], 2);
    Serial.print(" mL / ");
    Serial.print(totalML[fluid] / 1000, 2);
    Serial.println(" L");
  }
  Serial.println();
}

void readWaterflow(const String &fluid, unsigned long timepoint)
{
  byte pulse1Sec = pulseCount[fluid];
  pulseCount[fluid] = 0;
  flowRate[fluid] = ((1000.0 / (millis() - timepoint)) * pulse1Sec) / calibrationFactor;
  flowML[fluid] = (flowRate[fluid] / 60) * 1000;
  totalML[fluid] += flowML[fluid];

  Serial.print(fluid + " Flow rate: ");
  Serial.print(flowRate[fluid], 2);
  Serial.print(" L/min\t");

  Serial.print("Output Liquid Quantity: ");
  Serial.print(totalML[fluid], 2);
  Serial.print(" mL / ");
  Serial.print(totalML[fluid] / 1000, 2);
  Serial.println(" L");
}

void sendWaterflow(const String &fluid)
{
  voltage_pH = read_voltage(1, "PH");
  voltage_EC = read_voltage(3, "EC");
  JsonDocument doc;
  doc["waterflow"][String(fluid)]["total"] = totalML[fluid];
  doc["waterflow"][String(fluid)]["debit"] = flowRate[fluid];
  doc["microcontroller"] = NAME;

  String waterflow;
  serializeJson(doc, waterflow);
  Serial.println(waterflow);
}

void sendData()
{
  JsonDocument doc;
  doc["info"]["temperature"] = sensors.getTempCByIndex(0);
  doc["info"]["ec"] = ec.readEC(voltage_EC, doc["info"]["temperature"]) * 500;
  doc["info"]["ph"] = ph.readPH(voltage_pH, doc["info"]["temperature"]);
  doc["microcontroller"] = NAME;

  String jsonStr;
  serializeJson(doc, jsonStr);
  Serial.println(jsonStr);
}

void sendStatus() {
  JsonDocument doc;
  doc["microcontroller"] = NAME;

  String jsonStr;
  serializeJson(doc, jsonStr);
  Serial.println(jsonStr);
}

void loop()
{
  static unsigned long timepointPeracikan = millis();
  static unsigned long timepointDefault = millis();
  if (Serial.available() > 0)
  {
    String serialMessage = Serial.readStringUntil('\n');
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, serialMessage);
    if (error)
    {
      Serial.print("Failed to parse JSON: ");
      Serial.println(error.c_str());
    }
    else
    {
      if (doc.containsKey("peracikan"))
      {
        if (doc["peracikan"])
          startMixing();
        else
          stopMixing();
      }
      if (doc.containsKey("distribusi"))
      {
        if (doc["distribusi"])
          distribusi();
        else
          stopDistribusi();
      }
      if (doc.containsKey("detach")) {
          detachInterrupt(digitalPinToInterrupt(doc["detach"]["pin"]));
          sendWaterflow(doc["detach"]["cairan"]);
      }
      if (doc.containsKey("waterflow"))
      {
        if (doc["waterflow"].containsKey("volume"))
        {
          monitorWaterflow = doc["waterflow"]["cairan"].as<String>();
          attachInterrupt(
              digitalPinToInterrupt(doc["waterflow"]["pin"]), []()
              { pulseCounter(monitorWaterflow); },
              FALLING);
        }
        else
        {
          detachInterrupt(digitalPinToInterrupt(doc["waterflow"]["pin"]));
          monitorWaterflow = "";
          totalML[doc["waterflow"]["cairan"]] = 0;
        }
      }
      if (doc.containsKey("adjustment")) {
        if (doc["adjustment"].containsKey("ppm")) {
          if (doc["adjustment"]["ppm"]) ppmAdjustment();
          else stopPpmAdjustment();
        } else {
          if (doc["adjustment"]["ph"]) phAdjusment();
          else stopPhAdjustment();
        }
      }
    }
  }
  // time interval: 1s
  if (millis() - timepointPeracikan > 1000U)
  {
    if (isDistribusi)
    {
      readWaterflow("distribusi", timepointPeracikan);
      sendWaterflow("distribusi");
    }

    // if (monitorWaterflow != "")
    // {
    //   readWaterflow(monitorWaterflow, timepointPeracikan);
    //   sendWaterflow(monitorWaterflow);
    // }
    for (const auto &fluid : {"air", "a", "b", "asam"})
      {
        readWaterflow(fluid, timepointPeracikan);
        sendWaterflow(fluid);
      }
    timepointPeracikan = millis();
  }
  if (millis() - timepointDefault > 2500U)
  {
    sendStatus();
    sendData();
    timepointDefault = millis();
  }
}
