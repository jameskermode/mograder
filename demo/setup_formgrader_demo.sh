#!/usr/bin/env bash
# Build a pre-populated course directory for the formgrader demo.
# Run from the repo root: bash demo/setup_formgrader_demo.sh
set -e

COURSE=demo/formgrader-course

echo "=== Cleaning up ==="
rm -rf "$COURSE" examples/submitted examples/autograded examples/feedback \
       examples/gradebook.db examples/gradebook.db-shm examples/gradebook.db-wal \
       examples/moodle_worksheet.csv

echo "=== Generating spoof submissions ==="
${PYTHON:-python} examples/generate_spoof.py

echo "=== Autograding demo-holistic ==="
${MOGRADER:-mograder} autograde examples/submitted/demo-holistic/*.py \
  --source examples/source/demo-holistic/demo-holistic.py

echo "=== Autograding demo-assignment ==="
${MOGRADER:-mograder} autograde examples/submitted/demo-assignment/*.py \
  --source examples/source/demo-assignment/demo-assignment.py

echo "=== Simulating GTA grading ==="
${PYTHON:-python} examples/generate_spoof.py --postprocess

echo "=== Exporting feedback ==="
${MOGRADER:-mograder} feedback examples/autograded/demo-holistic/*.py
${MOGRADER:-mograder} feedback examples/autograded/demo-assignment/*.py

echo "=== Assembling course directory ==="
mkdir -p "$COURSE/import"
cp -r examples/source "$COURSE/"
cp -r examples/release "$COURSE/"
cp -r examples/submitted "$COURSE/"
cp -r examples/autograded "$COURSE/"
cp -r examples/feedback "$COURSE/"
cp examples/gradebook.db "$COURSE/"
cp examples/moodle_worksheet.csv "$COURSE/import/demo-assignment.csv"

echo "=== Importing student names ==="
(cd "$COURSE" && ${MOGRADER:-mograder} import-students import/demo-assignment.csv)

echo "=== Restructuring release for assignment server ==="
# Assignment server expects: <assignment>/files/<file>.py
for d in "$COURSE"/release/*/; do
    name=$(basename "$d")
    mkdir -p "$d/files"
    mv "$d"/*.py "$d/files/" 2>/dev/null || true
done

# Copy release notebooks with submit cells from demo/course if available
if [ -d demo/course ]; then
    for d in demo/course/*/; do
        name=$(basename "$d")
        if [ -d "$d/files" ]; then
            cp "$d"/files/*.py "$COURSE/release/$name/files/" 2>/dev/null || true
        fi
    done
fi

echo "=== Done ==="
echo "Course directory: $COURSE"
ls -la "$COURSE"
