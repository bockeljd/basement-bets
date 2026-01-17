#!/bin/bash

# 0. Load Environment Variables
if [ -f .env ]; then
    echo "Loading .env file..."
    export $(cat .env | grep -v '^#' | xargs)
fi

# 1. Start Backend
echo "Starting FastAPI Backend..."
# Run in background
PYTHONPATH=./src python3 -m uvicorn src.api:app --reload --port 8000 &
BACKEND_PID=$!

# 2. Start Frontend
echo "Starting React Frontend..."
cd client
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi
npm run dev &
FRONTEND_PID=$!

# Trap Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT

# Wait
wait
