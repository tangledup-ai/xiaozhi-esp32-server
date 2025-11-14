#!/usr/bin/env bash
#########################################################################
#  🧠  Run Script for Xiaozhi ESP32 stack
#  Starts Docker containers, Spring Boot API, Python server, and Web UI
#########################################################################

# Exit the script if any command fails
set -e

# ===================================================================== #
#  1️⃣  Start Docker containers (Database + Redis)
# ===================================================================== #
echo "🐳 Starting Docker containers..."
docker start xiaozhi-esp32-server-db
docker start xiaozhi-esp32-server-redis
echo "✅ Docker containers started."
echo

# ===================================================================== #
#  2️⃣  Define directories
# ===================================================================== #
API_DIR=~/projects/work/xiaozhi-esp32-server/main/manager-api
SERVER_DIR=~/projects/work/xiaozhi-esp32-server/main/xiaozhi-server
WEB_DIR=~/projects/work/xiaozhi-esp32-server/main/manager-web
CONDA_INIT_PATH=/home/smith/miniforge3/etc/profile.d/conda.sh

# ===================================================================== #
#  3️⃣  Define log directory
# ===================================================================== #
LOG_DIR=~/projects/work/xiaozhi-esp32-server/logs
mkdir -p "$LOG_DIR"

API_LOG="$LOG_DIR/manager-api.log"
SERVER_LOG="$LOG_DIR/xiaozhi-server.log"
WEB_LOG="$LOG_DIR/manager-web.log"

# ===================================================================== #
#  4️⃣  Graceful shutdown handler
# ===================================================================== #
cleanup() {
  echo -e "\n🧹 Stopping all running services..."
  pkill -P $$
  wait
  echo "✅ All services stopped."
}
trap cleanup EXIT

echo "🚀 Starting all backend/frontend services..."
echo

# ===================================================================== #
#  6️⃣  Start Web frontend (Vue / React etc.)
# ===================================================================== #
(
  cd "$WEB_DIR"
  echo "▶️  Starting Manager Web (npm)..."
  npm run serve > "$WEB_LOG" 2>&1
) &

# ===================================================================== #
#  5️⃣  Start Spring Boot service (Manager API)
# ===================================================================== #
(
  cd "$API_DIR"
  echo "▶️  Starting Manager API (Spring Boot)..."
  mvn spring-boot:run > "$API_LOG" 2>&1
) &

# ===================================================================== #
#  7️⃣  Start Python backend (Xiaozhi server)
# ===================================================================== #
#(
#  cd "$SERVER_DIR"
#  source "$CONDA_INIT_PATH"
#  conda activate xiaozhi
#  echo "▶️  Starting Xiaozhi Python Server..."
#  python app.py > "$SERVER_LOG" 2>&1
#) &

# ===================================================================== #
#  8️⃣  Wait for all background processes to finish
# ===================================================================== #
wait

