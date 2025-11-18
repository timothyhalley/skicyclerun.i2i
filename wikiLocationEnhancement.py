#!/usr/bin/env python3
import argparse
import json
import requests

def fetch_wikipedia_summary(page_title: str) -> str:
    """Fetch summary text from Wikipedia API given a page title."""
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}"
    resp = requests.get(url)
    if resp.status_code == 200:
        data = resp.json()
        return data.get("extract", "")
    else:
        return f"Failed to fetch Wikipedia summary for {page_title}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-store", required=True, help="Path to JSON input file")
    args = parser.parse_args()

    # Load JSON
    with open(args.master_store, "r") as f:
        data = json.load(f)

    # Get the first entry (dict key)
    first_key = next(iter(data))
    entry = data[first_key]

    # Use extratags.wikipedia if available
    wiki_tag = entry.get("extratags", {}).get("wikipedia")
    if wiki_tag:
        # Wikipedia tag is like "en:Washington Mews"
        page_title = wiki_tag.split(":")[-1]
        summary = fetch_wikipedia_summary(page_title)
        entry["wiki_summary"] = summary

    # Save back to file
    with open(args.master_store, "w") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    main()