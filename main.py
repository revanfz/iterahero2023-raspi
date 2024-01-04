import os
import datetime
import math
from random import randint, uniform
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
    "RELAY_A": 17,
    "RELAY_B": 2,
    "RELAY_ASAM": 20,
    "RELAY_BASA": 22,
    "RELAY_DISTRIBUSI": 6,
    "MOTOR_MIXING": 16,
    "MOTOR_NUTRISI": 25,
}

volume_tandon = 450

sensor = {
    "WATERFLOW_A": 13,
    "WATERFLOW_B": 26,
    "WATERFLOW_ASAM_BASA": 18,
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


tls_params = aiomqtt.TLSParameters(
    ca_certs=None,
    certfile=None,
    keyfile=None,
    cert_reqs=ssl.CERT_NONE,
    tls_version=ssl.PROTOCOL_TLS,
    ciphers=None,
)

client = None

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)
    GPIO.output(actuator_pin, GPIO.LOW)

for sensor_name, sensor_pin in sensor.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


async def actuatorState(channel, pin):
    await client.publish("iterahero2023/actuator", json.dumps({str(pin): True if GPIO.input(pin) else False}), qos=1)


def countPulse(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] / 378 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            peracikan_state[cairan + 'Enough'] = True
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 378}")

def countPulseAir(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] / 340 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            peracikan_state[cairan + 'Enough'] = True
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 68 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 340}")

def countPulseA(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] / 378 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            peracikan_state[cairan + 'Enough'] = True
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 378}")

def countPulseB(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] / 385 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            peracikan_state[cairan + 'Enough'] = True
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 77 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 385}")
            

def kontrol_peracikan(state=False):
    control = GPIO.HIGH if state else GPIO.LOW
    GPIO.output(actuator["RELAY_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    # GPIO.output(actuator["MOTOR_MIXING"], control)


def check_peracikan():
    air = GPIO.input(actuator["RELAY_AIR"])
    a = GPIO.input(actuator["RELAY_A"])
    b = GPIO.input(actuator["RELAY_B"])
    motor = GPIO.input(actuator["MOTOR_MIXING"])
    return air and a and b and motor


async def distribusi(selenoid, durasi):
    for item in selenoid:
        GPIO.output(item['GPIO'], GPIO.HIGH)
    try:
        await asyncio.sleep(durasi * 60)
    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")
    finally:
        print("Distribusi Selesai")
        for item in selenoid:
            GPIO.output(item['GPIO'], GPIO.LOW)


def checkVAR(item):
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")

def turn_off_actuator():
    for actuator_name, actuator_pin in actuator.items():
        GPIO.output(actuator_pin, GPIO.LOW)

def stop_peracikan():
    GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
    GPIO.remove_event_detect(sensor["WATERFLOW_A"])
    GPIO.remove_event_detect(sensor["WATERFLOW_B"])

    print("Peracikan Selesai" if peracikan_state["airEnough"] else "Peracikan Dihentikan")

async def test_waterflow(volume, cairan):
    if cairan == 'air':
        GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulseAir(
            channel, volume, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], cairan))
        GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    elif cairan == 'nutrisiA':
        GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulseA(
            channel, volume, actuator["RELAY_A"], sensor["WATERFLOW_A"], cairan))
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    elif cairan == 'nutrisiB':
        GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulseB(
            channel, volume, actuator["RELAY_B"], sensor["WATERFLOW_B"], cairan))
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)


async def validasi_ph(target_ph, actual_ph):
    if 6.0 <= actual_ph <= 7.0:
        print("PH aman")
    else:
        # ada yang ditambahin asam / basa
        if actual_ph < 6.2:
            print("Tambahin Basa")
            basa_tambahan = math.log10(1 / (10 ** -actual_ph)) / 0.1 # Belum final
            print(f"Perlu tambahan {basa_tambahan} L basa") 
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            # channel, vol_basa, actuator["RELAY_BASA"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))
        else:
            print("Tambahin asam")
            asam_tambahan = math.log10(1 /  (10 ** -(14 - actual_ph))) / 0.1 # belum final
            print(f"Perlu tambahan {asam_tambahan} L asam")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, vol_asam, actuator["RELAY_ASAM"], sensor["WATERFLOW_ASAM_BASA"], 'asam'))


