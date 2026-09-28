#!/usr/bin/env python3
import contextlib, importlib.util, io, os, stat, sys, tarfile, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import package_lib as PK
import package_testutil as T
spec = importlib.util.spec_from_file_location("install_app_package", os.path.join(HERE, "install-app-package.py"))
I = importlib.util.module_from_spec(spec); spec.loader.exec_module(I)

FILES = {"code/mutator.py": b"m\n", "notes.md": b"n\n"}


def tar_of(members):
    """members: list of (TarInfo-kwargs dict, bytes|None)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for kw, data in members:
            ti = tarfile.TarInfo(kw.pop("name"))
            for k, v in kw.items():
                setattr(ti, k, v)
            if data is not None:
                ti.size = len(data)
            t.addfile(ti, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.m = PK.build_manifest("app", "repo", T.FAKE_COMMIT, FILES)
        self.sha = PK.manifest_hash(self.m)
        self.projects = self._reg(self.sha)
        self.manifest = self._write("m.json", PK.manifest_bytes(self.m))
        self.package = self._write("p.tar", PK.build_tar(FILES))
        self.target = os.path.join(self.d, "claude-google-ads")
        os.makedirs(self.target)
        self._write("claude-google-ads/PLACEHOLDER", b"placeholder\n")

    def _write(self, rel, data):
        p = os.path.join(self.d, rel)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def _reg(self, sha):
        return self._write("projects.yaml", ("version: 1\n\nprojects:\n  app:\n    workdir: /projects/app\n"
                                             + T.package_block(sha)).encode())

    def _install(self, package=None, manifest=None):
        raw, files = I.verify("app", package or self.package, manifest or self.manifest, self.projects)
        I.install(self.target, raw, files, chown=False)


class TestInstall(Base):
    def test_valid_package_installs_with_the_stated_modes(self):
        self._install()
        self.assertFalse(os.path.exists(os.path.join(self.target, "PLACEHOLDER")))
        with open(os.path.join(self.target, "code/mutator.py"), "rb") as f:
            self.assertEqual(f.read(), b"m\n")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.target, "code/mutator.py")).st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.target, "code")).st_mode), 0o555)
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o555)
        env = os.path.join(self.target, ".env")
        self.assertEqual((os.path.getsize(env), stat.S_IMODE(os.stat(env).st_mode)), (0, 0o600))
        PK.verify_installed(self.target, self.sha, "code/mutator.py")      # guard 7 would pass

    def test_reinstall_over_an_installed_package(self):
        self._install(); self._install()                                     # read-only tree replaced

    def test_manifest_not_matching_the_pin_refused(self):
        self.projects = self._reg("f" * 64)
        with self.assertRaisesRegex(ValueError, "does not match the registry pin"):
            self._install()

    def test_member_bytes_not_matching_the_manifest_refused(self):
        bad = self._write("bad.tar", PK.build_tar({"code/mutator.py": b"evil\n", "notes.md": b"n\n"}))
        with self.assertRaisesRegex(ValueError, "does not match the manifest"):
            self._install(package=bad)

    def test_unsafe_members_refused(self):
        cases = {
            "symlink": [({"name": "code/mutator.py", "type": tarfile.SYMTYPE, "linkname": "/etc/passwd"}, None)],
            "hardlink": [({"name": "code/mutator.py", "type": tarfile.LNKTYPE, "linkname": "notes.md"}, None)],
            "dotdot": [({"name": "../evil.py"}, b"x")],
            "absolute": [({"name": "/tmp/evil.py"}, b"x")],
            "extra": [({"name": "code/mutator.py"}, b"m\n"), ({"name": "notes.md"}, b"n\n"), ({"name": "extra.py"}, b"x")],
            "missing": [({"name": "code/mutator.py"}, b"m\n")],
        }
        for label, members in cases.items():
            p = self._write(f"{label}.tar", tar_of(members))
            with self.assertRaises(ValueError, msg=label):
                self._install(package=p)
        self.assertTrue(os.path.exists(os.path.join(self.target, "PLACEHOLDER")))   # untouched

    def test_symlinked_target_refused(self):
        real = os.path.join(self.d, "elsewhere"); os.makedirs(real)
        link = os.path.join(self.d, "linked-target"); os.symlink(real, link)
        raw, files = I.verify("app", self.package, self.manifest, self.projects)
        with self.assertRaisesRegex(ValueError, "symlink"):
            I.install(link, raw, files, chown=False)

    def test_failed_swap_leaves_the_previous_tree(self):
        real_rename = os.rename
        calls = []

        def flaky(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise OSError("simulated failure between the two renames")
            return real_rename(src, dst)

        raw, files = I.verify("app", self.package, self.manifest, self.projects)
        with mock.patch.object(I.os, "rename", side_effect=flaky):
            with self.assertRaises(OSError):
                I.install(self.target, raw, files, chown=False)
        self.assertTrue(os.path.exists(os.path.join(self.target, "PLACEHOLDER")))
        self.assertEqual([n for n in os.listdir(self.d) if ".new-" in n or ".old-" in n], [])


class TestMain(Base):
    def test_success_prints_the_force_recreate_reminder(self):
        # D1 (final-review): the compose bind does not follow a rename, so the CLI
        # itself must remind the operator to force-recreate the gateway.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = I.main(["--project", "app", "--package", self.package, "--manifest", self.manifest,
                        "--target", self.target, "--projects", self.projects, "--no-chown"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("force-recreate hermes-agent", out)
        self.assertIn("docker compose ps", out)

    def test_control_a_refused_install_prints_no_reminder(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = I.main(["--project", "app", "--package", self.package, "--manifest", self.manifest + ".missing",
                        "--target", self.target, "--projects", self.projects, "--no-chown"])
        self.assertEqual(rc, 1)
        self.assertNotIn("force-recreate", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
