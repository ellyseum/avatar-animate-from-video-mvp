#!/bin/bash
# RunPod startup: set up SMPL models, start Xvfb, launch Express

SMPL_TARGET="/opt/frankmocap/extra_data/smpl"
SMPL_SOURCE="/app/smpl"

# Ensure SMPL models are in place
if [ ! -f "$SMPL_TARGET/SMPLX_NEUTRAL.pkl" ]; then
    echo "[start] Linking SMPL models..."
    mkdir -p "$(dirname "$SMPL_TARGET")"
    rm -rf "$SMPL_TARGET"
    ln -sf "$SMPL_SOURCE" "$SMPL_TARGET"
    echo "[start] SMPL models linked"
else
    echo "[start] SMPL models already present"
fi

# Start virtual framebuffer for headless rendering (FrankMocap + Blender)
Xvfb :99 -screen 0 1280x1024x24 &>/dev/null &

# Launch Express
exec node server/index.js
