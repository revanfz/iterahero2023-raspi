import os
import math
import random
import ssl
import sys
import json
import asyncio
import time
import aiomqtt
import datetime
import RPi.GPIO as GPIO
import serial.tools.list_ports
import paho.mqtt.client as paho

from aiomqtt import Will
from sensor.Sensor import SensorADC, SensorSuhu, SensorWaterflow

with open(os.path.dirname(__file__) + "/config.json") as config_file:
    config_str = config_file.read()
    config = json.loads(config_str)

# DEKLARASI PIN  DAN VARIABEL #
actuator = {
    "MOTOR_NUTRISI": 26,
    "MOTOR_MIXING": 13,
    "RELAY_AIR": 6,
    "RELAY_A": 5,
    "RELAY_B": 22,
    "POMPA_NUTRISI": 17,
    "SOLENOID_VALIDASI": 2,  # Relay Basa
    "SOLENOID_DISTRIBUSI": 20,  # Relay Asam
}

isi = {"tandon": 0}

sensor = {
    "WATERFLOW_A": 23,
    "WATERFLOW_B": 24,
    "WATERFLOW_ASAM_BASA": 18,
    "WATERFLOW_AIR": 25,
}

debit = {"air": 0, "asam": 0, "basa": 0, "distribusi": 0, "nutrisiA": 0, "nutrisiB": 0}

sum_volume = {"nutrisiA": 0, "nutrisiB": 0, "air": 0, "asam": 0, "basa": 0}

peracikan_state = {
    "airEnough": False,
    "basaEnough": False,
    "asamEnough": False,
    "nutrisiAEnough": False,
    "nutrisiBEnough": False,
}

distribusi_start, distribusi_update = (0, 0)
a_start, a_update = (0, 0)
b_start, b_update = (0, 0)
air_start, air_update = (0, 0)


tls_params = aiomqtt.TLSParameters(
    ca_certs=None,
    certfile=None,
    keyfile=None,
    cert_reqs=ssl.CERT_NONE,
    tls_version=ssl.PROTOCOL_TLS,
    ciphers=None,
)

ESP_ser = None
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
    """
    Menghtung volume yang keluar dari waterflow
    args:
        volume: volume target yang ingin dikeluarkan
        relay_aktuator: pin relay untuk mengontrol aktuator
        pin_sensor: pin sensor yang digunakan
        cairan: cairan yang dikeluarkan
        distribusi: apakah peracikan untuk distribusi
    """
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        sum_volume[cairan] = debit[cairan] / 378
        if sum_volume[cairan] >= volume:
            GPIO.output(relay_aktuator, GPIO.LOW)
            if cairan == "air":
                start_time = air_start
            elif cairan == "nutrisiB":
                start_time = b_start
            elif cairan == "nutrisiA":
                start_time = a_start
            peracikan_state[cairan + "Enough"] = True
            print(f"{volume} L membutuhkan waktu {time.time() - start_time} ")
            GPIO.remove_event_detect(pin_sensor)
            debit[cairan] = 0
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {sum_volume[cairan]}")


def countPulseManual(channel, relay_aktuator, pin_sensor, cairan):
    """
    Menghitung debit waterflow
    """
    actuator_state = GPIO.input(relay_aktuator)
    if actuator_state:
        debit[cairan] += 1
        isi["tandon"] += 1 / 378
        if debit[cairan] % 75 == 0:
            print(f"Volume {cairan} yang keluar: {debit[cairan] / 378}")


