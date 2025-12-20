#!/usr/bin/env python3
"""
Simple Vision Analysis Test Script
Tests Ollama vision models with a single image
"""
import argparse
from pathlib import Path
from ollama import chat


def main():
    parser = argparse.ArgumentParser(description='Test vision model analysis on an image')
    parser.add_argument('--image_path', required=True, help='Path to image file')
    parser.add_argument('--model', default='llava:7b', help='Vision model to use (default: llava:7b)')
    parser.add_argument('--prompt', default=None, 
                       help='Prompt to send to the model (default: read from test_vision_analysis_prompt.txt)')
    
    args = parser.parse_args()
    
    # Load prompt from file if not provided
    if args.prompt is None:
        prompt_file = Path(__file__).parent / 'test_vision_analysis_prompt.txt'
        if prompt_file.exists():
            args.prompt = prompt_file.read_text().strip()
            print(f"📄 Using prompt from: {prompt_file.name}")
        else:
            args.prompt = 'What is in this image? Be concise.'
            print(f"⚠️  Prompt file not found, using default")
    
    # Verify image exists
    image_path = Path(args.image_path)
    if not image_path.exists():
        print(f"❌ Error: Image not found: {image_path}")
        return 1
    
    print(f"🖼️  Image: {image_path.name}")
    print(f"🤖 Model: {args.model}")
    print("\n💬 Prompt:")
    print("-" * 80)
    print(args.prompt)
    print("-" * 80)
    
    # Call vision model
    try:
        response = chat(
            model=args.model,
            messages=[
                {
                    'role': 'user',
                    'content': args.prompt,
                    'images': [str(image_path)],
                }
            ],
        )
        
        print("\n📝 Response:")
        print(response.message.content)
        print()
        
    except Exception as e:
        print(f"❌ Error calling model: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
