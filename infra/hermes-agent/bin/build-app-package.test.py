#!/usr/bin/env python3
import importlib.util, os, subprocess, sys, tarfile, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("build_app_package", os.path.join(HERE, "build-app-package.py"))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)

REG = """version: 1

projects:
  app:
    workdir: /projects/app
    mutate_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - mutator
    package:
      include:
        - notes.md
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True).stdout.decode().strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, "init", "-q")
        os.makedirs(os.path.join(self.repo, "code"))
        for rel, body in (("code/mutator.py", "m\n"), ("notes.md", "n\n"),
                          ("code/not_listed.py", "x\n"), ("report.md", "client data\n")):
            with open(os.path.join(self.repo, rel), "w") as f:
                f.write(body)
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "c1")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        d = tempfile.mkdtemp(); self.projects = os.path.join(d, "projects.yaml")
        with open(self.projects, "w") as f:
            f.write(REG)


class TestBuild(Base):
    def test_contains_exactly_the_registry_list(self):
        out = B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())
        with tarfile.open(out["package"]) as tar:
            self.assertEqual(sorted(m.name for m in tar.getmembers()), ["code/mutator.py", "notes.md"])

    def test_reproducible(self):
        a = B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())
        b = B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())
        self.assertEqual(a["sha256"], b["sha256"])
        with open(a["package"], "rb") as fa, open(b["package"], "rb") as fb:
            self.assertEqual(fa.read(), fb.read())

    def test_refuses_a_commit_that_is_not_head(self):
        with open(os.path.join(self.repo, "notes.md"), "a") as f:
            f.write("more\n")
        git(self.repo, "commit", "-qam", "c2")
        with self.assertRaisesRegex(ValueError, "HEAD is"):
            B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())

    def test_refuses_modified_tracked_files(self):
        with open(os.path.join(self.repo, "code/mutator.py"), "a") as f:
            f.write("dirty\n")
        with self.assertRaisesRegex(ValueError, "modified"):
            B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())

    def test_untracked_files_do_not_block(self):
        with open(os.path.join(self.repo, "audit_data.json"), "w") as f:
            f.write("{}")
        B.build("app", self.repo, self.commit, self.projects, tempfile.mkdtemp())   # no raise

    def test_refuses_a_short_commit(self):
        with self.assertRaisesRegex(ValueError, "40-hex"):
            B.build("app", self.repo, self.commit[:12], self.projects, tempfile.mkdtemp())


class TestRefuseClientIds(unittest.TestCase):
    def test_doc_with_customer_id_is_refused(self):
        import package_lib as PK
        with self.assertRaises(ValueError) as cm:
            PK.refuse_client_ids({"campaigns.md": b"ok", "google-ads-audit.md": b"Account 676-497-7319"})
        self.assertIn("google-ads-audit.md", str(cm.exception))
        self.assertNotIn("676", str(cm.exception))

    def test_undashed_id_is_refused(self):
        import package_lib as PK
        with self.assertRaises(ValueError):
            PK.refuse_client_ids({"x.md": b"cid 6764977319 here"})

    def test_long_digit_runs_are_refused_without_naming_them(self):
        import package_lib as PK
        for name, body in (("a.md", b"campaign 23892569751"), ("b.md", b"ad group 238925697512")):
            with self.assertRaises(ValueError) as cm:
                PK.refuse_client_ids({name: body, "ok.md": b"CPL 120"})
            self.assertIn(name, str(cm.exception))
            self.assertNotIn("2389256975", str(cm.exception))

    def test_code_files_are_not_scanned_and_clean_docs_pass(self):
        import package_lib as PK
        PK.refuse_client_ids({"code/a.py": b"MCC = 4518110176", "dental-benchmarks.md": b"CPL $120-$250"})


if __name__ == "__main__":
    unittest.main()
