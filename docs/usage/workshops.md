# Workshop Notebooks with Encrypted Solutions

For formative workshops (ungraded, deployed as WASM on GitHub Pages), mograder supports encrypted solutions with two reveal mechanisms:

- **Auto-reveal on check pass** — when a student's `check()` passes and they've entered the workshop key, the model solution appears automatically below the check result
- **Instructor release** — the instructor can release solutions progressively during a live workshop via `keys.json`; students click "Check for released solutions" to fetch them

The workshop key is a secret shared verbally by the instructor during the session. It is not stored in the generated notebook (only a SHA-256 hash is embedded), so students cannot extract solutions from the source code.

## 1. Author a source notebook

Create a source notebook with a `# === MOGRADER: EXERCISES ===` cell listing exercise keys, alongside regular `### BEGIN/END SOLUTION` markers, `check()` calls, and optionally `hint()` for progressive hints:

```python
# === MOGRADER: EXERCISES ===
_exercises = ["Q1", "Q2"]
```

## 2. Generate the workshop notebook

Encrypts solutions, strips them, and injects solution-reveal cells. The command prints the workshop key for the instructor to share verbally:

```bash
mograder workshop encrypt source/workshop/workshop.py -o release/workshop/ --salt mykey
# Workshop key (share with students verbally): mykey
```

## 3. Export for WASM deployment

Generates HTML + keys.json for GitHub Pages:

```bash
mograder workshop export source/workshop/workshop.py -o dist/workshop/ --salt mykey
```

## 4. Release solutions during a live workshop

Incrementally reveal solutions by adding decryption keys to `keys.json`:

```bash
mograder workshop release-key dist/workshop/keys.json Q1 --salt mykey
```

Students click "Check for released solutions" in the notebook to fetch updated keys. Released solutions appear regardless of whether checks pass or the workshop key has been entered. To release all solutions at once, copy `keys_all.json` over `keys.json`.

## 5. Serve locally with an instructor dashboard

For live workshops, serve the exported directory with a built-in instructor dashboard for releasing solutions in real time:

```bash
mograder workshop serve dist/workshop/ --salt mykey
```

This starts a local server and prints two URLs: one for students (the WASM notebook) and one for the instructor (a dashboard to release solutions incrementally). The instructor dashboard URL includes a randomly generated secret token.
