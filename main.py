#!/usr/bin/python

import os
import ssl
import sys
import json
import asyncio
import aiomqtt

import RPi.GPIO as GPIO
import paho.mqtt.client as paho

from sensor.Sensor import SensorADC, SensorSuhu

with open(os.path.dirname(__file__) + '/config.json') as config_file:
    config_str = config_file.read()
    config = json.loads(config_str)

actuator = {
    "RELAY_AIR": 5,
    "RELAY_A": 2,
    "RELAY_B": 17,
    "RELAY_ASAM": 20,
    "RELAY_BASA": 22,
    "RELAY_DISTRIBUSI": 6,
    "MOTOR_MIXING": 7,
    "MOTOR_NUTRISI": 25,
}

sensor = {
    "WATERFLOW_A": 26,
    "WATERFLOW_B": 13,
    "WATERFLOW_ASAM_BASA": 18,
    "WATERFLOW_DISTRIBUSI": 23,
    "WATERFLOW_AIR": 24
}

debit = {
    'air': 0,
    'asam': 0,
    'basa': 0,
    'distribusi': 0,
    'nutrisiA': 0,
    'nutrisiB': 0
}

volume = {
    'nutrisiA': 0,
    'nutrisiB': 0,
    'air': 0,
    'asam': 0,
    'basa': 0
}

peracikan_state = {
    'airEnough': False,
    'basaEnough': False,
    'asamEnough': False,
    'nutrisiAEnough': False,
    'nutrisiBEnough': False
}

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)

for sensor_name, sensor_pin in sensor.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


async def test_baca():
    x, y = await asyncio.gather(
        pH_sensor.read_value(),
        EC_sensor.read_value()
    )
    print(x, y)


def countPulse(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] = debit[cairan] + 1
        print(f"Volume air yang keluar: {debit / 378} L")
        if debit[cairan] / 378 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
            peracikan_state[cairan + 'Enough'] = True


def kontrol_peracikan():
    GPIO.output(actuator["RELAY_AIR"], not (GPIO.input(actuator["RELAY_AIR"])))
    GPIO.output(actuator["RELAY_A"], not (GPIO.input(actuator["RELAY_A"])))
    GPIO.output(actuator["RELAY_A"], not (GPIO.input(actuator["RELAY_A"])))


def check_peracikan():
    air = GPIO.input(actuator["RELAY_AIR"])
    a = GPIO.input(actuator["RELAY_A"])
    b = GPIO.input(actuator["RELAY_B"])
    return air and a and b


async def penyiraman(pin_selenoid, durasi):
    GPIO.output(pin_selenoid, GPIO.HIGH)
    await asyncio.sleep(durasi)
    GPIO.output(pin_selenoid, GPIO.LOW)


def checkVAR(item):
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")


async def peracikan(pH, ppm, volume_air, volume_a, volume_b, durasi, pin_selenoid):
    GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_air, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
    GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
    GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
        channel, volume_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

    GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_B"], GPIO.HIGH)

    while not (peracikan_state['airEnough']) and not (peracikan_state['asamEnough']) and not (peracikan_state['basaEnough']):
        print("Lagi ngeracik")
        await asyncio.sleep(0.5)

    #  temp_value
    ppm_value, ph_value = await asyncio.gather(
        EC_sensor.read_value(),
        pH_sensor.read_value(),
        # temp_sensor.read_value()
    )
    print(f"\npH Larutan: {ph_value}\nPPM Larutan: {ppm_value}\n")
    # print(f"\npH Larutan: {ph_value}\nPPM Larutan: {ppm_value}\nSuhu Larutan: {temp_value}\n")

    if 6.0 <= ph_value <= 7.0:
        print("PH aman")
    else:
        # ada yang ditambahin asam / basa
        if ph_value < 6.2:
            print("Tambahin Basa")
        else:
            print("Tambahin asam")
    if ppm - 200 <= ppm_value <= ppm + 200:
        print("PPM Aman")
    else:
        # ada yang ditambahin air / nutrisi
        if ppm_value < 1000:
            print("Tambahin nutrisi")
        else:
            print("Tambahin air")

    for key in peracikan_state:
        peracikan_state[key] = False

    GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
    GPIO.remove_event_detect(sensor["WATERFLOW_A"])
    GPIO.remove_event_detect(sensor["WATERFLOW_B"])

    GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    GPIO.output(actuator["RELAY_B"], GPIO.HIGH)

    await asyncio.create_task(penyiraman(pin_selenoid, durasi))


async def main():
    # Inisialisasi TLS parameter TLS buat MQTT
    tls_params = aiomqtt.TLSParameters(
        ca_certs=None,
        certfile=None,
        keyfile=None,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS,
        ciphers=None,
    )
    async with aiomqtt.Client(config["mqtt_broker"],
                              8883,
                              username=config["mqtt_username"],
                              password=config["mqtt_password"],
                              protocol=paho.MQTTv5,
                              tls_params=tls_params) as client:
        await asyncio.sleep(0.2)
        print("MQTT Ready")
        async with client.messages() as messages:
            await client.subscribe("iterahero2023/#")
            async for message in messages:
                print(message.topic)
                if message.topic.matches("iterahero2023/actuator"):
                    data = json.loads(message.payload)
                    print(data)
                if message.topic.matches("iterahero2023/peracikan"):
                    x = check_peracikan()
                    if x:
                        print("Masih ada peracikan yang berjalan")
                    else:
                        try:
                            data = json.loads(message.payload)
                            komposisi = data['komposisi']
                            volume = komposisi['volume']
                            ph = komposisi['ph']
                            ppm = komposisi['ppm']
                            durasi = data['lamaPenyiraman']
                            konstanta = data['konstanta']

                            # Menimbang ada konstanta rasio A : B : Air, maka:
                            nutrisiA = round(
                                ppm / konstanta['ppm'] * konstanta['rasioA'] * volume / 1000, 3)
                            nutrisiB = round(
                                ppm / konstanta['ppm'] * konstanta['rasioB'] * volume / 1000, 3)
                            air = volume - (nutrisiA + nutrisiB)

                            # Print value variabel
                            # checkVAR(locals())

                            port = [aktuator['portRaspi']
                                    for aktuator in data['aktuator']]
                            aktuator = [
                                value for value in port if value in actuator.values()]

                            if len(aktuator) < 1:
                                raise ValueError('Aktuator gaada')

                            asyncio.create_task(peracikan(
                                ph, ppm, volume_a=nutrisiA, volume_b=nutrisiB,
                                volume_air=air, durasi=durasi, pin_selenoid=aktuator))

                        except KeyError as e:
                            print(f"Gaada {e}")

                        except ValueError as e:
                            print(f"{e}")

if __name__ == "__main__":
    try:
        pH_sensor = SensorADC("Sensor pH DF Robot",
                              "y = -54.465x + 858.77", 0, "ph")
        EC_sensor = SensorADC("Sensor EC DF Robot",
                              "y = (0.043x + 13.663) - 60", 1, "ec")
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63")
        asyncio.run(main())

    except KeyboardInterrupt:

        for actuator_name, actuator_pin in actuator.items():
            GPIO.output(actuator_pin, GPIO.LOW)

        GPIO.cleanup()
        sys.exit()
