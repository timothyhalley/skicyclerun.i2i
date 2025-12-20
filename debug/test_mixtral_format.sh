#!/bin/bash
# Test if mixtral:8x7b can follow format instructions

echo "Testing mixtral:8x7b with format instructions..."
curl -s http://localhost:11434/api/generate -d '{
  "model": "mixtral:8x7b",
  "prompt": "Output exactly two sections:\n\nTRAVEL BLOG: Write one sentence about a sunset.\n\nSUMMARY: Write one sentence about clouds.\n\nDO NOT explain your thinking. OUTPUT ONLY THE TWO SECTIONS ABOVE.",
  "stream": false,
  "options": {
    "temperature": 0.7,
    "num_predict": 200
  }
}' | python3 -c "import sys, json; resp = json.load(sys.stdin); print(resp['response'])"
