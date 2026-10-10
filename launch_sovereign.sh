#!/bin/bash
echo "[SOVEREIGN]: Igniting full-stack production telemetry pipeline..."

# 1. Clear any ghost connections holding port 5005
fuser -k 5005/udp 2>/dev/null

# 2. Fire up the data transmitter loop silently in the background
python3 simulation_transmitter.py &

# 3. Fire up the core ingestion database receiver silently in the background
python3 core_receiver.py &

# 4. Launch the live visual telemetry web dashboard panel
echo "[SOVEREIGN]: Deploying frontend browser panel..."
streamlit run app_dashboard.py