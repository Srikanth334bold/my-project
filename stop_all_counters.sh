#!/usr/bin/bash

echo "Stopping all conveyor counters..."

ps -eaf | grep logger1.py | grep -v grep | awk '{print $2}' | xargs kill

ps -eaf | grep responsive_table_test.py | grep -v grep | awk '{print $2}' | xargs kill

ps -eaf | grep loggers1.py | grep -v grep | awk '{print $2}' | xargs kill

echo "All conveyor counters stopped"