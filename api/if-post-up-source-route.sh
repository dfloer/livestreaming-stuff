#!/bin/bash -e
#this script requires a routing table named $IFACE (ie. bond0) exists in /etc/iproute2/rt_tables
#the $IFACE routing table is used to place the default route in for the source routing table
#ip route list table $IFACE will list the routing table for this interface

IFACE=$1
set -x

set_netinfo() {
  NETWORK=$(ip route show dev $IFACE | grep -v default | head -n 1 | awk '{print $1}')
  GATEWAY=$(ip route show dev $IFACE default | head -n 1 | awk '{print $3}')
}

if [ -z "$IFACE" ]; then
  if [[ $2 == "up" || $2 == "dhcp4-change" ]]; then
    IFACE=$1
  else
    exit 1
  fi
fi

set_netinfo
ip rule del lookup "$IFACE" || true
ip route flush table "$IFACE"
ip route add "$NETWORK" dev "$IFACE" proto kernel scope link table "$IFACE"
ip route add default via "$GATEWAY" dev "$IFACE" table "$IFACE"
ip rule add from "$NETWORK" lookup "$IFACE"
