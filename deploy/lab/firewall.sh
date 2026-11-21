#!/usr/bin/env bash
# NIMBORA lab — host firewall glue between Docker and Incus, idempotent.
#
# Installed by deploy/lab/install.sh as /usr/local/sbin/nimbora-lab-firewall and
# run by nimbora-lab-firewall.service after Docker and Incus start. Re-running it
# always yields the same rules: every rule it owns carries the comment
# "nimbora-lab", and is removed before being re-added.
#
# It never touches UFW, Docker's own chains or anything without that comment.
#
# What it does (IPv4):
#   DOCKER-USER (evaluated before Docker's FORWARD rules, which would otherwise
#   drop traffic between Docker bridges and the Incus bridge):
#     1. the PBX (Incus bridge) may talk to anything: Internet, operators, the
#        AI platform through its public name (hair-pin to Traefik);
#     2. replies to the PBX;
#     3. RTP from the public interface to the PBX (after the DNAT below);
#     4. SIP from the public interface to the PBX, only when SIP_PUBLIC=1;
#     5. the AI platform's own Docker network reaches the PBX (REST API, ARI);
#     6. Traefik's network reaches the PBX's HTTPS only (softphones, API);
#     7. the AI platform's network reaches Traefik (its own public URL);
#     8. nothing else from a Docker network reaches the PBX: ARI (5039) and
#        AMI (5038) are never reachable from other hosted applications.
#   nat PREROUTING: RTP (and SIP when SIP_PUBLIC=1) arriving on the public
#   interface is redirected to the PBX container.
set -euo pipefail

CONF="${NIMBORA_LAB_ENV:-/etc/nimbora-lab/lab.env}"
[[ -f "$CONF" ]] || { echo "nimbora-lab-firewall: $CONF introuvable" >&2; exit 1; }
# shellcheck disable=SC1090
. "$CONF"

: "${PUBLIC_IF:?PUBLIC_IF manquant dans $CONF}"
: "${PBX_IP:?PBX_IP manquant dans $CONF}"
: "${TRAEFIK_BRIDGE:?TRAEFIK_BRIDGE manquant dans $CONF}"
INCUS_BRIDGE="${INCUS_BRIDGE:-incusbr0}"
NIMBORA_BRIDGE="${NIMBORA_BRIDGE:-br-nimboralab}"
RTP_RANGE="${RTP_RANGE:-10000-20000}"
SIP_PUBLIC="${SIP_PUBLIC:-0}"
TAG="nimbora-lab"
RTP_PORTS="${RTP_RANGE/-/:}"

command -v iptables >/dev/null || { echo "iptables manquant" >&2; exit 1; }

# Remove every rule carrying our comment from a chain (table, chain).
flush_tagged() {
    local table=$1 chain=$2 rule
    # grep exits 1 when the chain holds none of our rules (first run): not an error.
    { iptables -t "$table" -S "$chain" 2>/dev/null | grep -- "--comment $TAG" || true; } | sed 's/^-A /-D /' |
    while read -r rule; do
        # shellcheck disable=SC2086
        iptables -t "$table" $rule
    done
}

# Docker creates DOCKER-USER when it starts; create it ourselves if Docker is
# not up yet, Docker reuses an existing chain.
iptables -N DOCKER-USER 2>/dev/null || true
iptables -C FORWARD -j DOCKER-USER 2>/dev/null || iptables -I FORWARD 1 -j DOCKER-USER

flush_tagged filter DOCKER-USER
flush_tagged nat PREROUTING

rules=(
    "-i $INCUS_BRIDGE -j ACCEPT"
    "-o $INCUS_BRIDGE -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
    "-i $PUBLIC_IF -o $INCUS_BRIDGE -d $PBX_IP -p udp --dport $RTP_PORTS -j ACCEPT"
)
if [[ "$SIP_PUBLIC" == "1" ]]; then
    rules+=(
        "-i $PUBLIC_IF -o $INCUS_BRIDGE -d $PBX_IP -p udp --dport 5060 -j ACCEPT"
        "-i $PUBLIC_IF -o $INCUS_BRIDGE -d $PBX_IP -p tcp -m multiport --dports 5060,5061 -j ACCEPT"
    )
fi
rules+=(
    "-i $NIMBORA_BRIDGE -o $INCUS_BRIDGE -d $PBX_IP -j ACCEPT"
    "-i $TRAEFIK_BRIDGE -o $INCUS_BRIDGE -d $PBX_IP -p tcp --dport 443 -j ACCEPT"
    "-i $NIMBORA_BRIDGE -o $TRAEFIK_BRIDGE -p tcp -m multiport --dports 80,443 -j ACCEPT"
    "-o $INCUS_BRIDGE -j DROP"
)
# Insert at position 1 in reverse order so the chain reads in the order above.
for ((i = ${#rules[@]} - 1; i >= 0; i--)); do
    # shellcheck disable=SC2086
    iptables -I DOCKER-USER 1 ${rules[i]} -m comment --comment "$TAG"
done

nat=(
    "-i $PUBLIC_IF -p udp --dport $RTP_PORTS -j DNAT --to-destination $PBX_IP"
)
if [[ "$SIP_PUBLIC" == "1" ]]; then
    nat+=(
        "-i $PUBLIC_IF -p udp --dport 5060 -j DNAT --to-destination $PBX_IP"
        "-i $PUBLIC_IF -p tcp -m multiport --dports 5060,5061 -j DNAT --to-destination $PBX_IP"
    )
fi
for ((i = ${#nat[@]} - 1; i >= 0; i--)); do
    # shellcheck disable=SC2086
    iptables -t nat -I PREROUTING 1 ${nat[i]} -m comment --comment "$TAG"
done

echo "nimbora-lab-firewall: ${#rules[@]} règles DOCKER-USER, ${#nat[@]} redirections vers $PBX_IP (SIP public : $SIP_PUBLIC)"
