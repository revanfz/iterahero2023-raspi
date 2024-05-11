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

isi = {
    'tandon': 0
}

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

MQTT = None
NAME = "Raspberry Pi 4 B Peracikan"

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for actuator_name, actuator_pin in actuator.items():
    GPIO.setup(actuator_pin, GPIO.OUT)
    GPIO.output(actuator_pin, GPIO.LOW)

for sensor_name, sensor_pin in sensor.items():
    GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def countPulse(channel, volume, relay_aktuator, pin_sensor, cairan):
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        if debit[cairan] / 378 >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            peracikan_state[cairan + 'Enough'] = True
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
            isi['tandon'] = debit[cairan] / 378
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 378}")
            

def kontrol_peracikan(state=False, mix=False):
    control = GPIO.HIGH if state else GPIO.LOW
    GPIO.output(actuator["RELAY_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    if mix:
        GPIO.output(actuator["MOTOR_MIXING"], control)


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
        GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], cairan))
        GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    elif cairan == 'nutrisiA':
        GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_A"], sensor["WATERFLOW_A"], cairan))
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    elif cairan == 'nutrisiB':
        GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume, actuator["RELAY_B"], sensor["WATERFLOW_B"], cairan))
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)


async def validasi_ph(ph_min, ph_max, actual_ph):
    if ph_min <= actual_ph <= ph_max:
        print("PH aman")
    else:
        if actual_ph < 6.2:
            print("Tambahin Basa")
            basa_tambahan = math.log10(1 / (10 ** -actual_ph)) / 0.1 # Belum final
            print(f"Perlu tambahan {basa_tambahan} mL basa") 
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            # channel, vol_basa, actuator["RELAY_BASA"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))
        else:
            print("Tambahin asam")
            asam_tambahan = math.log10(1 /  (10 ** -(14 - actual_ph))) / 0.1 # belum final
            print(f"Perlu tambahan {asam_tambahan} mL asam")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, vol_asam, actuator["RELAY_ASAM"], sensor["WATERFLOW_ASAM_BASA"], 'asam'))


async def validasi_ppm(ppm_min, ppm_max, actual_ppm, konstanta, volume):
    print("Validasi PPM")
    if ppm_min <= actual_ppm <= ppm_max:
        print("PPM Aman")
    else:
        # ada yang ditambahin air / nutrisi
        GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)
        if actual_ppm < ppm_min - 200:
            print(f"Target ppm: {ppm_min} - {ppm_max}")
            print(f"Actual ppm: {actual_ppm}")

            nutrisi_tambahan_a = ((((ppm_min + ppm_max) / 2) * konstanta['rasioA'] / konstanta['ppm']) - (
                actual_ppm * konstanta['rasioA'] / konstanta['ppm'])) / 1000 * volume
            nutrisi_tambahan_b = ((((ppm_min + ppm_max) / 2) * konstanta['rasioB'] / konstanta['ppm']) - (
                actual_ppm * konstanta['rasioB'] / konstanta['ppm'])) / 1000 * volume
            GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
                channel, nutrisi_tambahan_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
            GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
                channel, nutrisi_tambahan_b, actuator["RELAY_B"], sensor["WATERFLOW_B"], 'nutrisiB'))

            print(f"Nutrisi A add: {nutrisi_tambahan_a}")
            print(f"Nutrisi B add: {nutrisi_tambahan_b}")

            # GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
            # GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
            # while not (peracikan_state['nutrisiAEnough']) or not (peracikan_state['nutrisiBEnough']):
            #     await asyncio.sleep(0.1)
        elif actual_ppm > ppm_max + 200:
            # Ngitung air yang mau ditambahin
            air_tambahan = ((actual_ppm * konstanta['rasioAir'] / konstanta['ppm']) - (
                ((ppm_min + ppm_max) / 2) * konstanta['rasioAir'] / konstanta['ppm'])) / 1000 * volume
            print(f"Air tambahan : {air_tambahan}")
            # GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, air_tambahan, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
            # GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
            # print("Tambahin air")
            # while not (peracikan_state['airEnough']):
            #     await asyncio.sleep(0.1)


