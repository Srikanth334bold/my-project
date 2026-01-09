#!/usr/bin/bash
cd ~/project/Bamul_Final/poc
source venv/bin/activate

nohup python3 logger1.py --conveyor 1 --port 5001 > tray_counter_1.log 2>&1 &

nohup python3 logger1.py --conveyor 2 --port 5002 > tray_counter_2.log 2>&1 &

nohup python3 logger1.py --conveyor 3 --port 5003 > tray_counter_3.log 2>&1 &

nohup python3 logger1.py --conveyor 4 --port 5004 > tray_counter_4.log 2>&1 &

nohup python3 logger1.py --conveyor 5 --port 5005 > tray_counter_5.log 2>&1 &

echo "All conveyor counters started"