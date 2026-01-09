#!/bin/bash

# Piper TTS Setup for Ubuntu
echo "[INFO] Setting up Piper TTS for Ubuntu..."

# Create piper directory
mkdir -p ./piper
cd ./piper

# Download Piper binary for Linux
echo "[INFO] Downloading Piper binary..."
wget -O piper.tar.gz "https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz"
tar -xzf piper.tar.gz
mv piper_amd64/piper ./piper
chmod +x ./piper

# Download Kannada model
echo "[INFO] Downloading Kannada model..."
wget -O kn_IN-female-medium.onnx "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/kn/kn_IN/female/medium/kn_IN-female-medium.onnx"
wget -O kn_IN-female-medium.onnx.json "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/kn/kn_IN/female/medium/kn_IN-female-medium.onnx.json"

# Cleanup
rm -rf piper_amd64 piper.tar.gz

echo "[INFO] Piper TTS setup complete!"
echo "[INFO] Test with: echo 'ಶುಭಮ್ ಟೋನ್ಡ್' | ./piper/piper --model ./piper/kn_IN-female-medium.onnx --length_scale 0.6 --output_file test.wav && aplay test.wav"