"""Checks on the deployment kits' shell scripts (deploy/pbx, deploy/lab).

Standard library + pytest only, no server needed: the scripts' syntax, and the
pure functions they define, exercised by sourcing the function body in bash.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2]
SCRIPTS = [
    DEPLOY / "pbx" / "install.sh",
    DEPLOY / "lab" / "install.sh",
    DEPLOY / "lab" / "firewall.sh",
]


def bash_function(script: Path, name: str, *args: str) -> str:
    """Run one function of a bash script, without executing the script itself."""
    source = script.read_text()
    # One-line definition first, then a multi-line body closed by a lone brace.
    match = re.search(rf"^{name}\(\) \{{[^\n]*\}}$", source, re.M)
    if match is None:
        match = re.search(rf"^{name}\(\)\s*\{{\n.*?^\}}", source, re.S | re.M)
    assert match, f"{name}() not found in {script}"
    cmd = match.group(0) + "\n" + " ".join([name, *(f"'{a}'" for a in args)])
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_scripts_parse(script: Path):
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_tenant_name_with_space_is_one_argument():
    """A company name with a space must reach `wazo-auth-cli tenant create` whole.

    The engine's playbook interpolates the inventory value unquoted into a
    `command:`; Ansible evaluates INI values as Python literals, so a literal
    holding double quotes is what keeps the name as a single argument.
    """
    value = bash_function(DEPLOY / "pbx" / "install.sh", "ansible_quote", "Ivoire Immo")
    assert value == "'\"Ivoire Immo\"'"
    # What Ansible will see after literal_eval, then how the command module splits it.
    import ast
    import shlex

    rendered = ast.literal_eval(value)
    assert shlex.split(f"wazo-auth-cli tenant create {rendered}") == [
        "wazo-auth-cli", "tenant", "create", "Ivoire Immo",
    ]


def test_company_name_rejects_quotes():
    source = (DEPLOY / "pbx" / "install.sh").read_text()
    assert "ne peut contenir ni guillemet" in source


def test_lab_firewall_rules_are_tagged_and_flushable():
    """Every rule the lab adds carries the comment it later removes by."""
    source = (DEPLOY / "lab" / "firewall.sh").read_text()
    inserts = [
        line for line in source.splitlines()
        if "iptables -I DOCKER-USER" in line or "iptables -t nat -I PREROUTING" in line
    ]
    assert inserts, "no iptables insert found"
    for line in inserts:
        assert '--comment "$TAG"' in line, line
    assert "flush_tagged filter DOCKER-USER" in source
    assert "flush_tagged nat PREROUTING" in source
    # First run: grep finds nothing and must not abort the script (pipefail).
    assert '|| true; }' in source


def test_pbx_inventory_defines_ari_port_with_its_address():
    """The engine's b2bua role binds ARI to the address only if the port is also set.

    `b2bua_listen_address = 0.0.0.0` alone leaves Asterisk's HTTP server on
    127.0.0.1 and the platform cannot reach ARI (seen on the lab PBX).
    """
    source = (DEPLOY / "pbx" / "install.sh").read_text()
    inventory = source[source.index("[uc_engine:vars]"):source.index("EOF", source.index("[uc_engine:vars]"))]
    assert re.search(r"^b2bua_listen_address = 0\.0\.0\.0$", inventory, re.M)
    assert re.search(r"^b2bua_port_http = 5039$", inventory, re.M)
    # sysconfd has no authentication: its port must NOT be set, or the same
    # address would expose it.
    assert "b2bua_port_sysconfd" not in inventory


def run_pbx_install_argument_parsing(*args: str) -> subprocess.CompletedProcess:
    """Run deploy/pbx/install.sh's real option parsing and validation, nothing else.

    The script is executed up to (and including) its argument checks, with the
    root/Debian checks neutralised, then prints the inventory line it would
    write for the tenant. No package is installed, nothing is written.
    """
    script = (DEPLOY / "pbx" / "install.sh").read_text()
    head = script[: script.index('echo "==> Paquets de base"')]
    head = head.replace("[[ $EUID -eq 0 ]]", "true").replace(
        "grep -q 'VERSION_CODENAME=bookworm' /etc/os-release", "true"
    )
    head += '\nprintf "tenant_name = %s\\n" "$(ansible_quote "$COMPANY")"\n'
    return subprocess.run(
        ["bash", "-c", head + ' "$@"', "install.sh", *args], capture_output=True, text=True
    )


def test_pbx_install_accepts_company_name_with_spaces():
    result = run_pbx_install_argument_parsing(
        "--nimbora-url", "https://app.example.com", "--nimbora-ip", "203.0.113.10",
        "--company", "OPTIMIUM NEXUS LLC",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'tenant_name = \'"OPTIMIUM NEXUS LLC"\'' in result.stdout


def test_pbx_install_refuses_company_name_with_quotes():
    result = run_pbx_install_argument_parsing(
        "--nimbora-url", "https://app.example.com", "--nimbora-ip", "203.0.113.10",
        "--company", 'Ivoire "Immo"',
    )
    assert result.returncode == 1
    assert "guillemet" in result.stdout + result.stderr


def render_pbx_firewall(**options: str) -> str:
    """Render the PBX kit's nftables file the way install.sh --firewall-only would."""
    args = ["--nimbora-url", "https://app.example.com", "--nimbora-ip", "203.0.113.10", "--firewall-only"]
    for key, value in options.items():
        args += [f"--{key.replace('_', '-')}", value]
    script = (DEPLOY / "pbx" / "install.sh").read_text()
    head = script[: script.index('if [[ "$FIREWALL_ONLY" == 1 ]]; then')]
    head = head.replace("[[ $EUID -eq 0 ]]", "true").replace(
        "grep -q 'VERSION_CODENAME=bookworm' /etc/os-release", "true"
    )
    # Print the file instead of writing /etc and loading nft.
    head = head.replace("cat > /etc/nftables.d-nimbora-pbx.conf <<EOF", "cat <<EOF")
    head = head[: head.index("  grep -q 'nftables.d-nimbora-pbx.conf'")] + "}\napply_firewall\n"
    result = subprocess.run(["bash", "-c", head + ' "$@"', "install.sh", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout


def test_pbx_firewall_denies_by_default_and_opens_only_the_documented_ports():
    rules = render_pbx_firewall()
    assert "policy drop;" in rules
    assert "iif lo accept" in rules
    assert "ct state established,related accept" in rules
    assert "udp sport 67 udp dport 68 accept" in rules            # DHCP lease keeps working
    assert "    tcp dport 22 accept" in rules                      # SSH from anywhere by default
    assert "    tcp dport 443 accept" in rules
    assert "tcp dport 5039 ip saddr { 127.0.0.1, 203.0.113.10 } accept" in rules
    assert "tcp dport 5038 ip saddr 127.0.0.1 accept" in rules
    assert "    udp dport 5060 accept" in rules
    assert "    udp dport 10000-20000 accept" in rules
    for closed in ("5672", "25672", "15672", "4369", " 25 ", "2000", "8667", "9498", "9499", "dport 80 "):
        assert f"dport {closed}" not in rules and f"{closed} accept" not in rules, closed


def test_pbx_firewall_restricts_sip_and_opens_phones_on_request():
    rules = render_pbx_firewall(sip_from="198.51.100.0/24,203.0.113.5", phones_from="192.168.10.0/24", rtp_range="20000-30000")
    assert "ip saddr { 198.51.100.0/24, 203.0.113.5 } udp dport 5060 accept" in rules
    assert "ip saddr { 198.51.100.0/24, 203.0.113.5 } udp dport 20000-30000 accept" in rules
    assert "ip saddr { 192.168.10.0/24 } tcp dport { 8667, 9498, 9499 } accept" in rules
    assert "    udp dport 5060 accept" not in rules


def test_pbx_firewall_can_close_sip_and_rejects_bad_sources():
    rules = render_pbx_firewall(sip_from="none", ssh_from="none")
    assert "5060" not in rules and "dport 22" not in rules
    script = (DEPLOY / "pbx" / "install.sh").read_text()
    head = script[: script.index('if [[ "$FIREWALL_ONLY" == 1 ]]; then')]
    head = head.replace("[[ $EUID -eq 0 ]]", "true").replace("grep -q 'VERSION_CODENAME=bookworm' /etc/os-release", "true")
    bad = subprocess.run(["bash", "-c", head + ' "$@"', "install.sh", "--nimbora-url", "https://a.example.com",
                          "--nimbora-ip", "203.0.113.10", "--sip-from", "office"], capture_output=True, text=True)
    assert bad.returncode == 1 and "--sip-from" in bad.stdout + bad.stderr



FAIL2BAN = DEPLOY / "pbx" / "templates" / "fail2ban"
WAZO_AUTH_FAILURE = (
    "2026-11-21 20:34:13,781 UTC [pid 45056] [tid 126367618275008] (INFO) "
    "(wazo_auth.plugins.http.tokens.http): Failed login: unknown username or password "
    'for login baduser from 203.0.113.9 using agent "curl/8.5.0"'
)
WAZO_AUTH_RESPONSE = (
    "2026-11-21 20:34:13,825 UTC [pid 45056] [tid 126367618275008] (INFO) (wazo-auth): "
    "response to 203.0.113.9 in 0.19s: POST https://localhost/api/auth/0.1/token 401 [span_id=1]"
)


def fail2ban_regexes(filter_file: Path) -> list[re.Pattern]:
    """The filter's failregex lines as Python patterns (fail2ban's <HOST> → an IPv4/IPv6)."""
    import configparser

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(filter_file)
    lines = [l.strip() for l in parser["Definition"]["failregex"].splitlines() if l.strip()]
    return [re.compile(l.replace("<HOST>", r"(?P<host>[0-9a-fA-F.:]+)")) for l in lines]


def test_fail2ban_filter_matches_refused_logins_only():
    patterns = fail2ban_regexes(FAIL2BAN / "filter-nimbora-pbx-auth.conf")
    assert patterns
    hits = [p.search(WAZO_AUTH_FAILURE) for p in patterns]
    assert any(hits), "the refused-login line must match"
    assert next(h for h in hits if h).group("host") == "203.0.113.9"
    assert not any(p.search(WAZO_AUTH_RESPONSE) for p in patterns), "a plain 401 response line must not"


def test_fail2ban_jail_targets_wazo_auth_and_spares_the_platform():
    import configparser

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(FAIL2BAN / "jail-nimbora-pbx.conf")
    jail = parser["nimbora-pbx-auth"]
    assert jail["enabled"] == "true"
    assert jail["filter"] == "nimbora-pbx-auth"
    assert jail["logpath"] == "/var/log/wazo-auth.log"
    assert "__NIMBORA_IPS__" in jail["ignoreip"] and "127.0.0.1/8" in jail["ignoreip"]
    assert int(jail["maxretry"]) <= 5 and int(jail["bantime"]) >= 600
    assert "iptables-multiport" in jail["action"] and "443" in jail["action"]
    source = (DEPLOY / "pbx" / "install.sh").read_text()
    assert "__NIMBORA_IPS__#${platform_ips}" in source
    assert 'getent ahostsv4 "$DOMAIN"' in source        # the platform's public address too


def test_tenant_contexts_cover_what_the_platform_reads_by_type():
    """A tenant made with wazo-auth-cli has no context; the platform needs one of each kind."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ensure_tenant_contexts", DEPLOY / "pbx" / "scripts" / "ensure_tenant_contexts.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    contexts = module.desired_contexts(module.slugify("Entreprise test"))
    assert [c["type"] for c in contexts] == ["internal", "incall", "outcall"]
    assert [c["name"] for c in contexts] == ["entreprise-test-internal", "entreprise-test-incall", "entreprise-test-outcall"]
    internal = contexts[0]
    assert internal["user_ranges"] == [{"start": "1000", "end": "1999"}]      # extensions 1001, 1002…
    assert internal["queue_ranges"] == [{"start": "3000", "end": "3999"}]
    assert all(c["enabled"] for c in contexts)
    assert module.slugify("  OPTIMIUM NEXUS LLC ") == "optimium-nexus-llc"
    source = (DEPLOY / "pbx" / "install.sh").read_text()
    assert "ensure_tenant_contexts.py" in source and source.index("create_service_account.py") < source.index("ensure_tenant_contexts.py")
