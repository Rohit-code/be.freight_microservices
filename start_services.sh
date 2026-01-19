#!/bin/bash

# Start all microservices

echo "Starting Freight Forwarder Microservices..."

# Start Authentication Service
echo "Starting Authentication Service on port 8001..."
cd authentication
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload &
AUTH_PID=$!
cd ..

# Start Constants Service
echo "Starting Constants Service on port 8002..."
cd constants
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload &
CONSTANTS_PID=$!
cd ..

# Start AI Service
echo "Starting AI Service on port 8003..."
cd ai_service
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload &
AI_PID=$!
cd ..

# Start Vector DB Service
echo "Starting Vector DB Service on port 8004..."
cd vector_db
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload &
VECTOR_PID=$!
cd ..

# Start Email Service
echo "Starting Email Service on port 8005..."
cd email_service
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload &
EMAIL_PID=$!
cd ..

# Start User Service
echo "Starting User Service on port 8006..."
cd user_service
uvicorn app.main:app --host 0.0.0.0 --port 8006 --reload &
USER_PID=$!
cd ..

# Wait a bit for services to start
sleep 2

# Start API Gateway
echo "Starting API Gateway on port 8000..."
cd api_gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
GATEWAY_PID=$!
cd ..

echo ""
echo "All services started!"
echo "API Gateway: http://localhost:8000"
echo "Authentication: http://localhost:8001"
echo "Constants: http://localhost:8002"
echo "AI Service: http://localhost:8003"
echo "Vector DB Service: http://localhost:8004"
echo "Email Service: http://localhost:8005"
echo "User Service: http://localhost:8006"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for user interrupt
trap "kill $AUTH_PID $CONSTANTS_PID $AI_PID $VECTOR_PID $EMAIL_PID $USER_PID $GATEWAY_PID; exit" INT TERM
wait
