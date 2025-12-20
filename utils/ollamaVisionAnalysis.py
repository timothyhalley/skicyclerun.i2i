#!/usr/bin/env python3
import argparse
import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

def query_ollama(model: str, prompt: str, image_path: str) -> str:
    """Send prompt + image to Ollama model."""
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_path]  # Ollama supports local image paths
    }
    resp = requests.post(OLLAMA_URL, json=payload, stream=True)
    description = ""
    for line in resp.iter_lines():
        if line:
            chunk = json.loads(line.decode("utf-8"))
            description += chunk.get("response", "")
    return description.strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-store", required=True, help="Path to JSON input file")
    parser.add_argument("--model", default="llava", help="Ollama vision model name")
    args = parser.parse_args()

    # Load JSON
    with open(args.master_store, "r") as f:
        data = json.load(f)

    # Iterate over image entries
    for key, entry in data.items():
        if "file_path" in entry and "location" in entry:
            wiki_summary = entry.get("location", {}).get("wiki_summary", "")
            image_path = entry["file_path"]

            # Build prompt
            prompt = f"Based on the following Wikipedia context:\n{wiki_summary}\n\n" \
                     f"Describe the scene in the photo {image_path}, " \
                     f"enhancing with historical and cultural reflections."

            description = query_ollama(args.model, prompt, image_path)
            entry["location_model_detail"] = description

    # Save back to file
    with open(args.master_store, "w") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    main()