#!/usr/bin/env bash
# Stands in for a simulation, recording which machine it ran on
set -euo pipefail
mkdir -p data/simulation
echo "t,u" > data/simulation/results.csv
for i in $(seq 0 100); do
  awk -v t="$i" 'BEGIN { print t "," sin(t / 10) }' \
    >> data/simulation/results.csv
done
hostname > data/simulation/host.txt
