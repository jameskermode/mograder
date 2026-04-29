#!/usr/bin/env bash
# Build a pre-populated course directory for the grader demo.
# Run from the repo root: bash demo/setup_grader_demo.sh
set -e

# Resolve to absolute paths so subshells (cd) work.
# Use cd+pwd instead of realpath to avoid resolving symlinks —
# realpath on a venv python follows the symlink to the base
# interpreter, losing the venv's site-packages.
_resolve() { (cd "$(dirname "$1")" && echo "$(pwd)/$(basename "$1")"); }
PYTHON="$(_resolve "${PYTHON:-$(command -v python)}")"
MOGRADER="$(_resolve "${MOGRADER:-$(command -v mograder)}")"

COURSE=demo/grader-course

echo "=== Cleaning up ==="
rm -rf "$COURSE" examples/submitted examples/autograded examples/feedback \
       examples/gradebook.db examples/gradebook.db-shm examples/gradebook.db-wal \
       examples/moodle_worksheet.csv

echo "=== Generating spoof submissions ==="
$PYTHON examples/generate_spoof.py

echo "=== Autograding demo-holistic ==="
$MOGRADER autograde examples/submitted/demo-holistic/*.py \
  --source examples/source/demo-holistic/demo-holistic.py --jobs 1

echo "=== Autograding demo-assignment ==="
$MOGRADER autograde examples/submitted/demo-assignment/*.py \
  --source examples/source/demo-assignment/demo-assignment.py --jobs 1

echo "=== Simulating marker grading ==="
$PYTHON examples/generate_spoof.py --postprocess

echo "=== Exporting feedback ==="
$MOGRADER feedback examples/autograded/demo-holistic/*.py
$MOGRADER feedback examples/autograded/demo-assignment/*.py

echo "=== Assembling course directory ==="
mkdir -p "$COURSE/import"

cat > "$COURSE/mograder.toml" << 'TOML'
transport = "https"

[https]
url = "https://mograder-demo.jrkermode.uk"

[[assignments]]
name = "demo-assignment"
dir = "demo-assignment"

[[assignments]]
name = "demo-holistic"
dir = "demo-holistic"

[defaults]
no_edit = true
# Single-worker autograde — Oracle free-tier mini host (954 MB, no swap)
# can't sustain the default 4 parallel marimo exports without OOM.
jobs = 1

[rlimits]
cpu = 60
nproc = 128
nofile = 128
# 2 GiB virtual-address-space cap.  Values below ~1 GiB silently hang
# ``marimo export`` (Python + numpy + marimo reserve ~1 GiB of VM just to
# import).  For real RSS limits, set ``[security] use_bubblewrap = true``.
as = 2147483648

[hub]
session_ttl = 300
TOML
cp -r examples/source "$COURSE/"
cp -r examples/release "$COURSE/"
cp -r examples/submitted "$COURSE/"
cp -r examples/autograded "$COURSE/"
cp -r examples/feedback "$COURSE/"
cp examples/gradebook.db "$COURSE/"
cp examples/moodle_worksheet.csv "$COURSE/import/demo-assignment.csv"

echo "=== Importing student names ==="
"$PYTHON" -c "
from mograder.grading.gradebook import Gradebook
from mograder.transport.moodle import read_moodle_worksheet
_, rows = read_moodle_worksheet('$COURSE/import/demo-assignment.csv')
mapping = {r['Username']: r['Full name'] for r in rows if r.get('Username')}
with Gradebook('$COURSE/gradebook.db') as gb:
    gb.upsert_students(mapping)
print(f'Imported {len(mapping)} students')
"

# Generate release notebooks with submit cell for hub deployment
SUBMIT_URL="https://mograder-demo.jrkermode.uk"
echo "=== Generating release notebooks with submit cell ==="
$MOGRADER generate \
    examples/source/demo-assignment/demo-assignment.py \
    examples/source/demo-holistic/demo-holistic.py \
    --submit-url "$SUBMIT_URL" \
    -o "$COURSE/release" --no-validate

# Copy auxiliary notebooks from demo/course (lectures, workshops)
if [ -d demo/course ]; then
    for d in demo/course/*/; do
        name=$(basename "$d")
        # Skip assignments (generated above) and workshops (encrypted separately)
        case "$name" in *assignment*|*holistic*|*workshop*) continue ;; esac
        mkdir -p "$COURSE/source/$name" "$COURSE/release/$name"
        cp "$d"/files/*.py "$COURSE/source/$name/" 2>/dev/null || true
        cp "$d"/files/*.py "$COURSE/release/$name/" 2>/dev/null || true
    done
fi

# Create release zips for directories that don't have one yet
for d in "$COURSE/release"/*/; do
    name=$(basename "$d")
    if [ ! -f "$d/$name.zip" ]; then
        (cd "$d" && zip -q "$name.zip" *.py)
        echo "ZIP: $d$name.zip"
    fi
done

# Publish release notebooks for hub demo and build shared venvs
echo "=== Publishing hub assignments ==="
for d in "$COURSE/release"/*/; do
    name=$(basename "$d")
    mkdir -p "$COURSE/hub-release/$name"
    cp "$d"/*.py "$COURSE/hub-release/$name/" 2>/dev/null || true
done
# Encrypt and publish workshop notebooks for hub
echo "=== Publishing hub workshops ==="
if [ -d demo/course ]; then
    for d in demo/course/*/; do
        name=$(basename "$d")
        case "$name" in *workshop*)
            src=$(ls "$d"/files/*.py 2>/dev/null | head -1)
            if [ -n "$src" ]; then
                $MOGRADER workshop encrypt "$src" -o "$COURSE/hub-release/$name" \
                    --salt mograder --keys-url "/workshop/$name/keys.json"
            fi
        ;; esac
    done
fi

echo "=== Publishing hub lectures ==="
if [ -d demo/course ]; then
    for d in demo/course/*/; do
        name=$(basename "$d")
        case "$name" in *lecture*)
            src=$(ls "$d"/files/*.py 2>/dev/null | head -1)
            if [ -n "$src" ]; then
                $MOGRADER generate --lecture "$src" -o "$COURSE/release"
                # Copy release to hub-release
                mkdir -p "$COURSE/hub-release/$name"
                cp "$COURSE/release/$name"/* "$COURSE/hub-release/$name/" 2>/dev/null || true
                # Create manifest with lecture type
                $PYTHON -c "
import json
from pathlib import Path
d = Path('$COURSE/hub-release/$name')
files = sorted(f.name for f in d.iterdir() if f.is_file() and not f.name.startswith('.') and f.name != 'files.json')
(d / 'files.json').write_text(json.dumps({'files': files, 'type': 'lecture'}, indent=2))
print(f'  Published lecture: $name ({len(files)} files)')
"
            fi
        ;; esac
    done
fi

echo "=== Warming hub cache ==="
$MOGRADER hub -C "$COURSE" warm-cache --all

echo "=== Done ==="
echo "Course directory: $COURSE"
ls -la "$COURSE"
