import os

BASE_DIR = os.getcwd()
OUTPUT_FILE = "clean_snapshot.txt"

# Core files to always include fully
CORE_FILES = {
    "backend/app.py",
    "backend/audio_splitter.py",
    "backend/requirements.txt",
    "frontend/src/api.js",
    "frontend/src/App.jsx",
    "frontend/src/main.jsx",
    "frontend/src/index.css",
    "frontend/src/components/Navbar.jsx",
    "frontend/src/components/Hero.jsx",
    "frontend/src/components/UploadForm.jsx",
    "frontend/src/components/Faq.jsx",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/tailwind.config.js",
    "frontend/postcss.config.js",
    "INSTRUCTIONS.md",
    "packages_list.txt",
    ".env"
}

# Folders to show but NOT list contents
SKIP_LISTING = {
    os.path.join("backend", "logs"),
    os.path.join("backend", "temp"),
    os.path.join("backend", "uploads"),
    os.path.join("tests", "reports")
}

IGNORE_DIRS = {"node_modules", "venv", "__pycache__"}

with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
    out.write("# 📂 Project Structure\n")

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        rel_root = os.path.relpath(root, BASE_DIR)

        out.write(f"\n# 📁 {rel_root}\n")

        if any(rel_root.startswith(skip) for skip in SKIP_LISTING):
            out.write("  [Contents skipped]\n")
            continue

        for file in files:
            rel_path = os.path.normpath(os.path.join(rel_root, file))
            rel_path_unix = rel_path.replace("\\", "/")

            if rel_path_unix in CORE_FILES:
                out.write(f"\n## 📄 {rel_path_unix}\n")
                try:
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        out.write(f.read())
                except:
                    out.write("[Unreadable file]")
                out.write("\n" + "-"*60 + "\n")
            else:
                out.write(f"  {file}\n")

print(f"✅ Clean snapshot created: {OUTPUT_FILE}")
