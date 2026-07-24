import os, sqlite3, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "persist-review-proposal.py")


def _make_kanban_db(path, *, title="synthesize", status="done",
                    body="MODE: synthesis. Project: claude_code.",
                    result=None, run_summary=None, run_metadata=None):
    """Build a minimal kanban.db matching the columns read_content_db queries."""
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, result TEXT,"
        " status TEXT, completed_at INTEGER, created_at INTEGER);"
        "CREATE TABLE task_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,"
        " summary TEXT, metadata TEXT, status TEXT, outcome TEXT,"
        " ended_at INTEGER, started_at INTEGER);"
    )
    conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
                 ("t_syn", title, body, result, status, 100, 50))
    if run_summary is not None or run_metadata is not None:
        conn.execute("INSERT INTO task_runs (task_id, summary, metadata, status, outcome,"
                     " ended_at, started_at) VALUES (?,?,?,?,?,?,?)",
                     ("t_syn", run_summary, run_metadata, "done", "completed", 100, 60))
    conn.commit()
    conn.close()


class TestPersist(unittest.TestCase):
    def test_persists_content_via_save_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            cf = os.path.join(d, "content.md")
            with open(cf, "w") as f:
                f.write("# Improvement proposal\n## Summary\nteam review.\n")
            env = {**os.environ, "PROPOSALS_DIR": d}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code",
                                "--content-file", cf], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            written = r.stdout.strip()
            self.assertTrue(written.startswith(os.path.join(d, "claude_code") + os.sep), written)
            with open(written) as f:
                self.assertIn("team review.", f.read())

    def test_missing_content_file_fails(self):
        r = subprocess.run([sys.executable, SCRIPT, "--project", "p",
                            "--content-file", "/no/such"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_retrieves_from_db_result_field(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "kanban.db")
            _make_kanban_db(db, result="# Improvement proposal\n## Summary\nfrom result field.\n")
            env = {**os.environ, "PROPOSALS_DIR": d, "HERMES_KANBAN_DB": db}
            r = subprocess.run([sys.executable, SCRIPT, "--project", "claude_code"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            written = r.stdout.strip()
            self.assertTrue(written.startswith(os.path.join(d, "claude_code") + os.sep), written)
            with open(written) as f:
                self.assertIn("from result field.", f.read())


if __name__ == "__main__":
    unittest.main()
