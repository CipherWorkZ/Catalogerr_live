#!/bin/bash
set -e

cd "$(dirname "$0")"

# Start main.py in background and capture its logs
python3 main.py > main.log 2>&1 &
MAIN_PID=$!

echo "🚀 Starting Flask server (PID $MAIN_PID)..."

# Wait until we see the "Running on" line in the logs
until grep -q "Running on http://127.0.0.1:8006" main.log; do
  sleep 1
done

echo "✅ Flask server is up."

# Run admin.py
echo "⚙️  Running admin.py..."
python3 admin.py

# Notify user
echo "🎉 Server is ready! You can access it at:"
grep "Running on http" main.log

# Kill the background Flask (so it doesn’t block next run)
kill $MAIN_PID
wait $MAIN_PID 2>/dev/null || true

echo "🛑 Init Flask process stopped. Container will now exit."
