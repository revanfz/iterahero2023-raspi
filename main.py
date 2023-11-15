#!/usr/bin/python

import json
import aiomqtt
import paho.mqtt.client as paho
import RPi.GPIO as GPIO
import asyncio
import ssl
import sys
from sensor.Sensor import SensorADC, SensorSuhu

actuator = {"SELENOID_AIR": 2,
            "SELENOID_A": 17,
            "SELENOID_B": 22,
            "SELENOID_ASAM": 5,
            "SELENOID_BASA": 6,
            "MOTOR_MIXING": 13,
            "MOTOR_LARUTAN": 26,
            "RELAY_DISTRIBUSI": 4
            }

sensor = {"IN_WATERFLOW": 17}

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)

for sensor_name, sensor_pin in actuator.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def countPulse():
    global debit
    global volume
    pump_state = GPIO.input(actuator["POMPA"])
    if pump_state:
        debit = debit+1
        print(f"Volume air yang keluar: {debit / 378} L")
        if debit / 378 >= volume:
            actuator_control(actuator["POMPA"])
            GPIO.remove_event_detect(sensor["IN_WATERFLOW"])
            debit = 0


def actuator_control(pin):
    state = GPIO.input(pin)
    print("Mati" if state else "Nyala")
    GPIO.output(pin, not (state))
    # await asyncio.sleep(5)


async def main():
    global debit, volume
    ppm_value, ph_value = await asyncio.gather(
        EC_sensor.read_value(),
        pH_sensor.read_value()
    )
    print(f"pH Larutan: {ph_value}\nPPM Larutan: {ppm_value}")

    async with aiomqtt.Client("c401972c13f24e59b71daf85c5f5a712.s2.eu.hivemq.cloud",
                              8883,
                              username="iterahero2023",
                              password="Iterahero2023",
                              protocol=paho.MQTTv5,
                              tls_params=tls_params) as client:
        await client.publish("iterahero2023/info", json.dumps({"PPM": ppm_value, "PH": ph_value}), qos=1)
        async with client.messages() as messages:
            await client.subscribe("iterahero2023/#")
            async for message in messages:
                if message.topic.matches("iterahero2023/actuator"):
                    data = json.loads(message.payload)
                    print(data)
                    actuator_control(int(data['pin']))
                if message.topic.matches("iterahero2023/pompa"):
                    data = json.loads(message.payload)
                    volume = data['volume']
                    if (not (GPIO.input(actuator["POMPA"]))):
                        GPIO.add_event_detect(
                            sensor["IN_WATERFLOW"], GPIO.FALLING, callback=countPulse)
                        actuator_control(int(data['pin']))
                        print(data['volume'], data['pin'])
                    else:
                        GPIO.remove_event_detect(sensor["IN_WATERFLOW"])
                        actuator_control(int(data['pin']))
                        debit = 0


if __name__ == "__main__":
    try:
        global debit, volume
        tls_params = aiomqtt.TLSParameters(
            ca_certs=None,
            certfile=None,
            keyfile=None,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
            ciphers=None,
        )
        pH_sensor = SensorADC("Sensor pH DF Robot",
                              "y = -54.465x + 858.77", 0, "ph")
        EC_sensor = SensorADC("Sensor EC DF Robot",
                              "y = (0.043x + 13.663) - 60", 1, "ec")
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63")
        asyncio.run(main())

    except KeyboardInterrupt:
        GPIO.cleanup()
        sys.exit()
