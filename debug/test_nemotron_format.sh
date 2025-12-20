#!/bin/bash
# Test if nemotron-3-nano:30b can follow format instructions

curl -s http://localhost:11434/api/generate -d '{
  "model": "nemotron-3-nano:30b",
  "prompt": "Output exactly two sections:\n\nTRAVEL BLOG: Write one sentence about a sunset.\n\nSUMMARY: Write one sentence about clouds.\n\nDO NOT explain your thinking. OUTPUT ONLY THE TWO SECTIONS ABOVE.",
  "stream": false,
  "options": {
    "temperature": 0.5,
    "num_predict": 200
  }
}' | python3 -c "import sys, json; print(json.load(sys.stdin)['response'])"
