#!/bin/bash
set -e

MODE="${1:-server}"

case "$MODE" in
    server)
        echo "[preprocessor] Starting FastAPI server on :7860"
        exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 7860
        ;;
    batch)
        shift
        echo "[preprocessor] Running batch mode"
        exec python3 -m app.batch "$@"
        ;;
    shell)
        echo "[preprocessor] Interactive shell"
        exec /bin/bash
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Usage: entrypoint.sh [server|batch|shell]"
        echo "  server              - Start FastAPI on :7860 (default)"
        echo "  batch --input X --output Y  - Process video and exit"
        echo "  shell               - Interactive bash"
        exit 1
        ;;
esac
