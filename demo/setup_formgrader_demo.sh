#!/usr/bin/env bash
# Build a pre-populated course directory for the formgrader demo.
# Run from the repo root: bash demo/setup_formgrader_demo.sh
set -e

# Resolve to absolute paths so subshells (cd) work
PYTHON="$(realpath "${PYTHON:-$(command -v python)}")"
MOGRADER="$(realpath "${MOGRADER:-$(command -v mograder)}")"

COURSE=demo/formgrader-course

echo "=== Cleaning up ==="
rm -rf "$COURSE" examples/submitted examples/autograded examples/feedback \
       examples/gradebook.db examples/gradebook.db-shm examples/gradebook.db-wal \
       examples/moodle_worksheet.csv

echo "=== Generating spoof submissions ==="
$PYTHON examples/generate_spoof.py

echo "=== Autograding demo-holistic ==="
$MOGRADER autograde examples/submitted/demo-holistic/*.py \
  --source examples/source/demo-holistic/demo-holistic.py

echo "=== Autograding demo-assignment ==="
$MOGRADER autograde examples/submitted/demo-assignment/*.py \
  --source examples/source/demo-assignment/demo-assignment.py

echo "=== Simulating GTA grading ==="
$PYTHON examples/generate_spoof.py --postprocess

echo "=== Exporting feedback ==="
$MOGRADER feedback examples/autograded/demo-holistic/*.py
$MOGRADER feedback examples/autograded/demo-assignment/*.py

echo "=== Assembling course directory ==="
mkdir -p "$COURSE/import"

cat > "$COURSE/mograder.toml" << 'TOML'
[defaults]
no_edit = true
no_actions = true
TOML
cp -r examples/source "$COURSE/"
cp -r examples/release "$COURSE/"
cp -r examples/submitted "$COURSE/"
cp -r examples/autograded "$COURSE/"
cp -r examples/feedback "$COURSE/"
cp examples/gradebook.db "$COURSE/"
cp examples/moodle_worksheet.csv "$COURSE/import/demo-assignment.csv"

echo "=== Importing student names ==="
(cd "$COURSE" && $MOGRADER import-students import/demo-assignment.csv)

# Copy release notebooks with submit cells from demo/course if available
if [ -d demo/course ]; then
    for d in demo/course/*/; do
        name=$(basename "$d")
        if [ -d "$COURSE/release/$name" ]; then
            cp "$d"/*.py "$COURSE/release/$name/" 2>/dev/null || true
        fi
    done
fi

echo "=== Done ==="
echo "Course directory: $COURSE"
ls -la "$COURSE"
