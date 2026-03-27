#!/usr/bin/env bash
# Build a pre-populated course directory for the formgrader demo.
# Run from the repo root: bash demo/setup_formgrader_demo.sh
set -e

# Resolve to absolute paths so subshells (cd) work.
# Use cd+pwd instead of realpath to avoid resolving symlinks —
# realpath on a venv python follows the symlink to the base
# interpreter, losing the venv's site-packages.
_resolve() { (cd "$(dirname "$1")" && echo "$(pwd)/$(basename "$1")"); }
PYTHON="$(_resolve "${PYTHON:-$(command -v python)}")"
MOGRADER="$(_resolve "${MOGRADER:-$(command -v mograder)}")"

COURSE=demo/formgrader-course

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
[defaults]
no_edit = true
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
from mograder.gradebook import Gradebook
from mograder.moodle import read_moodle_worksheet
_, rows = read_moodle_worksheet('$COURSE/import/demo-assignment.csv')
mapping = {r['Username']: r['Full name'] for r in rows if r.get('Username')}
with Gradebook('$COURSE/gradebook.db') as gb:
    gb.upsert_students(mapping)
print(f'Imported {len(mapping)} students')
"

# Copy source and release notebooks from demo/course if available
if [ -d demo/course ]; then
    for d in demo/course/*/; do
        name=$(basename "$d")
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

echo "=== Done ==="
echo "Course directory: $COURSE"
ls -la "$COURSE"
