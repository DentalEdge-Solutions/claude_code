import os, shutil, stat, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import host_layout as H


def make_layout(store, spool):
    """Build the layout BY HAND, as the test process's own user. Every mode in the table
    keeps owner rwx on directories, so cleanup never needs a chmod first."""
    for e in H.LAYOUT:
        p = H.entry_path(e, store, spool)
        if e.kind == H.DIR:
            os.mkdir(p)
        else:
            with open(p, "wb") as f:
                f.write(e.content)
        os.chmod(p, e.mode)


class Base(unittest.TestCase):
    """Tier 1: one unprivileged user. The resolver maps every table name onto that user's
    own uid/gid, so a correct layout is buildable without root. A WRONG owner or group is
    produced by pointing a name at some other id, never by chown."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="host-layout-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.uid, self.gid = os.getuid(), os.getgid()
        self.set_roots(self.base)
        self.resolver = H.Resolver(
            users={"root": self.uid, "hermes-broker": self.uid},
            groups={"hermes": self.gid, "hermes-broker": self.gid})

    def set_roots(self, parent):
        self.store = os.path.join(parent, "governance")
        self.spool = os.path.join(parent, "spool")

    def kw(self, **over):
        # Ancestors are walked only up to self.base, and trust this user as well as root:
        # a tempdir's real ancestors (/var/folders on darwin, /tmp on Linux) are exactly
        # what production must refuse, and are exercised in Tier 2.
        kw = dict(resolver=self.resolver, ancestor_uids=(0, self.uid),
                  ancestor_top=self.base)
        kw.update(over)
        return kw

    def check(self, **over):
        return H.check(self.store, self.spool, **self.kw(**over))


class TestTable(unittest.TestCase):
    def test_the_table_is_the_spec(self):
        """Spec §3.2 and §3.3, pinned. A change here is a security design change and must
        come with a spec change, not a test edit."""
        got = {(e.root_key, e.relpath): (e.kind, e.owner, e.group, e.mode)
               for e in H.LAYOUT}
        self.assertEqual(got, {
            ("store", ""): ("dir", "root", "hermes", 0o750),
            ("store", "approvals"): ("dir", "hermes-broker", "hermes", 0o2750),
            ("store", "control"): ("dir", "root", "hermes", 0o2750),
            ("store", "control/.locks"): ("dir", "hermes-broker", "hermes-broker", 0o700),
            ("store", "registry"): ("dir", "root", "hermes", 0o2750),
            ("store", "registry/clients.json"): ("file", "root", "hermes", 0o640),
            ("store", "log"): ("dir", "root", "hermes", 0o2750),
            ("store", "seen"): ("dir", "hermes-broker", "hermes-broker", 0o700),
            ("spool", ""): ("dir", "root", "hermes", 0o750),
            ("spool", "requests"): ("dir", "hermes-broker", "hermes", 0o3770),
            ("spool", "requests/.quarantine"): ("dir", "hermes-broker", "hermes-broker", 0o700),
            ("spool", "results"): ("dir", "hermes-broker", "hermes", 0o2750),
        })

    def test_log_dir_mode_is_the_governance_lib_constant(self):
        log = [e for e in H.LAYOUT if e.relpath == "log"][0]
        self.assertEqual(log.mode, H.governance_lib.LOG_DIR_MODE)

    def test_the_registry_starts_as_zero_clients(self):
        reg = [e for e in H.LAYOUT if e.relpath == "registry/clients.json"][0]
        self.assertEqual(reg.content, b"{}\n")

    def test_parents_precede_children(self):
        seen = set()
        for e in H.LAYOUT:
            parent = os.path.dirname(e.relpath)
            if e.relpath:
                self.assertIn((e.root_key, parent), seen, e)
            seen.add((e.root_key, e.relpath))

    def test_default_roots(self):
        self.assertEqual(H.DEFAULT_STORE_ROOT, "/var/lib/hermes/governance")
        self.assertEqual(H.DEFAULT_SPOOL_ROOT, "/var/lib/hermes/spool")


class TestCheck(Base):
    def setUp(self):
        super().setUp()
        make_layout(self.store, self.spool)

    def test_control_the_correct_layout_has_no_problems(self):
        self.assertEqual(self.check(), [])

    def test_a_missing_entry_is_reported_as_missing(self):
        os.rmdir(os.path.join(self.store, "seen"))
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("seen", problems[0])
        self.assertIn("missing", problems[0])
        self.assertIn("expected dir hermes-broker:hermes-broker 0700", problems[0])

    def test_a_missing_root_is_one_problem_not_a_cascade(self):
        shutil.rmtree(self.spool)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith(self.spool + ":"), problems)

    def test_a_missing_setgid_bit_is_caught(self):
        os.chmod(os.path.join(self.store, "approvals"), 0o750)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("mode 0750", problems[0])
        self.assertIn("expected hermes-broker:hermes 2750", problems[0])

    def test_a_missing_sticky_bit_is_caught(self):
        os.chmod(os.path.join(self.spool, "requests"), 0o2770)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("expected hermes-broker:hermes 3770", problems[0])

    def test_a_wrong_owner_is_caught(self):
        r = H.Resolver(users={"root": self.uid, "hermes-broker": self.uid + 4242},
                       groups={"hermes": self.gid, "hermes-broker": self.gid})
        problems = self.check(resolver=r)
        owned = [e for e in H.LAYOUT if e.owner == "hermes-broker"]
        self.assertEqual(len(problems), len(owned), problems)
        for p in problems:
            self.assertIn("expected hermes-broker:", p)

    def test_a_wrong_group_is_caught(self):
        r = H.Resolver(users={"root": self.uid, "hermes-broker": self.uid},
                       groups={"hermes": self.gid + 4242, "hermes-broker": self.gid})
        problems = self.check(resolver=r)
        grouped = [e for e in H.LAYOUT if e.group == "hermes"]
        self.assertEqual(len(problems), len(grouped), problems)

    def test_a_symlink_in_place_of_a_directory_is_caught_and_not_followed(self):
        q = os.path.join(self.spool, "requests", ".quarantine")
        os.rmdir(q)
        target = os.path.join(self.base, "elsewhere")
        os.mkdir(target)
        os.chmod(target, 0o700)          # the target would PASS if it were followed
        os.symlink(target, q)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("symlink", problems[0])

    def test_a_directory_in_place_of_the_registry_file_is_caught(self):
        reg = os.path.join(self.store, "registry", "clients.json")
        os.unlink(reg)
        os.mkdir(reg)
        os.chmod(reg, 0o640 | 0o100)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not a file", problems[0])

    def test_every_mismatch_line_names_the_expected_state(self):
        """R3. The tool never repairs, so a refusal must say what correct is."""
        reg = os.path.join(self.store, "registry", "clients.json")
        os.chmod(reg, 0o644)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("registry/clients.json", problems[0])
        self.assertIn("mode 0644", problems[0])
        self.assertIn("expected root:hermes 0640", problems[0])


class TestAncestors(Base):
    def setUp(self):
        super().setUp()
        self.mid = os.path.join(self.base, "mid")
        os.mkdir(self.mid)
        os.chmod(self.mid, 0o755)
        self.set_roots(self.mid)
        make_layout(self.store, self.spool)

    def test_control_a_sound_ancestor_chain_passes(self):
        self.assertEqual(self.check(), [])

    def test_a_group_writable_ancestor_is_refused(self):
        os.chmod(self.mid, 0o775)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)     # one line, not one per root
        self.assertIn(self.mid, problems[0])
        self.assertIn("writable", problems[0])

    def test_a_world_writable_ancestor_is_refused(self):
        os.chmod(self.mid, 0o757)
        problems = self.check()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("writable", problems[0])

    @unittest.skipIf(os.geteuid() == 0, "as root the test directory IS root-owned")
    def test_an_ancestor_owned_by_an_untrusted_uid_is_refused(self):
        problems = self.check(ancestor_uids=(0,))
        self.assertTrue(any(self.mid in p and "owned by uid" in p for p in problems),
                        problems)

    def test_a_symlinked_ancestor_is_refused(self):
        link = os.path.join(self.base, "link")
        os.symlink(self.mid, link)
        self.set_roots(link)
        problems = self.check()
        self.assertTrue(any(p.startswith(link + ":") and "symlink" in p
                            for p in problems), problems)


class TestSystemResolver(unittest.TestCase):
    class _Pw:
        def __init__(self, uid):
            self.pw_uid = uid

    class _Gr:
        def __init__(self, gid):
            self.gr_gid = gid

    def _lookups(self, users, groups):
        def getpwnam(n):
            if n not in users:
                raise KeyError(n)
            return self._Pw(users[n])

        def getgrnam(n):
            if n not in groups:
                raise KeyError(n)
            return self._Gr(groups[n])
        return getpwnam, getgrnam

    def test_resolves_names_to_ids(self):
        pw, gr = self._lookups({"root": 0, "hermes-broker": 997},
                               {"hermes": 10000, "hermes-broker": 996})
        r = H.system_resolver(pw, gr)
        self.assertEqual((r.uid("hermes-broker"), r.gid("hermes")), (997, 10000))

    def test_refuses_a_hermes_group_that_is_not_the_executor_gid(self):
        pw, gr = self._lookups({"root": 0, "hermes-broker": 997},
                               {"hermes": 1234, "hermes-broker": 996})
        with self.assertRaises(H.LayoutError) as cm:
            H.system_resolver(pw, gr)
        self.assertIn("10000", str(cm.exception))

    def test_an_unknown_user_is_a_refusal_naming_it(self):
        pw, gr = self._lookups({"root": 0}, {"hermes": 10000, "hermes-broker": 996})
        r = H.system_resolver(pw, gr)
        with self.assertRaises(H.LayoutError) as cm:
            r.uid("hermes-broker")
        self.assertIn("hermes-broker", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
