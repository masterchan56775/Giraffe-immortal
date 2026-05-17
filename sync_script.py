import shutil
import os

src_dir = r"d:\program\py\2"
dest_dir = os.path.join(r"d:\program\py", "Giraffe-immortal")

print(f"Syncing from {src_dir} to {dest_dir}...")

def sync_directories(src, dest):
    if not os.path.exists(dest):
        os.makedirs(dest)
        
    for item in os.listdir(src):
        # 忽略不需要同步的目录或文件
        if item in ['.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'sync_script.py']:
            continue
            
        s = os.path.join(src, item)
        d = os.path.join(dest, item)
        
        if os.path.isdir(s):
            print(f"Copying directory: {s} -> {d}")
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            print(f"Copying file: {s} -> {d}")
            shutil.copy2(s, d)

if __name__ == "__main__":
    try:
        sync_directories(src_dir, dest_dir)
        print("Sync complete!")
    except Exception as e:
        print(f"Error during sync: {e}")
