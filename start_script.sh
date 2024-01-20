#!/bin/bash

while true; do
    if iwconfig wlan0 | grep -q "ESSID:off/any"; then
        echo "WiFi connection not established yet. Retrying in 3 seconds..."
        sleep 3
    else
        echo "WiFi connection established."
        break
    fi
done

# Pindah ke direktori skrip Python
cd /home/iterahero2023/iterahero2023/

/usr/bin/python3 main.py & sleep 4

# Hentikan proses yang sedang berjalan
sudo pkill -f 'main.py'

# Tunggu sebentar untuk memastikan proses sebelumnya berhenti
sleep 1

# Jalankan skrip Python
/usr/bin/python3 main.py  > peracikan.log 2>&1
