#!/usr/bin/env bash
set -e

MARKER="/app/.initialized"

if [ ! -f "$MARKER" ]; then
    echo "📦 First run detected: installing requirements..."
    pip install --no-cache-dir -r requirements.txt
    
    echo "⚙️ Running init.sh..."
    bash /app/init.sh

    # Mark init as complete
    touch "$MARKER"

    echo "✅ Init complete. Exiting so container can be restarted..."
    exit 0
fi

echo "🚀 Starting main app..."
exec python3 main.py
