"""End-to-end test: fetch → submit → status via localhost HTTPS server."""

import pytest
from click.testing import CliRunner

from mograder.cli import cli
from mograder.transport.https_server import run_server_background


@pytest.fixture()
def course_server(tmp_path):
    """Set up a course directory with a server and assignment files."""
    # Server root
    server_root = tmp_path / "server"
    hw1_files = server_root / "hw1" / "files"
    hw1_files.mkdir(parents=True)
    (hw1_files / "homework.py").write_text("# HW1 starter\nprint('hello')\n")

    srv, thread = run_server_background(server_root, port=0)
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    # Student working directory
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    (course_dir / "mograder.toml").write_text(
        f'transport = "https"\n\n[https]\nurl = "{base_url}"\n'
    )

    yield base_url, course_dir, server_root
    srv.shutdown()


class TestE2EStudentWorkflow:
    def test_https_fetch_list(self, course_server, monkeypatch):
        base_url, course_dir, _ = course_server
        monkeypatch.chdir(course_dir)
        runner = CliRunner()
        result = runner.invoke(cli, ["https", "fetch", "--list", "--url", base_url])
        assert result.exit_code == 0, result.output
        assert "hw1" in result.output

    def test_https_fetch_downloads(self, course_server, monkeypatch):
        base_url, course_dir, _ = course_server
        monkeypatch.chdir(course_dir)
        out_dir = course_dir / "hw1"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["https", "fetch", "hw1", "--url", base_url, "-o", str(out_dir)],
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "homework.py").exists()
        assert "starter" in (out_dir / "homework.py").read_text()

    def test_https_submit(self, course_server, monkeypatch):
        base_url, course_dir, server_root = course_server
        monkeypatch.chdir(course_dir)

        # Create student solution
        sol = course_dir / "solution.py"
        sol.write_text("print('my answer')\n")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "https",
                "submit",
                "hw1",
                str(sol),
                "--url",
                base_url,
                "--token",
                "alice:fake",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Submitted" in result.output
        assert (server_root / "hw1" / "alice.py").exists()

    def test_https_feedback_after_submit(self, course_server, monkeypatch):
        base_url, course_dir, server_root = course_server
        monkeypatch.chdir(course_dir)

        # Submit first
        sol = course_dir / "solution.py"
        sol.write_text("print('my answer')\n")
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "https",
                "submit",
                "hw1",
                str(sol),
                "--url",
                base_url,
                "--token",
                "alice:fake",
            ],
        )

        # Check status
        result = runner.invoke(
            cli,
            ["https", "feedback", "hw1", "--url", base_url, "--token", "alice:fake"],
        )
        assert result.exit_code == 0, result.output
        assert "submitted" in result.output

    def test_full_workflow(self, course_server, monkeypatch):
        """Full cycle: fetch → submit → status."""
        base_url, course_dir, server_root = course_server
        monkeypatch.chdir(course_dir)
        runner = CliRunner()

        # 1. Fetch
        out_dir = course_dir / "hw1"
        result = runner.invoke(
            cli, ["https", "fetch", "hw1", "--url", base_url, "-o", str(out_dir)]
        )
        assert result.exit_code == 0, result.output
        assert (out_dir / "homework.py").exists()

        # 2. Submit
        result = runner.invoke(
            cli,
            [
                "https",
                "submit",
                "hw1",
                str(out_dir / "homework.py"),
                "--url",
                base_url,
                "--token",
                "alice:fake",
            ],
        )
        assert result.exit_code == 0, result.output

        # 3. Check status
        result = runner.invoke(
            cli,
            ["https", "feedback", "hw1", "--url", base_url, "--token", "alice:fake"],
        )
        assert result.exit_code == 0, result.output
        assert "submitted" in result.output

        # 4. Instructor fetches submissions
        sub_dir = course_dir / "submissions"
        result = runner.invoke(
            cli,
            [
                "https",
                "fetch-submissions",
                "hw1",
                "--url",
                base_url,
                "-o",
                str(sub_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (sub_dir / "alice.py").exists()
