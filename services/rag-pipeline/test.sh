#!/bin/bash

# Configuration
HOST="http://localhost:1416"
INDEX_NAME="hello"
TOP_K=5

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to make a single RAG query request
make_rag_request() {
    local question=$1
    local request_id=$2
    local start_time=$(date +%s.%N)
    
    echo -e "${BLUE}[Request $request_id] Starting: $question${NC}"
    
    response=$(curl -s -X POST "$HOST/rag_query/run" \
        -H "accept: application/json" \
        -H "Content-Type: application/json" \
        -d "{
            \"question\": \"$question\",
            \"top_k\": $TOP_K,
            \"conversation_history\": [],
            \"index_name\": \"$INDEX_NAME\"
        }")
    
    local end_time=$(date +%s.%N)
    local duration=$(echo "$end_time - $start_time" | bc)
    
    # Extract success status and answer (using jq if available, otherwise grep)
    if command -v jq &> /dev/null; then
        success=$(echo "$response" | jq -r '.success')
        answer=$(echo "$response" | jq -r '.answer' | head -c 100)
    else
        success=$(echo "$response" | grep -o '"success":[^,}]*' | cut -d':' -f2)
        answer=$(echo "$response" | grep -o '"answer":"[^"]*' | cut -d'"' -f4 | head -c 100)
    fi
    
    if [ "$success" = "true" ]; then
        echo -e "${GREEN}[Request $request_id] ✓ Completed in ${duration}s${NC}"
        echo -e "${GREEN}[Request $request_id] Answer preview: ${answer}...${NC}"
    else
        echo -e "${RED}[Request $request_id] ✗ Failed after ${duration}s${NC}"
        echo -e "${RED}[Request $request_id] Error: $response${NC}"
    fi
}

# Function to make a chat completion request (streaming)
make_chat_request() {
    local content=$1
    local request_id=$2
    local custom_id="test-$request_id-$(date +%s)"
    local start_time=$(date +%s.%N)
    
    echo -e "${BLUE}[Chat $request_id] Starting: $content${NC}"
    
    # Use curl with streaming output
    response=$(curl -s -N -X POST "$HOST/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"rag_query\",
            \"messages\": [
                {\"role\": \"user\", \"content\": \"$content\"}
            ],
            \"index_name\": \"$INDEX_NAME\",
            \"temperature\": 0.7,
            \"max_tokens\": 500,
            \"top_k\": $TOP_K,
            \"custom_id\": \"$custom_id\",
            \"stream\": true
        }" 2>&1 | head -c 500)  # Limit output for readability
    
    local end_time=$(date +%s.%N)
    local duration=$(echo "$end_time - $start_time" | bc)
    
    echo -e "${GREEN}[Chat $request_id] ✓ Completed in ${duration}s${NC}"
    echo -e "${GREEN}[Chat $request_id] Response preview: ${response:0:100}...${NC}"
}

# Test scenarios
echo -e "${YELLOW}=== Concurrent RAG Pipeline Test ===${NC}"
echo -e "${YELLOW}Host: $HOST${NC}"
echo -e "${YELLOW}Index: $INDEX_NAME${NC}"
echo -e "${YELLOW}Top K: $TOP_K${NC}"
echo ""

# Test 1: Multiple concurrent RAG queries
echo -e "${YELLOW}Test 1: Launching 5 concurrent RAG queries...${NC}"

# Launch requests in background
make_chat_request "What are the main topics discussed?" 1 &
make_chat_request "Can you summarize the key points?" 2 &
make_chat_request "What decisions were made?" 3 &
make_chat_request "Who are the participants mentioned?" 4 &
make_chat_request "What are the action items?" 5 &

# Wait for all background jobs to complete
wait
echo ""
