import os, re, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))

AGENT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(AGENT, "bin"))
import host_layout as H
import bind_agreement as BA


def unit(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


def live_lines(body):
    """Directive lines only: stripped, no comments, no blanks. A commented-out
    directive is how a gate gets disabled mid-debug and left that way."""
    return [l.strip() for l in body.splitlines()
            if l.strip() and not l.strip().startswith("#")]


class TestUnits(unittest.TestCase):
    """WHAT THIS PROVES, AND WHAT IT DOES NOT.

    These assert that the unit FILES SAY the right thing. They do NOT prove systemd
    behaves that way: nothing here exercises ProtectSystem=strict, NoNewPrivileges,
    RestrictAddressFamilies, or boot ordering. Those stay UNPROVEN until the VPS, and
    the PR body must say so — "the units are tested" would otherwise read as a
    guarantee this wave does not make.

    Discovery note: run-bin-tests.sh discovers *.test.py under bin/ only, so this
    suite is NOT picked up by that runner. Run it explicitly:
    `python3 infra/hermes-agent/deploy/units.test.py`. The units live in deploy/;
    moving this file to bin/ to satisfy a discovery glob would split it from the
    files it tests for no real gain. CI therefore invokes it as its own step rather
    than relying on discovery — see .github/workflows/ci.yml.
    """

    def test_the_broker_is_not_in_the_docker_group(self):
        """The entire point of the proxy. A broker in the docker group has host root
        and every other guarantee in this tier is decoration."""
        body = unit("hermes-broker.service")
        for raw in body.splitlines():
            # .strip() because systemd honours a leading-whitespace directive but a bare
            # startswith() would skip it — and skipping, here, is a silent PASS on the one
            # regression this file exists to catch. MEASURED 2026-09-17.
            line = raw.strip()
            if line.startswith(("Group=", "SupplementaryGroups=")):
                self.assertNotIn("docker", line, raw)

    def test_only_the_proxy_touches_the_real_socket(self):
        self.assertIn("/var/run/docker.sock", unit("hermes-docker-proxy.service"))
        self.assertNotIn("/var/run/docker.sock", unit("hermes-broker.service"))

    def test_the_broker_reaches_docker_only_through_the_proxy(self):
        self.assertIn("DOCKER_HOST=unix:///run/hermes/docker-proxy.sock",
                      unit("hermes-broker.service"))

    def test_the_preflight_runs_before_the_broker_starts(self):
        """Line-based, not a raw substring check, for the same reason
        test_the_broker_is_not_in_the_docker_group is. MEASURED 2026-09-17: with
        `assertIn("ExecStartPre", body)`, prefixing the directive with `#` — which is
        how a pre-flight actually gets disabled mid-debug and left that way — still
        satisfied the assertion, while systemd reads the line as a comment and never
        runs the gate. Deleting the lines was caught; commenting them out was not."""
        directives = [l.strip() for l in unit("hermes-broker.service").splitlines()
                      if l.strip().startswith("ExecStartPre=")]
        self.assertTrue(directives, "no live ExecStartPre= directive (commented out?)")
        self.assertTrue(
            any("preflight-governance-access.py" in l for l in directives),
            "ExecStartPre= runs something, but not the governance pre-flight: %r"
            % directives)

    def test_both_users_share_the_rail_group_so_the_socket_is_reachable(self):
        """MEASURED 2026-09-16: without a shared group on the runtime directory and
        the socket, the broker gets EACCES and the rail is dead on first boot."""
        self.assertIn("Group=hermes-rail", unit("hermes-docker-proxy.service"))
        self.assertIn("hermes-rail", unit("hermes-broker.service"))

    def test_the_proxy_does_not_get_the_brokers_group(self):
        """That would work for the socket AND hand the proxy read access to .env.gaw.

        Line-based, not a raw substring check: the unit's own explanatory comment
        names "Group=hermes-broker" verbatim (to say why it was NOT chosen), which
        a plain assertNotIn would trip on. Check the actual directive line instead,
        the same way test_the_broker_is_not_in_the_docker_group does.

        Checks BOTH Group= and SupplementaryGroups=: the proxy unit only sets
        SupplementaryGroups=docker today, so there is no live gap, but a future
        SupplementaryGroups=hermes-broker would grant the same .env.gaw read access
        through the supplementary path and must not slip past unnoticed.
        """
        body = unit("hermes-docker-proxy.service")
        for raw in body.splitlines():
            line = raw.strip()   # see the note in test_the_broker_is_not_in_the_docker_group
            if line.startswith("Group="):
                self.assertNotEqual(line, "Group=hermes-broker", raw)
            elif line.startswith("SupplementaryGroups="):
                groups = line.split("=", 1)[1].split()
                self.assertNotIn("hermes-broker", groups, raw)

    def test_the_broker_can_read_the_governance_store(self):
        """The pre-flight READS clients.json. A broker outside gid 10000 refuses with four
        spurious 'cannot stat' problems instead of naming --bootstrap-logs.

        Membership is checked by SPLITTING the directive, not by regex. The obvious
        r"SupplementaryGroups=.*\bhermes\b" is ILLUSORY: \bhermes\b is satisfied by the
        'hermes' inside 'hermes-rail' (the hyphen is a word boundary), so it matches a unit
        that has dropped the real gid-10000 group — exactly the regression this guards."""
        groups = []
        for raw in unit("hermes-broker.service").splitlines():
            line = raw.strip()   # see test_the_broker_is_not_in_the_docker_group
            if line.startswith("SupplementaryGroups="):
                groups.extend(line.split("=", 1)[1].split())
        self.assertIn("hermes", groups)
        self.assertIn("hermes-rail", groups)

    def test_the_proxy_unit_supplies_the_required_network_flag(self):
        """--network is required=True in main(). A unit that omits it fails to start with
        argparse exit 2 — at boot, on the VPS. Ruling 9 added the flag in Task 3 and this
        assertion is what keeps Task 5's unit in step with it."""
        self.assertRegex(unit("hermes-docker-proxy.service"), r"--network \S+")

    def test_the_proxy_has_no_log_only_bypass(self):
        """A proxy with a bypass flag is not a proxy."""
        self.assertNotIn("--log-only", unit("hermes-docker-proxy.service"))

    def test_every_allow_bind_flag_is_well_formed(self):
        for raw in re.findall(r"--allow-bind (\S+)", unit("hermes-docker-proxy.service")):
            bits = raw.split(":")
            self.assertEqual(len(bits), 3, raw)
            self.assertIn(bits[2], ("ro", "rw"), raw)

    def test_exactly_one_bind_is_writable(self):
        modes = [r.split(":")[2] for r in
                 re.findall(r"--allow-bind (\S+)", unit("hermes-docker-proxy.service"))]
        self.assertEqual(modes.count("rw"), 1)
        self.assertEqual(len(modes), 7)

    def test_the_layout_check_runs_before_the_preflight(self):
        """F10. The pre-flight predicts what uid 10000 can do; it cannot tell a wrong
        OWNER from a right one with the same bits. The layout --check can. It runs
        first so a wrong layout refuses with its own expected-state lines."""
        pre = [l for l in live_lines(unit("hermes-broker.service"))
               if l.startswith("ExecStartPre=")]
        layout = [i for i, l in enumerate(pre) if "init-host-layout.py" in l]
        flight = [i for i, l in enumerate(pre) if "preflight-governance-access.py" in l]
        self.assertEqual(len(layout), 1, pre)
        self.assertEqual(len(flight), 1, pre)
        self.assertLess(layout[0], flight[0])
        self.assertIn("--check", pre[layout[0]])
        self.assertNotIn("--apply", " ".join(pre))

    def test_the_broker_writes_only_the_store_and_the_spool(self):
        rw = [l.split("=", 1)[1].split() for l in live_lines(unit("hermes-broker.service"))
              if l.startswith("ReadWritePaths=")]
        self.assertEqual(rw, [[H.DEFAULT_STORE_ROOT, H.DEFAULT_SPOOL_ROOT]])

    def test_no_live_directive_points_the_broker_at_data_spool(self):
        """F10b: under the gateway-owned data/, the spool is a redirect into the store."""
        for l in live_lines(unit("hermes-broker.service")):
            self.assertNotIn("data/spool", l)


class TestUMask(unittest.TestCase):
    """The §6 hardening (spec 2026-09-23 §3.3): both units run with UMask=0077, in [Service].
    systemd applies it only there; a UMask in [Unit] or [Install] is ignored silently."""

    @staticmethod
    def _service_umasks(body):
        section, found = None, []
        for line in live_lines(body):
            if line.startswith("[") and line.endswith("]"):
                section = line
            elif line.startswith("UMask="):
                found.append((section, line))
        return found

    def test_both_units_set_umask_0077_in_service(self):
        for name in ("hermes-docker-proxy.service", "hermes-broker.service"):
            self.assertEqual(self._service_umasks(unit(name)),
                             [("[Service]", "UMask=0077")], name)

    def test_control_a_unit_without_the_line_fails(self):
        body = unit("hermes-docker-proxy.service")
        stripped = "\n".join(l for l in body.splitlines() if not l.strip().startswith("UMask="))
        self.assertNotEqual(self._service_umasks(stripped), [("[Service]", "UMask=0077")])

    def test_control_a_umask_in_the_wrong_section_fails(self):
        body = "[Unit]\nUMask=0077\n[Service]\nType=simple\n"
        self.assertNotEqual(self._service_umasks(body), [("[Service]", "UMask=0077")])


class TestSpoolPathContract(unittest.TestCase):
    """F10b. The unit, .env.example, the compose mount and host_layout must name one
    spool path, and compose must have no fallback to a path under data/."""

    def read(self, rel):
        return open(os.path.join(AGENT, rel), encoding="utf-8").read()

    def test_unit_and_env_example_agree_with_the_layout(self):
        self.assertIn("Environment=HERMES_SPOOL_ROOT=%s" % H.DEFAULT_SPOOL_ROOT,
                      live_lines(unit("hermes-broker.service")))
        self.assertRegex(self.read(".env.example"),
                         r"(?m)^HERMES_SPOOL_DIR=%s$" % re.escape(H.DEFAULT_SPOOL_ROOT))

    def test_the_gateway_mounts_the_spool_with_no_fallback(self):
        mounts = [l for l in live_lines(self.read("docker-compose.yml"))
                  if "/opt/data/spool" in l]
        self.assertEqual(len(mounts), 1, mounts)
        source = mounts[0].split(":/opt/data/spool")[0]
        self.assertTrue(source.startswith("- ${HERMES_SPOOL_DIR:?"), mounts[0])
        self.assertNotIn(":-", source)


class TestExecutorBindContract(unittest.TestCase):
    """F9. The broker unit, .env.example and the units' own program paths must name the same
    executor bind sources. proxy-policy-sync.test.py compares them with the proxy's pins."""

    def setUp(self):
        self.env = BA.unit_environment(unit("hermes-broker.service"))
        self.example = open(os.path.join(AGENT, ".env.example"), encoding="utf-8").read()

    def test_the_broker_sets_the_executor_bind_sources(self):
        self.assertEqual(self.env.get("HERMES_AGENT_DIR"), "/opt/hermes-agent")
        self.assertEqual(self.env.get("HERMES_ADS_REPO_DIR"), "/opt/projects/claude-google-ads")

    def test_the_brokers_spool_dir_is_its_spool_root(self):
        self.assertEqual(self.env.get("HERMES_SPOOL_DIR"), self.env.get("HERMES_SPOOL_ROOT"))
        self.assertEqual(self.env.get("HERMES_SPOOL_DIR"), H.DEFAULT_SPOOL_ROOT)

    def test_env_example_agrees_with_the_broker(self):
        for key in ("HERMES_AGENT_DIR", "HERMES_ADS_REPO_DIR", "HERMES_GOVERNANCE_DIR",
                    "HERMES_SPOOL_DIR"):
            self.assertRegex(self.example,
                             r"(?m)^%s=%s$" % (key, re.escape(self.env[key])), key)

    def test_both_units_run_their_program_from_the_agent_dir(self):
        """HERMES_AGENT_DIR is the checkout both units already execute from; a unit that
        runs from one path and binds from another is F9 again."""
        agent = self.env["HERMES_AGENT_DIR"]
        for name in ("hermes-broker.service", "hermes-docker-proxy.service"):
            start = [l for l in live_lines(unit(name)) if l.startswith("ExecStart=")]
            self.assertEqual(len(start), 1, name)
            self.assertIn(agent + "/bin/", start[0], name)

    def test_firing_control_a_drifted_example_fails_the_regex(self):
        drifted = self.example.replace("HERMES_AGENT_DIR=/opt/hermes-agent",
                                       "HERMES_AGENT_DIR=/opt/elsewhere")
        self.assertNotEqual(drifted, self.example, "the control did not drift anything")
        self.assertNotRegex(drifted, r"(?m)^HERMES_AGENT_DIR=/opt/hermes-agent$")



class TestExecStartProgramsAreExecutable(unittest.TestCase):
    """F15, measured on the VPS 2026-09-22: hermes-docker-proxy.service execs
    bin/docker-create-proxy.py DIRECTLY, but the file shipped 100644, so systemd could not
    exec it at all — `status=203/EXEC`, the proxy dead, and the broker failing after it with
    "Dependency failed". Nothing caught it: bind-agreement-integration.test.py starts the
    proxy as `python3 <script>` and never needs the bit, and every other assertion in this
    file reads the unit TEXT.

    The rule this pins: if a unit's ExecStart/ExecStartPre runs a repo file directly (the
    program token is the script itself, not an interpreter), that file must be 100755 IN GIT
    — the working tree's mode is a local accident, git's index is what a fresh host clones.
    A script invoked as `/usr/bin/python3 <script>` is exempt: the interpreter is the
    program, and the script needs no bit.
    """

    AGENT_DIR = "/opt/hermes-agent"          # what the units execute from; == HERMES_AGENT_DIR

    def git_mode(self, repo_rel):
        """The file's mode in the git INDEX, e.g. '100644'. None when not tracked."""
        repo_root = os.path.dirname(os.path.dirname(AGENT))   # AGENT is infra/hermes-agent
        r = subprocess.run(["git", "ls-files", "-s", "--", repo_rel],
                           cwd=repo_root, capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout.split()[0]

    def directly_executed_programs(self):
        """(unit, program path) for every Exec* line whose program is a repo file.

        Scope: ExecStart/ExecStartPre/ExecStartPost, the lines that decide whether a unit
        can START — which is what F15 broke. Add ExecStop/ExecStopPost/ExecReload here if a
        unit ever execs a repo file from one of those.
        """
        out = []
        for name in ("hermes-broker.service", "hermes-docker-proxy.service"):
            for line in live_lines(re.sub(r"\\\n", " ", unit(name))):
                m = re.match(r"ExecStart(?:Pre|Post)?=(\S+)", line)
                if not m:
                    continue
                program = m.group(1)
                if not program.startswith(self.AGENT_DIR + "/"):
                    continue          # an interpreter (/usr/bin/python3): it is the program
                rel = os.path.join("infra/hermes-agent",
                                   program[len(self.AGENT_DIR) + 1:])
                out.append((name, rel))
        return out

    def test_control_the_mode_lookup_distinguishes_executable_from_not(self):
        """Without this, a lookup that silently returned None would pass everything."""
        self.assertEqual(self.git_mode("infra/hermes-agent/bin/init-host-layout.py"), "100755")
        self.assertEqual(self.git_mode("infra/hermes-agent/bin/governance_lib.py"), "100644")
        self.assertIsNone(self.git_mode("infra/hermes-agent/bin/does-not-exist.py"))

    def test_control_at_least_one_unit_execs_a_repo_file_directly(self):
        """If the parser found nothing, the assertion below would pass vacuously."""
        found = self.directly_executed_programs()
        self.assertTrue(found, "no Exec* line runs a repo file directly — parser is broken")

    def test_every_directly_executed_program_is_executable_in_git(self):
        for unit_name, rel in self.directly_executed_programs():
            mode = self.git_mode(rel)
            self.assertIsNotNone(mode, "%s execs %s, which git does not track" % (unit_name, rel))
            self.assertEqual(mode, "100755",
                             "%s execs %s directly, but it is %s in git — systemd would fail "
                             "with status=203/EXEC on a fresh host (F15). Fix with "
                             "`git update-index --chmod=+x %s`." % (unit_name, rel, mode, rel))


if __name__ == "__main__":
    unittest.main()