def kontrol_peracikan(state=False, mix=False):
    """
    Mengontrol aktuator peracikan
    args:
        state: true jika ingin menyalakan, false untuk mematikan
        mix: apakah motor berputar
    """
    control = GPIO.HIGH if state else GPIO.LOW
    GPIO.output(actuator["RELAY_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    if mix:
        GPIO.output(actuator["MOTOR_MIXING"], control)
        GPIO.output(actuator["SOLENOID_VALIDASI"], control)


def kontrol_peracikan(state=False, mix=False):
    """
    Mengontrol aktuator peracikan
    args:
        state: true jika ingin menyalakan, false untuk mematikan
        mix: apakah motor berputar
    """
    control = GPIO.HIGH if state else GPIO.LOW
    GPIO.output(actuator["RELAY_AIR"], control)
    GPIO.output(actuator["RELAY_A"], control)
    GPIO.output(actuator["RELAY_B"], control)
    if mix:
        GPIO.output(actuator["MOTOR_MIXING"], control)


def check_peracikan():
    """
    Mengecek apakah peracikan sedang berjalan
    """
    air = GPIO.input(actuator["RELAY_AIR"])
    a = GPIO.input(actuator["RELAY_A"])
    b = GPIO.input(actuator["RELAY_B"])
    motor = GPIO.input(actuator["MOTOR_MIXING"])
    return air or a or b or motor


def checkVAR(item):
    """
    Mengecek data variabel untuk debugging resep peracikan
    """
    for var_names, var_value in item.items():
        print(f"{var_names} = {var_value}")


def turn_off_actuator():
    """
    Mematikan semua aktuator
    """
    for actuator_name, actuator_pin in actuator.items():
        GPIO.output(actuator_pin, GPIO.LOW)


async def stop_peracikan():
    """
    Menghentikan peracikan
    """
    GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
    GPIO.remove_event_detect(sensor["WATERFLOW_A"])
    GPIO.remove_event_detect(sensor["WATERFLOW_B"])

    isi["tandon"] += sum_volume["air"] + sum_volume["nutrisiA"] + sum_volume["nutrisiB"]
    sum_volume.update((key, 0) for key in sum_volume)
    debit.update((key, 0) for key in debit)

    peracikan_state.update((key, False) for key in peracikan_state)
    debit.update((key, 0) for key in debit)
    kontrol_peracikan(mix=True)

    print(
        "Peracikan Selesai" if peracikan_state["airEnough"] else "Peracikan Dihentikan"
    )

    relay_state = [
        {
            str(actuator["MOTOR_MIXING"]): bool(
                GPIO.input(actuator["MOTOR_MIXING"])
            )
        },
        {str(actuator["RELAY_AIR"]): bool(GPIO.input(actuator["RELAY_AIR"]))},
        {str(actuator["RELAY_A"]): bool(GPIO.input(actuator["RELAY_A"]))},
        {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))},
        {
            str(actuator["SOLENOID_DISTRIBUSI"]): bool(
                GPIO.input(actuator["SOLENOID_DISTRIBUSI"])
            )
        },
        {
            str(actuator["SOLENOID_VALIDASI"]): bool(
                GPIO.input(actuator["SOLENOID_VALIDASI"])
            )
        },
        {
            str(actuator["POMPA_NUTRISI"]): bool(
                GPIO.input(actuator["POMPA_NUTRISI"])
            )
        },
    ]

    await asyncio.gather(
        MQTT.publish(
            "iterahero2023/peracikan/info",
            json.dumps(
                {
                    "status": "Berisi nutrisi",
                    "volume": round(isi["tandon"], 2),
                    "microcontrollerName": NAME,
                }
            ),
            qos=1,
        ),
        MQTT.publish(
            "iterahero2023/actuator",
            json.dumps({"actuator": relay_state, "microcontrollerName": NAME}),
            qos=1,
        ),
    )


async def test_waterflow(volume, cairan):
    """
    Trial and error waterflow
    args:
        volume: volume target yang ingin dikeluarkan
        cairan: cairan yang dikeluarkan
    """
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    if cairan == "air":
        GPIO.add_event_detect(
            sensor["WATERFLOW_AIR"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel, volume, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], cairan
            ),
        )
        air_start = time.time()
        air_update = air_start
        GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
    elif cairan == "nutrisiA":
        GPIO.add_event_detect(
            sensor["WATERFLOW_A"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel, volume, actuator["RELAY_A"], sensor["WATERFLOW_A"], cairan
            ),
        )
        a_start = time.time()
        a_update = a_start
        GPIO.output(actuator["RELAY_A"], GPIO.HIGH)
    elif cairan == "nutrisiB":
        GPIO.add_event_detect(
            sensor["WATERFLOW_B"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel, volume, actuator["RELAY_B"], sensor["WATERFLOW_B"], cairan
            ),
        )

        b_start = time.time()
        b_update = b_start
        GPIO.output(actuator["RELAY_B"], GPIO.HIGH)


async def validasi_ph(ph_min, ph_max, actual_ph):
    """
    Validasi PH nutrisi
    args:
        ph_min: nilai minimal dari ph target
        ph_max: nilai maksimal dari ph target
        actual_ph: nilai ph yang dibaca sensor
    """
    print("Validasi PH")
    if ph_min <= actual_ph <= ph_max:
        print("PH aman")
    else:
        if actual_ph < 6.2:
            print("Perlu tambahan Basa")
            basa_tambahan = math.log10(1 / (10**-actual_ph)) / 0.1  # Belum final
            print(f"Perlu tambahan {basa_tambahan} mL basa")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            # channel, vol_basa, actuator["SOLENOID_DISTRIBUSI"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))
            basa_tambahan = math.log10(1 / (10**-actual_ph)) / 0.1  # Belum final
            print(f"Perlu tambahan {basa_tambahan} mL basa")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            # channel, vol_basa, actuator["SOLENOID_DISTRIBUSI"], sensor["WATERFLOW_ASAM_BASA"], 'basa'))
        else:
            print("Perlu tambahan Asam")
            asam_tambahan = (
                math.log10(1 / (10 ** -(14 - actual_ph))) / 0.1
            )  # belum final
            print(f"Perlu tambahan {asam_tambahan} mL asam")
            # GPIO.add_event_detect(sensor["WATERFLOW_ASAM_BASA"], GPIO.FALLING, callback=lambda channel: countPulse(
            #     channel, vol_asam, actuator["SOLENOID_VALIDASI"], sensor["WATERFLOW_ASAM_BASA"], 'asam'))
    await asyncio.sleep(0.1)


