"""
Package the XGuard Dify plugin into a .difypkg file.
Usage: python package.py
"""
import os
import zipfile

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_NAME = "xguard"

EXCLUDE_DIRS = {"__pycache__", ".git", "server", ".idea"}
EXCLUDE_FILES = {"package.py", ".env"}
EXCLUDE_EXTENSIONS = {".pyc", ".difypkg"}


def should_include(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts:
        if part in EXCLUDE_DIRS:
            return False
        if part.startswith(".") and not part.startswith("_"):
            return False
    filename = parts[-1]
    if filename in EXCLUDE_FILES:
        return False
    _, ext = os.path.splitext(filename)
    if ext in EXCLUDE_EXTENSIONS:
        return False
    return True


def main():
    output_path = os.path.join(PLUGIN_DIR, f"{PLUGIN_NAME}.difypkg")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PLUGIN_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS
                       and not (d.startswith(".") and not d.startswith("_"))]
            for filename in files:
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, PLUGIN_DIR)
                if should_include(rel_path):
                    zf.write(filepath, rel_path)
                    print(f"  + {rel_path}")

    print(f"\nPackaged: {output_path}")
    print(f"Size: {os.path.getsize(output_path)} bytes")


if __name__ == "__main__":
    main()