async def peracikan(ph_min, ph_max, ppm_min, ppm_max, volume_air, volume_a, volume_b, konstanta, volume):
    try:
        GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume_air, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
        GPIO.add_event_detect(sensor["WATERFLOW_A"], GPIO.FALLING, callback=lambda channel: countPulse(
            channel, volume_a, actuator["RELAY_A"], sensor["WATERFLOW_A"], 'nutrisiA'))
        GPIO.add_event_detect(sensor["WATERFLOW_B"], GPIO.FALLING, callback=lambda channel: countPulse(
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
        
        await MQTT.publish("iterahero2023/actuator", json.dumps({"actuator": relay_state, "microcontrollerName": NAME}), qos=1)

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

        await asyncio.create_task(validasi_ppm(ppm_min, ppm_max, ppm_value, konstanta, volume))
        await asyncio.create_task(validasi_ph(ph_min, ph_max, ph_value))

        await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya", "microcontrollerName": NAME}), qos=1)
        stop_peracikan()
        turn_off_actuator()

        peracikan_state.update((key, False) for key in peracikan_state)
        debit.update((key, 0) for key in debit)

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        loop.run_until_complete(stop_peracikan())
        print(f"{e}")

    finally:
        await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya", "volume": isi['tandon'], "microcontrollerName": NAME}), qos=1)



def on_off_actuator(pin):
    state = GPIO.input(pin)
    print(state)
    GPIO.output(pin, not (state))
    print('Mati' if state else 'Nyala')


async def publish_sensor():
        global MQTT
        while True:
            try:
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

                await MQTT.publish("iterahero2023/info/sensor", json.dumps({"microcontrollerName": NAME, "sensor_adc": [
                    {str(sensor_adc[0]): round(ph_value, 2) + 5}, {sensor_adc[1]: ppm_value}], "sensor_non_adc": [{str(sensor_non_adc[0]): round(temp_value, 2)}]}), qos=1)
               
            except (asyncio.CancelledError, KeyboardInterrupt):
                print("Publish Sensor dihentikan")


async def publish_actuator(halt=False):
    while True and not halt:
        try:
            data = []
            for key, value in actuator.items():
                data.append({value: GPIO.input(value)})
            await MQTT.publish("iterahero2023/info/aktuator", json.dumps({ "aktuator": data, "microcontrollerName": NAME }), qos=1)
            await asyncio.sleep(1)
        
        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Publish Aktuator dihentikan{e}")     
            break

    if halt:
        await MQTT.publish("iterahero2023/info/aktuator", json.dumps({ "aktuator": data, "microcontrollerName": NAME }), qos=1)


async def publishStatus():
    while True:          
        try:
            await MQTT.publish("iterahero2023/mikrokontroller/status", json.dumps({ "mikrokontroler": NAME }), qos=1)
            await asyncio.sleep(1)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Publish Status mikrokontroller dihentikan {e}")     
            break


async def timerActuator(pin, duration):
    state = GPIO.input(pin)
    if not(state):
        print("Udah nyala")
    else:
        GPIO.output(pin, GPIO.HIGH) # Nyala
        print('Nyala')
        await asyncio.sleep(duration * 60)
        GPIO.output(pin, GPIO.LOW) # Mati


async def main():
    # Inisialisasi TLS parameter buat MQTT
    global MQTT
    # MQTT = aiomqtt.Client(config["mqtt_broker"],
    #                          8883,
    #                          username=config["mqtt_username"],
    #                          password=config["mqtt_password"],
    #                          protocol=paho.MQTTv5,
    #                          tls_params=tls_params,
    #                          keepalive=1800)
    MQTT = aiomqtt.Client(config["mqtt_broker_public"],
                          1883)
    while True:
        try:
            async with MQTT:
                try:
                    print("MQTT Ready")
                    await asyncio.sleep(0.2)
                    await MQTT.subscribe("iterahero2023/#")
                    asyncio.gather(publish_sensor(), publish_actuator(), publishStatus())
                    async with MQTT.messages() as messages:
                        async for message in messages:
                            data = json.loads(message.payload)
                            if message.topic.matches("iterahero2023/automation"):
                                print(data)
                                if data['microcontroller'] == NAME:
                                    if data['pin'] and 'durasi' in data:
                                        timerActuator(data['pin'], data['durasi'])
                                    elif data['pin']:
                                        on_off_actuator(data['pin'])
                            if message.topic.matches("iterahero2023/kontrol"):
                                print(data)
                                if data['pin'] and data['microcontroller'] == NAME:
                                    on_off_actuator(data['pin'])
                            if message.topic.matches("iterahero2023/waterflow"):
                                asyncio.create_task(test_waterflow(data['volume'], data['cairan']))
                            if message.topic.matches("iterahero2023/peracikans") and data['konstanta']['aktuator'][0]['microcontroller']['name'] == NAME:
                                x = check_peracikan()
                                if x:
                                    print("Masih ada peracikan yang berjalan")
                                else:
                                    komposisi = data['komposisi']
                                    await MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Meracik " + komposisi['nama'], "microcontrollerName": NAME}), qos=1)
                                    volume = komposisi['volume']
                                    ph_min = komposisi['ph_min']
                                    ph_max = komposisi['ph_max']
                                    ppm_min = komposisi['ppm_min']
                                    ppm_max = komposisi['ppm_max']
                                    konstanta = data['konstanta']
                                    print(konstanta)
                                    nutrisiA = round(
                                        ((ppm_min + ppm_max) / 2) / konstanta['ppm'] * konstanta['rasioA'] * volume / 1000, 3)
                                    nutrisiB = round(
                                        ((ppm_min + ppm_max) / 2) / konstanta['ppm'] * konstanta['rasioB'] * volume / 1000, 3)
                                    air = volume - (nutrisiA + nutrisiB)

                                    # Print value variabel
                                    checkVAR(locals())

                                    asyncio.create_task(peracikan(ph_min, ph_max, ppm_min, ppm_max, nutrisiA, nutrisiB, air, konstanta, volume))

                except KeyError as e:
                    print(f"Gaada {e}")

                except (ValueError, KeyboardInterrupt, asyncio.CancelledError) as e:
                    print(f"{e}")

        except aiomqtt.MqttError:
            print(f"Connection lost; Reconnecting in {3} seconds ...")
            await asyncio.sleep(3)

        except KeyboardInterrupt:
            print("Koneksi MQTT dihentikan")
            break
            

if __name__ == "__main__":
    try:
        pH_sensor = SensorADC("Sensor pH DF Robot",
                              "1000 * voltage / 820 / 200 * 1.45", 0, "ph")
        EC_sensor = SensorADC("Sensor EC DF Robot",
                              "y = (0.043x + 13.663) - 60", 1, "ec")
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63", 15)

        sensor_adc = [pH_sensor.channel, EC_sensor.channel]
        sensor_non_adc = [temp_sensor.GPIO]

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        loop.run_until_complete(MQTT.publish("iterahero2023/peracikan/info", json.dumps({"status": "Ada Isinya", "volume": isi['tandon'], "microcontrollerName": NAME}), qos=1))

        if check_peracikan():
            loop.run_until_complete(stop_peracikan())
        else:
            print("Sistem Dihentikan")

        turn_off_actuator()
        loop.run_until_complete(publish_actuator(halt=True))

    finally:
        GPIO.cleanup()
        sys.exit()