async def validasi_ppm(ppm_min, ppm_max, actual_ppm, konstanta, volume):
    print(">>> Validasi PPM <<<")
    global air_start, air_update, a_start, a_update, b_start, b_update
    try:
        status = False
        validasi = False
        print("Pompa validasi dinyalakan")
        GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.HIGH)
        await asyncio.sleep(0.2)
        GPIO.output(actuator["POMPA_NUTRISI"], GPIO.HIGH)
        await asyncio.sleep(30)
        GPIO.output(actuator["POMPA_NUTRISI"], GPIO.LOW)
        await asyncio.sleep(0.2)
        GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.LOW)
        await asyncio.sleep(30)
        validasi_start = time.time()
        if ppm_min <= actual_ppm <= ppm_max:
            print("PPM Aman <<<")
        else:
            validasi = True
            print(f"Target ppm: {ppm_min} - {ppm_max} <<<")
            print(f"Actual ppm: {EC_sensor.nilai} <<<")
            actual_ppm = EC_sensor.nilai
            if actual_ppm < ppm_min:
                # nutrisi_tambahan_a = (
                #     (
                #         (((ppm_min + ppm_max) / 2) * konstanta["rasioA"] / konstanta["ppm"])
                #         - (actual_ppm * konstanta["rasioA"] / konstanta["ppm"])
                #     )
                #     / 1000
                #     * volume
                # )
                # nutrisi_tambahan_b = (
                #     (
                #         (((ppm_min + ppm_max) / 2) * konstanta["rasioB"] / konstanta["ppm"])
                #         - (actual_ppm * konstanta["rasioB"] / konstanta["ppm"])
                #     )
                #     / 1000
                #     * volume
                # )
                # print(">>> Perhitungan Lama")
                # print(f"Nutrisi A add: {nutrisi_tambahan_a}")
                # print(f"Nutrisi B add: {nutrisi_tambahan_b} <<<")

                print("PPM kurang, penambahan nutrisi dilakukan sampai PPM memenuhi")
                GPIO.add_event_detect(
                    sensor["WATERFLOW_A"],
                    GPIO.FALLING,
                    callback=lambda channel: countPulseManual(
                        channel,
                        actuator["RELAY_A"],
                        sensor["WATERFLOW_A"],
                        "nutrisiA",
                    ),
                )
                GPIO.add_event_detect(
                    sensor["WATERFLOW_B"],
                    GPIO.FALLING,
                    callback=lambda channel: countPulseManual(
                        channel,
                        actuator["RELAY_B"],
                        sensor["WATERFLOW_B"],
                        "nutrisiB",
                    ),
                )
                GPIO.output(actuator["RELAY_A"], GPIO.HIGH),
                GPIO.output(actuator["RELAY_B"], GPIO.HIGH)
                a_start = time.time()
                a_update = a_start
                b_start = time.time()
                b_update = b_start

                logging_time = time.time()
                validasi_time = time.time()
                pompa_on = False

                while EC_sensor.nilai < ppm_min:
                    await asyncio.sleep(0.1)
                    if time.time() - logging_time >= 3:
                        if pompa_on:
                            MQTT.publish(
                                "iterahero2023/peracikan/info",
                                json.dumps(
                                    {
                                        "status": "Berisi nutrisi",
                                        "volume": round(isi["tandon"], 2),
                                        "microcontrollerName": NAME,
                                    }
                                ),
                                qos=1,
                            ),
                        
                        print(
                            "Menyesuaikan ppm yang kurang dari ppm min (menambah nutrisi)\nPPM target {} - {}; actual {}".format(
                                ppm_min, ppm_max, EC_sensor.nilai
                            )
                        )

                    if time.time() - validasi_time >= 30 and not pompa_on:
                        GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.HIGH)
                        await asyncio.sleep(0.2)
                        GPIO.output(actuator["POMPA_NUTRISI"], GPIO.HIGH)
                        validasi_time = time.time()
                        pompa_on = True

                    elif time.time() - validasi_time >= 10 and pompa_on:
                        GPIO.output(actuator["POMPA_NUTRISI"], GPIO.LOW)
                        await asyncio.sleep(0.2)
                        GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.LOW)
                        validasi_time = time.time()
                        pompa_on = False

                
                GPIO.output(actuator["POMPA_NUTRISI"], GPIO.LOW)
                GPIO.output(actuator["RELAY_B"], GPIO.LOW)
                GPIO.output(actuator["RELAY_A"], GPIO.LOW)
                await asyncio.sleep(0.2)
                GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.LOW)
                GPIO.remove_event_detect(sensor["WATERFLOW_A"])
                GPIO.remove_event_detect(sensor["WATERFLOW_B"])
                debit.update("nutrisiA", 0)
                debit.update("nutrisiB", 0)
                status = True

            elif actual_ppm > ppm_max:
                # Ngitung air yang mau ditambahin
                # GPIO.add_event_detect(sensor["WATERFLOW_AIR"], GPIO.FALLING, callback=lambda channel: countPulse(
                #     channel, air_tambahan, actuator["RELAY_AIR"], sensor["WATERFLOW_AIR"], 'air'))
                # air_tambahan = (
                #     (
                #         (actual_ppm * konstanta["rasioAir"] / konstanta["ppm"])
                #         - (
                #             ((ppm_min + ppm_max) / 2)
                #             * konstanta["rasioAir"]
                #             / konstanta["ppm"]
                #         )
                #     )
                #     / 1000
                #     * volume
                # )
                # print(f"Air tambahan : {air_tambahan}")
                print("PPM berlebih, penambahan air dilakukan sampai PPM memenuhi")
                GPIO.add_event_detect(
                    sensor["WATERFLOW_AIR"],
                    GPIO.FALLING,
                    callback=lambda channel: countPulseManual(
                        channel,
                        actuator["RELAY_AIR"],
                        sensor["WATERFLOW_AIR"],
                        "air",
                    ),
                )
                GPIO.output(actuator["RELAY_AIR"], GPIO.HIGH)
                air_start = time.time()
                air_update = air_start
                logging_time = time.time()
                pompa_time = time.time()
                pompa_on = False

                while EC_sensor.nilai > ppm_max:
                    await asyncio.sleep(0.1)
                    if time.time() - logging_time >= 2.5:
                        if pompa_on:
                            MQTT.publish(
                                "iterahero2023/peracikan/info",
                                json.dumps(
                                    {
                                        "status": "Berisi nutrisi",
                                        "volume": round(isi["tandon"], 2),
                                        "microcontrollerName": NAME,
                                    }
                                ),
                                qos=1,
                            ),
                        print(
                            "Menyesuaikan ppm yang melebihi ppm maks (menambah air)\nPPM target {} - {}; actual {}".format(
                                ppm_min, ppm_max, EC_sensor.nilai
                            )
                        )

                    if time.time() - pompa_time >= 30 and not pompa_on:
                        GPIO.input(actuator["SOLENOID_VALIDASI"], GPIO.HIGH)
                        await asyncio.sleep(0.1)
                        GPIO.input(actuator["POMPA_NUTRISI"], GPIO.HIGH)
                        pompa_time = time.time()
                        pompa_on = True

                    elif time.time() - pompa_time >= 10 and pompa_on:
                        GPIO.input(actuator["POMPA_NUTRISI"], GPIO.LOW)
                        await asyncio.sleep(0.1)
                        GPIO.input(actuator["SOLENOID_VALIDASI"], GPIO.LOW)
                        pompa_time = time.time()
                        pompa_on = False

                GPIO.output(actuator["POMPA_NUTRISI"], GPIO.LOW)
                GPIO.output(actuator["RELAY_AIR"], GPIO.LOW)
                GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
                await asyncio.sleep(0.5)
                GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.LOW)
                debit.update("air", 0)
                status = True

    except KeyboardInterrupt as e:
        print(f"Validasi dihentikan {e}")
        raise KeyboardInterrupt("Validasi dihentikan paksa")
    
    except Exception as e:
        print(f"Error: {e}")
        raise Exception(f"Error {e}")
    
    finally:
        if validasi:
            elapsed_time = time.time() - validasi_start
            elapsed_min = int(elapsed_time // 60)
            elapsed_hr = int(elapsed_min // 60)
            elapsed_sec = round(elapsed_time % 60, 2)
            print(
                "{} menyesuaikan PPM\nTarget: {} - {}\tAktual: {}\nLama penyesuaian: {:02d}:{:02d}:{:.2f}s.".format(
                    'BERHASIL' if status else 'GAGAL', ppm_min, ppm_max, EC_sensor.nilai, elapsed_hr, elapsed_min, elapsed_sec
                )
            )
        else:
            print(">>> PPM memenuhi, tidak perlu penyesuaian <<<")


async def validasi_waterflow():
    reason = []
    await asyncio.sleep(5)
    if debit["air"] < 100 and not peracikan_state["airEnough"]:
        reason.append(sensor["WATERFLOW_AIR"])
    if debit["nutrisiA"] < 100 and not peracikan_state["nutrisiAEnough"]:
        reason.append(sensor["WATERFLOW_A"])
    if debit["nutrisiB"] < 100 and not peracikan_state["nutrisiBEnough"]:
        reason.append(sensor["WATERFLOW_B"])

    valid = not bool(len(reason))

    return valid, reason


async def peracikan(
    ph_min,
    ph_max,
    ppm_min,
    ppm_max,
    volume_air,
    volume_a,
    volume_b,
    konstanta,
    volume,
    resep,
):
    """
    Melakukan peracikan nutrisi
    args:
        ph_min: target nilai ph_min nutrisi
        ph_max: target nilai ph_max nutrisi
        ppm_min: target nilai ppm_min nutrisi
        ppm_max: target nilai ppm_max nutrisi
        volume_air: volume air yang dibutuhkan
        volume_a: volume nutrisi A yang dibutuhkan
        volume_b: volume nutrisi B yang dibutuhkan
        kosntanta: konstanta pupuk yang digunakan
        volume: volume total nutrisi yang dibuat
        resep: nama resep dari nutrisi yang dibuat
    """
    try:
        done = False
        peracikan_start = time.time()
        print(f"{datetime.datetime.now()} >>> Peracikan dimulai")
        GPIO.add_event_detect(
            sensor["WATERFLOW_AIR"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel,
                volume_air,
                actuator["RELAY_AIR"],
                sensor["WATERFLOW_AIR"],
                "air",
            ),
        )
        GPIO.add_event_detect(
            sensor["WATERFLOW_A"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel,
                volume_a,
                actuator["RELAY_A"],
                sensor["WATERFLOW_A"],
                "nutrisiA",
            ),
        )
        GPIO.add_event_detect(
            sensor["WATERFLOW_B"],
            GPIO.FALLING,
            callback=lambda channel: countPulse(
                channel,
                volume_b,
                actuator["RELAY_B"],
                sensor["WATERFLOW_B"],
                "nutrisiB",
            ),
        )

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

        valid, reason = await validasi_waterflow()
        if valid:
            relay_state = [
                {
                    str(actuator["MOTOR_MIXING"]): bool(
                        GPIO.input(actuator["MOTOR_MIXING"])
                    )
                },
                {str(actuator["RELAY_AIR"]): bool(GPIO.input(actuator["RELAY_AIR"]))},
                {str(actuator["RELAY_A"]): bool(GPIO.input(actuator["RELAY_A"]))},
                {str(actuator["RELAY_B"]): bool(GPIO.input(actuator["RELAY_B"]))},
                {
                    str(actuator["SOLENOID_DISTRIBUSI"]): bool(
                        GPIO.input(actuator["SOLENOID_DISTRIBUSI"])
                    )
                },
                {
                    str(actuator["SOLENOID_VALIDASI"]): bool(
                        GPIO.input(actuator["SOLENOID_VALIDASI"])
                    )
                },
                {
                    str(actuator["POMPA_NUTRISI"]): bool(
                        GPIO.input(actuator["POMPA_NUTRISI"])
                    )
                },
            ]

            await MQTT.publish(
                "iterahero2023/actuator",
                json.dumps({"actuator": relay_state, "microcontrollerName": NAME}),
                qos=1,
            )

            logging_time = time.time()
            # validasi = False
            mengaduk = False
            while (
                not (peracikan_state["airEnough"])
                or not (peracikan_state["nutrisiBEnough"])
                or not (peracikan_state["nutrisiAEnough"])
            ):
                if sum(sum_volume.values()) >= 0.50 * volume and not mengaduk:
                    GPIO.output(actuator["MOTOR_MIXING"], GPIO.HIGH)
                    mengaduk = True
                # if sum(sum_volume.values()) >= 0.75 * volume and not validasi:
                #     GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.HIGH)
                #     validasi = True
                #     await asyncio.sleep(1)
                #     GPIO.output(actuator["POMPA_NUTRISI"], GPIO.HIGH)
                if (time.time() - logging_time) >= 3:
                    await MQTT.publish(
                        "iterahero2023/peracikan/info",
                        json.dumps(
                            {
                                "status": f"Meracik {resep}",
                                "volume": round(isi["tandon"] + sum(sum_volume.values()), 2),
                                "microcontrollerName": NAME,
                            }
                        ),
                        qos=1,
                    )
                    print("Sedang melakukan peracikan {}...".format(resep))
                    logging_time = time.time()

            peracikan_state.update((key, False) for key in peracikan_state)
            GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
            GPIO.remove_event_detect(sensor["WATERFLOW_A"])
            GPIO.remove_event_detect(sensor["WATERFLOW_B"])
            
            kontrol_peracikan()

            # ppm_value, ph_value, temp_value = await asyncio.gather(
            #     EC_sensor.read_value(), pH_sensor.read_value(), temp_sensor.read_value()
            # )

            await asyncio.gather(
                validasi_ppm(ppm_min, ppm_max, EC_sensor.nilai, konstanta, volume),
                # validasi_ph(ph_min, ph_max, pH_sensor.nilai),
            )
            done = True
        else:
            await MQTT.publish(
                "iterahero2023/peracikan/log",
                json.dumps(
                    {
                        "mikrokontroler": NAME,
                        "status": "terminated",
                        "sensor": reason,
                    }
                ),
            )
            print(f"Peracikan gagal karena {[key for key, value in sensor.items() if value in reason]} bermasalah")

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

    except Exception as e:
        print(f"{datetime.datetime.now()} -> Error: {e}")

    finally:
        await MQTT.publish(
            "iterahero2023/peracikan/info",
            json.dumps(
                {
                    "status": f"Berisi pupuk {resep}",
                    "volume": round(isi["tandon"], 2),
                    "microcontrollerName": NAME,
                }
            ),
            qos=1,
        )

        await stop_peracikan()
        turn_off_actuator()
        elapsed_time = time.time() - peracikan_start
        elapsed_min = int(elapsed_time // 60)
        elapsed_hr = int(elapsed_min // 60)
        elapsed_sec = round(elapsed_time % 60, 2)
        print(
            ">>> Waktu yang dibutuhkan untuk melakukan peracikan adalah {:02d}:{:02d}:{:.2f}s.\nStatus: {}. <<<".format(
                elapsed_hr, elapsed_min, elapsed_sec, "Berhasil" if done else "Gagal"
            )
        )


async def count_distribusi_nutrisi():
    """
    Menghitung volume nutrisi yang terdistribusi untuk mengurangnya dengan isi tandon
    """
    global distribusi_start, distribusi_update
    while True:
        try:
            if GPIO.input(actuator["SOLENOID_DISTRIBUSI"]) == GPIO.HIGH:
                now = time.time()
                isi["tandon"] -= (now - distribusi_update) * 0.1
                distribusi_update = now
                await asyncio.sleep(1)

        except Exception as e:
            print(e)


async def volume_pompa_air():
    """
    Menghitung volume air yang mengisi tandon
    """
    global air_start, air_update
    while True:
        try:
            if GPIO.input(actuator["RELAY_AIR"]) == GPIO.HIGH:
                now = time.time()
                isi["tandon"] += (now - air_update) * 0.1
                air_update = now
                await asyncio.sleep(1)

        except Exception as e:
            print(e)


async def volume_pompa_A():
    """
    Menghitung volume A yang mengisi tandon
    """
    global a_start, a_update
    while True:
        try:
            if GPIO.input(actuator["RELAY_A"]) == GPIO.HIGH:
                now = time.time()
                isi["tandon"] += (now - a_update) * 0.1
                a_update = now
                await asyncio.sleep(1)

        except Exception as e:
            print(e)


async def volume_pompa_B():
    """
    Menghitung volume nutrisi B yang mengisi tandon
    """
    global b_start, b_update
    while True:
        try:
            if GPIO.input(actuator["RELAY_B"]) == GPIO.HIGH:
                now = time.time()
                isi["tandon"] += (now - b_update) * 0.1
                b_update = now
                await asyncio.sleep(1)

        except Exception as e:
            print(e)


def on_off_actuator(pin):
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    state = GPIO.input(pin)
    if not state:
        if pin == actuator["POMPA_NUTRISI"] and (
            (not GPIO.input(actuator["SOLENOID_DISTRIBUSI"]))
            or (not GPIO.input(actuator["SOLENOID_VALIDASI"]))
        ):
            GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.HIGH)
            # GPIO.output(actuator["SOLENOID_DISTRIBUSI"], GPIO.HIGH)
        elif pin == actuator["RELAY_AIR"]:
            GPIO.add_event_detect(
                sensor["WATERFLOW_AIR"],
                GPIO.FALLING,
                callback=lambda channel: countPulseManual(
                    channel,
                    actuator["RELAY_AIR"],
                    sensor["WATERFLOW_AIR"],
                    "air",
                ),
            )
            air_start = time.time()
            air_update = air_start

        elif pin == actuator["RELAY_A"]:
            GPIO.add_event_detect(
                sensor["WATERFLOW_A"],
                GPIO.FALLING,
                callback=lambda channel: countPulseManual(
                    channel,
                    actuator["RELAY_A"],
                    sensor["WATERFLOW_A"],
                    "nutrisiA",
                ),
            )
            a_start = time.time()
            a_update = a_start

        elif pin == actuator["RELAY_B"]:
            GPIO.add_event_detect(
                sensor["WATERFLOW_B"],
                GPIO.FALLING,
                callback=lambda channel: countPulseManual(
                    channel,
                    actuator["RELAY_B"],
                    sensor["WATERFLOW_B"],
                    "nutrisiB",
                ),
            )
            b_start = time.time()
            b_update = b_start
    else:
        if pin == actuator["RELAY_AIR"]:
            GPIO.remove_event_detect(sensor["WATERFLOW_AIR"])
            debit.update({"air": 0})
        elif pin == actuator["RELAY_A"]:
            GPIO.remove_event_detect(sensor["WATERFLOW_A"])
            debit.update({"nutrisiA": 0})
        elif pin == actuator["RELAY_B"]:
            GPIO.remove_event_detect(sensor["WATERFLOW_B"])
            debit.update({"nurtisiB": 0})

        elif pin == actuator["SOLENOID_DISTRIBUSI"]:
            if GPIO.input(actuator["POMPA_NUTRISI"]) and not GPIO.input(
                actuator["SOLENOID_VALIDASI"]
            ):
                GPIO.output(actuator["POMPA_NUTRISI"], GPIO.LOW)

        elif pin == actuator["SOLENOID_VALIDASI"]:
            if GPIO.input(actuator["POMPA_NUTRISI"]) and not GPIO.input(
                actuator["SOLENOID_DISTRIBUSI"]
            ):
                GPIO.output(actuator["POMPA_NUTRISI"], GPIO.LOW)

    GPIO.output(pin, not (state))
    if pin == actuator["SOLENOID_DISTRIBUSI"] and not state:
        GPIO.output(actuator["POMPA_NUTRISI"], GPIO.HIGH)
        distribusi_start = time.time()
        distribusi_update = distribusi_start
    if pin == actuator["SOLENOID_VALIDASI"] and not state:
        GPIO.output(actuator["POMPA_NUTRISI"], GPIO.HIGH)
    if pin == actuator["POMPA_NUTRISI"] and state:
        GPIO.output(actuator["SOLENOID_DISTRIBUSI"], GPIO.LOW)
        GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.LOW)

    print(f"{pin} Mati" if state else f"{pin} Nyala")


async def publish_sensor():
    try:
        ph_value = pH_sensor.nilai if pH_sensor.nilai > 0 else 0
        ppm_value = EC_sensor.nilai if EC_sensor.nilai > 0 else 0
        temp_value = temp_sensor.nilai if temp_sensor.nilai > 0 else 0
        temp_value = round(random.uniform(29, 31), 2)
        temp_value = 28
        now = datetime.datetime.now()
        print(f"{now}:\tSuhu Larutan: {temp_value}\tPPM Larutan: {ppm_value}\tpH Larutan: {ph_value}")

        debit_air = (
            (debit["air"] / 378) / (time.time() - air_start) if debit["air"] > 0 else 0
        )
        debit_a = (
            (debit["nutrisiA"] / 378) / (time.time() - a_start)
            if debit["nutrisiA"] > 0
            else 0
        )
        debit_b = (
            (debit["nutrisiB"] / 378) / (time.time() - b_start)
            if debit["nutrisiB"] > 0
            else 0
        )

        await MQTT.publish(
            "iterahero2023/info/sensor",
            json.dumps(
                {
                    "microcontrollerName": NAME,
                    "sensor_adc": [
                        {str(sensor_adc[0]): ph_value},
                        {str(sensor_adc[1]): ppm_value},
                    ],
                    "sensor_non_adc": [
                        {str(sensor_non_adc[0]): temp_value},
                        {str(sensor_non_adc[1]): round(debit_air, 3)},
                        {str(sensor_non_adc[2]): round(debit_a, 3)},
                        {str(sensor_non_adc[3]): round(debit_b, 3)},
                    ],
                }
            ),
            qos=1,
        )

    except (asyncio.CancelledError, KeyboardInterrupt):
        print("Publish Sensor dihentikan")

    except Exception as e:
        print(e)


async def find_serial_port():
    while True:
        ports = serial.tools.list_ports.comports()
        for port, desc, hwid in sorted(ports):
            if "USB" in desc:
                return port
        print("ESP tidak terhubung ke Raspi")
        await asyncio.sleep(1)


async def readSensor():
    global ESP_ser
    port = await find_serial_port()
    ESP_ser = serial.Serial(port, 115200)
    ESP_ser.reset_input_buffer()

    lastPubTime = time.time()

    while True:
        try:
            if ESP_ser.in_waiting > 0:
                data = ESP_ser.readline().decode("utf-8").strip()
                json_data = json.loads(data)

                if "info" in json_data:
                    temp_sensor.update(round(json_data["info"]["temperature"]))
                    pH_sensor.update(round(json_data["info"]["ph"], 2))
                    EC_sensor.update(round(json_data["info"]["ppm"], 3))

            currentTime = time.time()
            if currentTime - lastPubTime >= 2:
                await publish_sensor()
                lastPubTime = time.time()

        except json.JSONDecodeError as e:
            print(f"Gagal memparsing json : {e}")
            continue

        except UnicodeDecodeError as e:
            print(f"Error decoding data: {e}")
            continue

        except KeyError:
            print(f"Key yang diperlukan tidak ditemukan")
            continue

        except KeyboardInterrupt as e:
            print(f"Pembacaan sensor dihentikan")
            break

        except Exception as e:
            print(e)


async def publish_actuator(halt=False):
    while True and not halt:
        try:
            data = []
            for key, value in actuator.items():
                data.append({value: GPIO.input(value)})
            await MQTT.publish(
                "iterahero2023/info/aktuator",
                json.dumps({"aktuator": data, "microcontrollerName": NAME}),
                qos=1,
            )
            await asyncio.sleep(1)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Publish Aktuator dihentikan {e}")
            break

        except Exception as e:
            print(e)

    if halt:
        data = []
        for key, value in actuator.items():
            data.append({value: GPIO.input(value)})
        await MQTT.publish(
            "iterahero2023/info/aktuator",
            json.dumps({"aktuator": data, "microcontrollerName": NAME}),
            qos=1,
        )


async def publish_status():
    while True:
        try:
            await MQTT.publish(
                "iterahero2023/mikrokontroller/status",
                json.dumps({"mikrokontroler": NAME, "status": 1}),
                qos=1,
            )
            await asyncio.sleep(1)

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            print(f"Publish Status mikrokontroller dihentikan {e}")
            break

        except Exception as e:
            print(e)


async def timerActuator(pin, duration):
    global distribusi_start, distribusi_update, air_start, air_update, a_start, a_update, b_start, b_update
    state = GPIO.input(pin)
    if state:
        print("Udah nyala")
    else:
        if pin == actuator["SOLENOID_DISTRIBUSI"]:
            distribusi_start = time.time()
            distribusi_update = distribusi_start
        elif pin == actuator["RELAY_AIR"]:
            air_start = time.time()
            air_update = air_start
        elif pin == actuator["RELAY_A"]:
            a_start = time.time()
            a_update = a_start
        elif pin == actuator["RELAY_B"]:
            b_start = time.time()
            b_update = b_start

        if pin == actuator["POMPA_NUTRISI"] and (not GPIO.input(actuator["SOLENOID_DISTRIBUSI"]) or not GPIO.input(actuator["SOLENOID_VALIDASI"])):
            GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.HIGH)
            GPIO.output(actuator["SOLENOID_DISTRIBUSI"], GPIO.HIGH)

        GPIO.output(pin, GPIO.HIGH)  # Nyala
        print("Nyala")
        await asyncio.sleep(duration * 60)
        GPIO.output(pin, GPIO.LOW)  # Mati
        if pin == actuator["POMPA_NUTRISI"]:
            GPIO.output(actuator["SOLENOID_DISTRIBUSI"], GPIO.LOW)
            GPIO.output(actuator["SOLENOID_VALIDASI"], GPIO.LOW)


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
    will = Will(
        "iterahero2023/mikrokontroller/status",
        json.dumps({"mikrokontroler": NAME, "status": 0}),
        qos=1,
        retain=True,
    )
    MQTT = aiomqtt.Client(config["mqtt_broker_public"], 1883, will=will)

    while True:
        try:
            async with MQTT:
                try:
                    print("MQTT Ready")
                    await asyncio.sleep(0.2)
                    await MQTT.subscribe("iterahero2023/#")
                    asyncio.gather(
                        readSensor(),
                        publish_actuator(),
                        publish_status(),
                        # count_distribusi_nutrisi(),
                        # volume_pompa_air(),
                        # volume_pompa_A(),
                        # volume_pompa_B(),
                    )

                    async for message in MQTT.messages:
                        data = json.loads(message.payload)
                        if message.topic.matches("iterahero2023/automation"):
                            if data["microcontroller"] == NAME:
                                if data["pin"] and "durasi" in data:
                                    timerActuator(data["pin"], data["durasi"])
                                elif data["pin"]:
                                    on_off_actuator(data["pin"])
                        if message.topic.matches("iterahero2023/kontrol"):
                            if data["pin"] and data["microcontroller"] == NAME:
                                on_off_actuator(data["pin"])
                        if message.topic.matches("iterahero2023/waterflow"):
                            asyncio.create_task(
                                test_waterflow(data["volume"], data["cairan"])
                            )
                        if message.topic.matches("iterahero2023/tandon/volume"):
                            if data["mikrokontroler"] == NAME:
                                isi["tandon"] = data["volume"]
                        if (
                            message.topic.matches("iterahero2023/peracikan")
                            and data["konstanta"]["aktuator"][0]["microcontroller"][
                                "name"
                            ]
                            == NAME
                        ):
                            x = check_peracikan()
                            if x:
                                print("Masih ada peracikan yang berjalan")
                            else:
                                komposisi = data["komposisi"]
                                volume = komposisi["volume"]
                                ph_min = komposisi["ph_min"]
                                ph_max = komposisi["ph_max"]
                                ppm_min = komposisi["ppm_min"]  
                                ppm_max = komposisi["ppm_max"]
                                resep = komposisi["nama"]
                                konstanta = data["konstanta"]
                                print(konstanta)
                                nutrisiA = round(
                                    ((ppm_min + ppm_max) / 2)
                                    / konstanta["ppm"]
                                    * konstanta["rasioA"]
                                    * volume
                                    / 1000,
                                    3,
                                )
                                nutrisiB = round(
                                    ((ppm_min + ppm_max) / 2)
                                    / konstanta["ppm"]
                                    * konstanta["rasioB"]
                                    * volume
                                    / 1000,
                                    3,
                                )
                                air = volume - (nutrisiA + nutrisiB)

                                # Print value variabel
                                checkVAR(locals())

                                asyncio.create_task(
                                    peracikan(
                                        ph_min,
                                        ph_max,
                                        ppm_min,
                                        ppm_max,
                                        air,
                                        nutrisiA,
                                        nutrisiB,
                                        konstanta,
                                        volume,
                                        resep,
                                    )
                                )
                        if (
                            message.topic.matches("iterahero2023/peracikan/cancel")
                            and data["microcontroller"] == NAME
                        ):
                            if check_peracikan():
                                stop_peracikan()
                                turn_off_actuator()

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
        pH_sensor = SensorADC(
            "Sensor pH DF Robot", "1000 * voltage / 820 / 200 * 1.45", 0, "ph"
        )
        EC_sensor = SensorADC(
            "Sensor EC DF Robot", "y = (0.043x + 13.663) - 60", 1, "ec"
        )
        temp_sensor = SensorSuhu("Sensor Suhu DS18B20", "y = x - 1.63", 15)
        waterflow_air = SensorWaterflow(
            name="Waterflow Air",
            persamaan="y = (x / 378) - (time_now - time_start)",
            gpio=sensor["WATERFLOW_AIR"],
            pulse=378,
        )
        waterflow_a = SensorWaterflow(
            name="Waterflow A",
            persamaan="y = (x / 378) - (time_now - time_start)",
            gpio=sensor["WATERFLOW_A"],
            pulse=378,
        )
        waterflow_b = SensorWaterflow(
            name="Waterflow B",
            persamaan="y = (x / 378) - (time_now - time_start)",
            gpio=sensor["WATERFLOW_B"],
            pulse=378,
        )

        sensor_adc = [pH_sensor.channel, EC_sensor.channel]
        sensor_non_adc = [
            temp_sensor.GPIO,
            waterflow_air.GPIO,
            waterflow_a.GPIO,
            waterflow_b.GPIO,
        ]

        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        print(f"{e}")

        loop.run_until_complete(
            MQTT.publish(
                "iterahero2023/peracikan/info",
                json.dumps(
                    {
                        "status": "Berisi nutrisi",
                        "volume": round(isi["tandon"], 2),
                        "microcontrollerName": NAME,
                    }
                ),
                qos=1,
            )
        )

        if check_peracikan():
            loop.run_until_complete(stop_peracikan())
        else:
            print("Sistem Dihentikan")

        turn_off_actuator()
        loop.run_until_complete(publish_actuator(halt=True))

    except Exception as e:
        print(e)

    finally:
        loop.run_until_complete(
            MQTT.publish(
                "iterahero2023/peracikan/info",
                json.dumps(
                    {
                        "status": "Berisi nutrisi",
                        "volume": round(isi["tandon"], 2),
                        "microcontrollerName": NAME,
                    }
                ),
                qos=1,
            )
        )

        if check_peracikan():
            loop.run_until_complete(stop_peracikan())
        else:
            print("Sistem Dihentikan")

        turn_off_actuator()
        loop.run_until_complete(publish_actuator(halt=True))
        GPIO.cleanup()
        sys.exit()