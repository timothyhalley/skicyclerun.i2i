import os
import shutil

# Source and destination paths
src_dir = "/Users/timothyhalley/.cache/huggingface"
dst_dir = "/Volumes/MySSD/huggingface"

# Ensure destination exists
os.makedirs(dst_dir, exist_ok=True)

for root, dirs, files in os.walk(src_dir):
    for d in dirs:
        src_path = os.path.join(root, d)
        dst_path = os.path.join(dst_dir, d)

        # Only move if destination does not already exist
        if not os.path.exists(dst_path):
            print(f"Moving {src_path} -> {dst_path}")
            shutil.move(src_path, dst_path)
        else:
            print(f"Skipping {src_path}, already exists at destination.")