#!/bin/bash

sleep 10

# Pindahkan ke direktori skrip Python
cd /home/iterahero2023/iterahero2023/

/usr/bin/python3 main.py & sleep 4

# Hentikan proses yang sedang berjalan (jika ada)
sudo pkill -f 'main.py'

# Tunggu sebentar untuk memastikan proses sebelumnya berhenti
sleep 1

# Jalankan skrip Python
/usr/bin/python3 main.py > peracikan.log 2>&1
