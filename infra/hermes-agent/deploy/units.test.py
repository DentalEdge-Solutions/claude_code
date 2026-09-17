import os, re, unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def unit(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


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
    files it tests for no real gain.
    """

    def test_the_broker_is_not_in_the_docker_group(self):
        """The entire point of the proxy. A broker in the docker group has host root
        and every other guarantee in this tier is decoration."""
        body = unit("hermes-broker.service")
        for line in body.splitlines():
            if line.startswith(("Group=", "SupplementaryGroups=")):
                self.assertNotIn("docker", line, line)

    def test_only_the_proxy_touches_the_real_socket(self):
        self.assertIn("/var/run/docker.sock", unit("hermes-docker-proxy.service"))
        self.assertNotIn("/var/run/docker.sock", unit("hermes-broker.service"))

    def test_the_broker_reaches_docker_only_through_the_proxy(self):
        self.assertIn("DOCKER_HOST=unix:///run/hermes/docker-proxy.sock",
                      unit("hermes-broker.service"))

    def test_the_preflight_runs_before_the_broker_starts(self):
        body = unit("hermes-broker.service")
        self.assertIn("ExecStartPre", body)
        self.assertIn("preflight-governance-access.py", body)

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
        for line in body.splitlines():
            if line.startswith("Group="):
                self.assertNotEqual(line.strip(), "Group=hermes-broker", line)
            elif line.startswith("SupplementaryGroups="):
                groups = line.split("=", 1)[1].split()
                self.assertNotIn("hermes-broker", groups, line)

    def test_the_broker_can_read_the_governance_store(self):
        """The pre-flight READS clients.json. A broker outside gid 10000 refuses with four
        spurious 'cannot stat' problems instead of naming --bootstrap-logs.

        Membership is checked by SPLITTING the directive, not by regex. The obvious
        r"SupplementaryGroups=.*\bhermes\b" is ILLUSORY: \bhermes\b is satisfied by the
        'hermes' inside 'hermes-rail' (the hyphen is a word boundary), so it matches a unit
        that has dropped the real gid-10000 group — exactly the regression this guards."""
        groups = []
        for line in unit("hermes-broker.service").splitlines():
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


if __name__ == "__main__":
    unittest.main()
