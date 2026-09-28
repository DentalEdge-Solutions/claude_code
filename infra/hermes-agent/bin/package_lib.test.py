#!/usr/bin/env python3
import io, json, os, sys, tarfile, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import package_lib as PK
import package_testutil as T

REG = """version: 1

projects:
  app:
    workdir: /projects/app
    read_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - reader_one
        - reader_two
    mutate_execute:
      runner: /bin/true
      script_dir: code
      allow:
        - mutator
      caps:
        actions_per_changeset: 1
    package:
      include:
        - notes.md
"""

FILES = {"code/mutator.py": b"print('m')\n", "code/reader_one.py": b"r1\n",
         "code/reader_two.py": b"r2\n", "notes.md": b"# notes\n"}


class TestFileList(unittest.TestCase):
    def test_derived_from_both_allow_lists_plus_include(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "projects.yaml")
        with open(p, "w") as f:
            f.write(REG)
        self.assertEqual(PK.package_file_list(p, "app"), sorted(FILES))

    def test_nothing_declared_refuses(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "projects.yaml")
        with open(p, "w") as f:
            f.write("version: 1\n\nprojects:\n  app:\n    workdir: /x\n")
        with self.assertRaisesRegex(ValueError, "nothing to package"):
            PK.package_file_list(p, "app")


class TestManifest(unittest.TestCase):
    def test_hash_is_stable_and_order_independent(self):
        a = PK.build_manifest("app", "repo", "c" * 40, FILES)
        b = PK.build_manifest("app", "repo", "c" * 40, dict(reversed(list(FILES.items()))))
        self.assertEqual(PK.manifest_hash(a), PK.manifest_hash(b))

    def test_one_byte_changes_the_hash(self):
        a = PK.build_manifest("app", "repo", "c" * 40, FILES)
        changed = dict(FILES); changed["notes.md"] = b"# notes!\n"
        self.assertNotEqual(PK.manifest_hash(a), PK.manifest_hash(PK.build_manifest("app", "repo", "c" * 40, changed)))

    def test_load_round_trips(self):
        m = PK.build_manifest("app", "repo", "c" * 40, FILES)
        self.assertEqual(PK.load_manifest(PK.manifest_bytes(m)), m)

    def test_load_refuses_bad_shapes(self):
        m = PK.build_manifest("app", "repo", "c" * 40, FILES)
        for mutate in (lambda x: x.pop("files"),
                       lambda x: x["files"][0].update(path="../evil"),
                       lambda x: x["files"][0].update(sha256="zz"),
                       lambda x: x["files"].append(dict(x["files"][0])),
                       lambda x: x.update(commit="short")):
            bad = json.loads(json.dumps(m)); mutate(bad)
            with self.assertRaises(ValueError):
                PK.load_manifest(PK.manifest_bytes(bad))


class TestTar(unittest.TestCase):
    def test_reproducible(self):
        self.assertEqual(PK.build_tar(FILES), PK.build_tar(dict(reversed(list(FILES.items())))))

    def test_members_are_plain_files_with_fixed_metadata(self):
        with tarfile.open(fileobj=io.BytesIO(PK.build_tar(FILES))) as tar:
            members = tar.getmembers()
        self.assertEqual([m.name for m in members], sorted(FILES))
        for m in members:
            self.assertTrue(m.isreg())
            self.assertEqual((m.mtime, m.uid, m.gid, m.mode), (0, 0, 0, 0o444))


class TestVerifyInstalled(unittest.TestCase):
    def setUp(self):
        self.wd = tempfile.mkdtemp()
        self.sha = T.pin_workdir(self.wd, "app", FILES)

    def test_untouched_file_passes(self):
        PK.verify_installed(self.wd, self.sha, "code/mutator.py")        # control: no raise

    def test_edited_file_refused(self):
        with open(os.path.join(self.wd, "code/mutator.py"), "ab") as f:
            f.write(b"# tampered\n")
        with self.assertRaisesRegex(ValueError, "does not match the installed package manifest"):
            PK.verify_installed(self.wd, self.sha, "code/mutator.py")

    def test_missing_manifest_refused(self):
        os.remove(os.path.join(self.wd, PK.MANIFEST_NAME))
        with self.assertRaisesRegex(ValueError, "no installed package manifest"):
            PK.verify_installed(self.wd, self.sha, "code/mutator.py")

    def test_manifest_not_matching_pin_refused(self):
        with self.assertRaisesRegex(ValueError, "does not match the registry pin"):
            PK.verify_installed(self.wd, "0" * 64, "code/mutator.py")

    def test_file_not_in_manifest_refused(self):
        with self.assertRaisesRegex(ValueError, "not in the installed package manifest"):
            PK.verify_installed(self.wd, self.sha, "code/other.py")


if __name__ == "__main__":
    unittest.main()
