#!/bin/bash

# Start all microservices

echo "Starting Freight Forwarder Microservices..."

# Start Authentication Service
echo "Starting Authentication Service on port 8001..."
cd authentication
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload --log-level info &
AUTH_PID=$!
cd ..
sleep 3  # Give authentication service more time to start (it needs DB connection)

# Start Constants Service
echo "Starting Constants Service on port 8002..."
cd constants
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload --log-level warning &
CONSTANTS_PID=$!
cd ..

# Start AI Service
echo "Starting AI Service on port 8003..."
cd ai_service
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload --log-level warning &
AI_PID=$!
cd ..

# Start Vector DB Service
echo "Starting Vector DB Service on port 8004..."
cd vector_db
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload --log-level warning &
VECTOR_PID=$!
cd ..

# Start Email Service
echo "Starting Email Service on port 8005..."
cd email_service
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload --log-level warning &
EMAIL_PID=$!
cd ..

# Start User Service
echo "Starting User Service on port 8006..."
cd user_service
uvicorn app.main:app --host 0.0.0.0 --port 8006 --reload --log-level warning &
USER_PID=$!
cd ..

# Start Order Service (orders + tracking; used by gateway and customer portal)
echo "Starting Order Service on port 8015..."
cd order_service
uvicorn app.main:app --host 0.0.0.0 --port 8015 --reload --log-level warning &
ORDER_PID=$!
cd ..

# Start Customer Service (customers + portal login; used by gateway)
echo "Starting Customer Service on port 8016..."
cd customer_service
uvicorn app.main:app --host 0.0.0.0 --port 8016 --reload --log-level warning &
CUSTOMER_PID=$!
cd ..

# Start Knowledge Graph Service (must be before Rate Sheet Service and Orchestrator)
echo "Starting Knowledge Graph Service on port 8011..."
cd knowledge_graph_service
uvicorn app.main:app --host 0.0.0.0 --port 8011 --reload --log-level warning &
GRAPH_PID=$!
cd ..

# Start Intent Classifier Service (must be before Orchestrator)
echo "Starting Intent Classifier Service on port 8012..."
cd intent_classifier_service
uvicorn app.main:app --host 0.0.0.0 --port 8012 --reload --log-level warning &
INTENT_PID=$!
cd ..

# Start Orchestrator Service (depends on Intent Classifier, Graph, Vector, SQL services)
echo "Starting Orchestrator Service on port 8013..."
cd orchestrator_service
uvicorn app.main:app --host 0.0.0.0 --port 8013 --reload --log-level warning &
ORCHESTRATOR_PID=$!
cd ..

# Start Decision Engine (called by Rate Sheet Service)
echo "Starting Decision Engine on port 8014..."
cd decision_engine
uvicorn app.main:app --host 0.0.0.0 --port 8014 --reload --log-level warning &
DECISION_PID=$!
cd ..

# Give the agentic services time to start
sleep 2

# Start Rate Sheet Service (depends on Orchestrator, Decision Engine, Knowledge Graph)
echo "Starting Rate Sheet Service on port 8010..."
cd rate_sheet_service
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload --log-level warning &
RATE_SHEET_PID=$!
cd ..

# Wait a bit for services to start (already waited for auth service)
sleep 2

# Start API Gateway
echo "Starting API Gateway on port 8000..."
cd api_gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --log-level warning &
GATEWAY_PID=$!
cd ..

echo ""
echo "All services started!"
echo ""
echo "=== Core Services ==="
echo "API Gateway: http://localhost:8000"
echo "Authentication: http://localhost:8001"
echo "Constants: http://localhost:8002"
echo "AI Service: http://localhost:8003"
echo "Vector DB Service: http://localhost:8004"
echo "Email Service: http://localhost:8005"
echo "User Service: http://localhost:8006"
echo "Order Service: http://localhost:8015"
echo "Customer Service: http://localhost:8016"
echo "Rate Sheet Service: http://localhost:8010"
echo ""
echo "=== New Architecture Services ==="
echo "Knowledge Graph Service: http://localhost:8011"
echo "Intent Classifier Service: http://localhost:8012"
echo "Orchestrator Service: http://localhost:8013"
echo "Decision Engine: http://localhost:8014"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for user interrupt
trap "kill $AUTH_PID $CONSTANTS_PID $AI_PID $VECTOR_PID $EMAIL_PID $USER_PID $ORDER_PID $CUSTOMER_PID $RATE_SHEET_PID $GRAPH_PID $INTENT_PID $ORCHESTRATOR_PID $DECISION_PID $GATEWAY_PID; exit" INT TERM
wait