async def validasi_ppm(target_ppm, actual_ppm, konstanta, volume):
    if target_ppm - 200 <= actual_ppm <= target_ppm + 200:
        print("PPM Aman")
    else:
        # ada yang ditambahin air / nutrisi
        GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)
        if actual_ppm < target_ppm - 200:
            print(f"Target ppm: {target_ppm}")
            print(f"Actual ppm: {actual_ppm}")

            nutrisi_tambahan_a = ((target_ppm * konstanta['rasioA'] / konstanta['ppm']) - (
                actual_ppm * konstanta['rasioA'] / konstanta['ppm'])) / 1000
            nutrisi_tambahan_b = ((target_ppm * konstanta['rasioB'] / konstanta['ppm']) - (
                actual_ppm * konstanta['rasioB'] / konstanta['ppm'])) / 1000
            GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulseA(
                channel, nutrisi_tambahan_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
            GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulseB(
                channel, nutrisi_tambahan_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

            print(f"Nutrisi A add: {nutrisi_tambahan_a}")
            print(f"Nutrisi B add: {nutrisi_tambahan_b}")

            GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
            GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
            while not (peracikan_state['nutrisiAEnough']) or not (peracikan_state['nutrisiBEnough']):
                await asyncio.sleep(0.1)
        else:
            # Ngitung air yang mau ditambahin
            air_tambahan = ((actual_ppm * konstanta['rasioAir'] / konstanta['ppm']) - (
                target_ppm * konstanta['rasioAir'] / konstanta['ppm'])) / 1000 * volume
            print(f"Air tambahan : {air_tambahan}")
            GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulseAir(
                channel, air_tambahan, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
            GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
            print("Tambahin air")
            while not (peracikan_state['airEnough']):
                await asyncio.sleep(0.1)


async def peracikan(pH, ppm, volume_air, volume_a, volume_b, konstanta, volume, penyiraman=False, durasi=None, pin_selenoid=None):
    GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulseAir(
        channel, volume_air, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
    GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulseA(
        channel, volume_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
    GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulseB(
        channel, volume_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

    if volume_air > 0:
         GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    else:
        GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
        peracikan_state["airEnough"] = True

    if volume_a > 0:
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    else:
        GPIO.remove_event_detect(sensor["WATERFLOW_A"])
        peracikan_state["nutrisiAEnough"] = True

    if volume_b > 0:
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
    else:
        GPIO.remove_event_detect(sensor["WATERFLOW_B"])
        peracikan_state["nutrisiBEnough"] = True

    GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)

    relay_state = [{str(actuator["MOTOR_MIXING"]): bool(GPIO.input(actuator["MOTOR_MIXING"]))},
                   {str(actuator["RELAY_AIR"]): bool(
                       GPIO.input(actuator["RELAY_AIR"]))},
                   {str(actuator["RELAY_A"]): bool(
                       GPIO.input(actuator["RELAY_A"]))},
                   {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))}]
    await client.publish("iterahero2023/actuator", json.dumps({"actuator": relay_state}), qos=1)

    while not (peracikan_state['airEnough']) or not (peracikan_state['nutrisiBEnough']) or not (peracikan_state['nutrisiAEnough']):
        print("Lagi ngeracik")
        await asyncio.sleep(0.2)

    peracikan_state.update((key, False) for key in peracikan_state)

    kontrol_peracikan(False)

    ppm_value, ph_value, temp_value = await asyncio.gather(
        EC_sensor.read_value(),
        pH_sensor.read_value(),
        temp_sensor.read_value()
    )
    print(
        f"\npH Larutan: {ph_value}\nPPM Larutan: {ppm_value}\nSuhu Larutan: {temp_value}\n")

    # VALIDASI PH
    await validasi_ph(pH, ph_value)

    # VALIDASI PPM
    await validasi_ppm(ppm, ppm_value, konstanta, volume)

    await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya"}), qos=1)
    stop_peracikan()
    turn_off_actuator()

    peracikan_state.update((key, False) for key in peracikan_state)
    debit.update((key, 0) for key in debit)

    if penyiraman:
        await distribusi(pin_selenoid, durasi)


async def publish_sensor(client):
        try:
            while True:
                ppm_value, ph_value, temp_value = await asyncio.gather(
                    EC_sensor.read_value(),
                    pH_sensor.read_value(),
                    temp_sensor.read_value()
                )
                
                print("======= INFO SENSOR ========")
                print(f"PH \t: {ph_value}")
                print(f"PPM \t: {ppm_value}")
                print(f"Suhu \t: {temp_value}")
                print("============================")
                print()
                
                ph_value = ph_value if ph_value > 0 else 0
                ppm_value = ppm_value if ppm_value > 0 else 0
                temp_value = temp_value if temp_value > 0 else 0

                await client.publish("iterahero2023/info/sensor", json.dumps({"sensor_adc": [
                    {str(sensor_adc[0]): round(ph_value, 2)}, {sensor_adc[1]: ppm_value}], "sensor_non_adc": [{str(sensor_non_adc[0]): round(temp_value, 2)}]}), qos=1)
                await asyncio.sleep(1)
               
        except KeyboardInterrupt:
            print("Publish Sensor dihentikan")


async def publish_actuator():
    global client
    data = []
    for key, value in actuator.items():
        data.append({value: GPIO.input(value)})
    await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya"}), qos=1)
    # await client.publish("iterahero2023/info/actuator", json.dumps({"actuator" : data}), qos=1)


def on_off_actuator(pin):
    state = GPIO.input(pin)
    GPIO.output(pin, not (state))
    print('Nyala' if not (state) else 'Mati')


async def main():
    # Inisialisasi TLS parameter buat MQTT
    global client
    # client = aiomqtt.Client(config["mqtt_broker"],
    #                          8883,
    #                          username=config["mqtt_username"],
    #                          password=config["mqtt_password"],
    #                          protocol=paho.MQTTv5,
    #                          tls_params=tls_params,
    #                          keepalive=1800)
    client = aiomqtt.Client(config["mqtt_broker_public"],
                           1883)
    async with client:
        try:
            print("MQTT Ready")
            await asyncio.sleep(0.2)
            # await client.subscribe("iterahero/#")
            await client.subscribe("iterahero2023/#")
            asyncio.create_task(publish_sensor(client))
            # asyncio.create_task(publish_actuator(client))
            async with client.messages() as messages:
                async for message in messages:
                    if message.topic.matches("iterahero2023/kontrol"):
                        data = json.loads(message.payload)
                        print(data)
                        if data['pin']:
                            on_off_actuator(data['pin'])
                    if message.topic.matches("iterahero2023/waterflow"):
                        data = json.loads(message.payload)
                        asyncio.create_task(test_waterflow(data['volume'], data['cairan']))
                    if message.topic.matches("iterahero2023/peracikan"):
                        x = check_peracikan()
                        if x:
                            print("Masih ada peracikan yang berjalan")
                        else:
                            data = json.loads(message.payload)
                            komposisi = data['komposisi']
                            await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Meracik " + komposisi['nama']}), qos=1)
                            volume = komposisi['volume']
                            ph = komposisi['ph']
                            ppm = komposisi['ppm']
                            konstanta = data['konstanta']
                            komposisi = data['komposisi']
                            print(konstanta)
                            nutrisiA = round(
                                ppm / konstanta['ppm'] * konstanta['rasioA'] * volume / 1000, 3)
                            nutrisiB = round(
                                ppm / konstanta['ppm'] * konstanta['rasioB'] * volume / 1000, 3)
                            air = volume - (nutrisiA + nutrisiB)

                            # Print value variabel
                            checkVAR(locals())

                            asyncio.create_task(peracikan(
                                ph, ppm, volume_a=nutrisiA, volume_b=nutrisiB,
                                volume_air=air, konstanta=konstanta, volume=volume))

                    if message.topic.matches("iterahero2023/penjadwalan-peracikan"):
                        x = check_peracikan()
                        if x:
                            print("Masih ada peracikan yang berjalan")
                        else:
                            data = json.loads(message.payload)
                            komposisi = data['komposisi']
                            await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Meracik " + komposisi['nama']}), qos=1)
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
                            checkVAR(locals())

                            port = [aktuator['GPIO'] or aktuator['channel']
                                    for aktuator in data['aktuator']]
                            aktuator = [
                                value for value in port if value in actuator.values()]

                            if len(aktuator) < 1:
                                raise ValueError('Aktuator gaada')

                            asyncio.create_task(peracikan(
                                ph, ppm, volume_a=nutrisiA, volume_b=nutrisiB,
                                volume_air=air, durasi=durasi, pin_selenoid=aktuator, penyiraman=True))
                    if message.topic.matches("iterahero2023/penjadwalan-distribusi"):
                        x = check_peracikan()
                        if x:
                            print("Masih ada peracikan yang berjalan")
                        else:
                            await client.publish("iterahero2023/peracikan/info", json.dumps({"status": "Penyiraman"}), qos=1)
                            data = json.loads(message.payload)
                            selenoid_distribusi = data['aktuator']
                            lama_penyiraman = data['lamaPenyiraman']
                            print(selenoid_distribusi)
                            asyncio.create_task(distribusi(
                                selenoid_distribusi, lama_penyiraman))

        except KeyError as e:
            print(f"Gaada {e}")

        except (ValueError, KeyboardInterrupt) as e:
            print(f"{e}")

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        pH_sensor = SensorADC("Sensor pH DF Robot",
                              "y = -54.465x + 858.77", 0, "ph")
        EC_sensor = SensorADC("Sensor EC DF Robot",
                              "y = (0.043x + 13.663) - 60", 1, "ec")
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63", 15)

        sensor_adc = [pH_sensor.channel, EC_sensor.channel]
        sensor_non_adc = [temp_sensor.GPIO]

        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        if check_peracikan():
            loop.run_until_complete(stop_peracikan())
        else:
            print("Sistem Dihentikan")

        turn_off_actuator()
        loop.run_until_complete(publish_actuator())

        GPIO.cleanup()
        sys.exit()
