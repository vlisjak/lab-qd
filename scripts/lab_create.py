#!/usr/bin/env python

import ipaddress
import os
import sys
from nested_dict import nested_dict
import utils
from box import Box
from copy import deepcopy
import argparse
import re
import pprint as pp
from collections import defaultdict

"""
TODO:
- improve dry_run: True/False --> --dry_run", dest="dry", action="store_true", help="Will not run on devices
"""


def parseArgs():
    parser = argparse.ArgumentParser()
    parser.set_defaults(feature=True)
    parser.add_argument(
        "-m",
        "--master",
        help="Master inventory file [default=master.yaml]",
        default="master.yaml",
        required=False,
    )
    return parser.parse_args()


def parse_link(link):
    """
    Extract (n1,if1,n2,if2) from user provided link in master.yaml, such as:
      links:
        p1---p2
        pe1:Gi0/0/0/2---pe2
        pe3:TenGig1/2---cpe1:Gig9/8

    Returns for each of above examples:
        (p1, None, p2, None)
        (pe1, Gi0/0/0/2, pe2, None)
        (pe3, TenGig1/2, cpe1, Gig9/8)
    """
    result = []
    for endpoint in link.split("---"):
        node_intf = endpoint.split(":")
        if len(node_intf) == 2:
            # endpoint = node:interface
            result.extend(node_intf)
        else:
            # endpoint = node
            result.extend([node_intf[0], None])

    return result


def exclude_manual_intf(links):
    """
    Users can manually define interface names in "links:" section of master.yaml, such as:
      links:
        p1---p2
        pe1:Gi0/0/0/9---pe2
        pe3:TenGig1/2---cpe1:Gig9/8

    This will allow to enforce some interfaces, for example interfaces on RRs always Gi0/0/0/9.
    Or, when we have a physical lab, we also want to define all lab interfaces manually.

    But then, the P2p_Intf_Allocator must avoid (exclude) these manually defined interfaces.

    Returns:
        for each node and interface type, identify a list of IDs (last integer after whatever interface string), eg:
            {'p1': defaultdict(<class 'list'>, {'Gi0/0/0/': [0]}),
            'p2': defaultdict(<class 'list'>,
                            {'Bundle-Ether': [10],
                                'Gi0/0/0/': [0, 100]}),
            'p3': defaultdict(<class 'list'>, {'Gi0/0/0/': [0]}),
            'p4': defaultdict(<class 'list'>, {'Gi0/0/0/': [0]}),
            'rr1': defaultdict(<class 'list'>, {'Gi0/0/0/': [9]}),
            'rr2': defaultdict(<class 'list'>, {'Gi0/0/0/': [9]})}
    """
    exclude_ids = defaultdict(lambda: defaultdict(list))

    for link in links:
        (n1, if1, n2, if2) = parse_link(link["link"])

        if if1:
            matches = re.match(r"(.+[^\d]+)(\d+)", if1)
            intf_type, intf_id = matches.group(1), int(matches.group(2))
            exclude_ids[n1][intf_type].append(intf_id)

        if if2:
            matches = re.match(r"(.+[^\d]+)(\d+)", if2)
            intf_type, intf_id = matches.group(1), int(matches.group(2))
            exclude_ids[n2][intf_type].append(intf_id)

    return exclude_ids


class P2p_Intf_Allocator:
    """
    Allocate (sequentially) last digit for XRD interface names, such as:
        Gi0/0/0/X (X=0,1,2,3..)
        Bundle-EthernetX (X=1,2,3..)

    Notes:
        - allocation is specific to interface_type and node
        - allocator will avoid manually defined interfaces in master.yaml (exclude_IDs)
    Usage:

        p2p_if_allocator = P2p_Intf_Allocator(exclude_IDs)

        intf_id1 = p2p_if_allocator.next("r1", "Gi0/0/0/", 0)
        intf_id1 = p2p_if_allocator.next("r1", "Gi0/0/0/", 0)
        intf_id1 = p2p_if_allocator.next("r1", "Bundle-Ethernet", 1)
        etc.
    """

    def __init__(self, excludeIDs=None):
        self.nodes = defaultdict(lambda: defaultdict(int))
        self.excludeIDs = excludeIDs or {}

    def __iter__(self):
        return self

    def __next__(self):
        raise NotImplementedError("Use next(node, interface, first_id) to get the next value for a specific node and interface.")

    def next(self, node: str, interface: str, first_id: int) -> int:
        current_id = self.nodes[node].get(interface, first_id)

        # Get excluded IDs for this node/interface
        excluded = self.excludeIDs.get(node, {}).get(interface, [])

        while current_id in excluded:
            current_id += 1

        self.nodes[node][interface] = current_id + 1
        return current_id


class Subnet_Allocator:
    """
    Allocate consecutive subnets from provided prefix and subnet length.

    Usage:

        subnet_allocator = Subnet_Allocator()

        subnet = subnet_allocator.next_subnet('1.0.0.0/16', 30)
        subnet = subnet_allocator.next_subnet('1.0.0.0/16', 30)
        subnet = subnet_allocator.next_subnet('1.255.0.0/16', 24)
        etc.
    """

    def __init__(self):
        self.subnet_iterators = {}

    def next_subnet(self, prefix, length):
        if prefix not in self.subnet_iterators:
            network = ipaddress.ip_network(prefix)
            self.subnet_iterators[prefix] = network.subnets(new_prefix=length)
        return next(self.subnet_iterators[prefix])


def get_bundle_id(node, neighbor, interfaces):
    """
    Compute Bundle ID between two nodes.

    Note: only one Bundle is allowed between any two nodes -> hence we can auto-assign
          all bundle members between these two nodes to respective Bundle
    """
    for intf, intf_details in interfaces.items():

        if intf_details.bundle.type == "bundle" and intf_details.lldp.neighbor == neighbor:
            matches = re.match(r"(.+[^\d]+)(\d+)", intf)
            intf_type, intf_id = matches.group(1), int(matches.group(2))
            return intf_id


def intf_ip_allocation(master_inherit_dotted):
    nodes_intf = Box(nested_dict(), default_box=True)
    clab_links = []
    subnet_allocator = Subnet_Allocator()
    excludeIDs = exclude_manual_intf(master_inherit_dotted.links)

    print("Manually defined interface names in master.yaml:")
    for exc_node, exc_node_details in excludeIDs.items():
        for exc_intf, excIDs in exc_node_details.items():
            print(f" {exc_node:8s} {exc_intf:15s} {excIDs}")

    p2p_if_allocator = P2p_Intf_Allocator(excludeIDs=excludeIDs)

    _allocate_p2p_links(master_inherit_dotted, nodes_intf, clab_links, p2p_if_allocator, subnet_allocator)
    _assign_loopback_and_mgmt(master_inherit_dotted, nodes_intf)
    _update_master_with_interfaces(master_inherit_dotted, nodes_intf)

    return master_inherit_dotted.to_dict(), {"links": clab_links}

def _allocate_p2p_links(master, nodes_intf, clab_links, if_allocator, subnet_allocator):
    for link in master.links:
        node1, if1, node2, if2 = parse_link(link.link)
        n1_dict, n2_dict = master.devices[node1], master.devices[node2]

        if "clab" not in n1_dict or "clab" not in n2_dict:
            continue

        intf_type1, first_id1 = _get_intf_type_and_id(n1_dict, link.link_group)
        intf_type2, first_id2 = _get_intf_type_and_id(n2_dict, link.link_group)

        if not if1:
            if1 = f"{intf_type1}{if_allocator.next(node1, intf_type1, first_id1)}"
        if not if2:
            if2 = f"{intf_type2}{if_allocator.next(node2, intf_type2, first_id2)}"

        clab_if1 = utils.clab_intf_map(n1_dict.clab.kind, if1) if n1_dict.get("clab_intf_map") else if1
        clab_if2 = utils.clab_intf_map(n2_dict.clab.kind, if2) if n2_dict.get("clab_intf_map") else if2

        # exclude interfaces such as Bundles, which can be defined in master.yaml (to be configured in IOS-XR by 
        # nornir), but not part of clab topology
        if not link.get("clab_exclude", False):
            clab_links.append({
                "endpoints": [
                    f"{node1 if node1 != 'host' else 'macvlan'}:{clab_if1}",
                    f"{node2 if node2 != 'host' else 'macvlan'}:{clab_if2}"
                ]
            })

        _add_interface_metadata(nodes_intf, node1, if1, node2, if2, link)
        _add_interface_metadata(nodes_intf, node2, if2, node1, if1, link)

        if "v4_prefix" in link:
            subnet = subnet_allocator.next_subnet(link["v4_prefix"], 30)
            ip1, ip2 = list(subnet.hosts())[:2]

            nodes_intf[node1].interfaces[if1].update({"ipv4_address": f"{ip1}/{subnet.prefixlen}"})
            nodes_intf[node2].interfaces[if2].update({"ipv4_address": f"{ip2}/{subnet.prefixlen}"})

            # also update our "lldp" entry (which proves handy in jinja templates)
            nodes_intf[node1].interfaces[if1].lldp.update({"neighbor_ipv4": f"{ip2}/{subnet.prefixlen}"})
            nodes_intf[node2].interfaces[if2].lldp.update({"neighbor_ipv4": f"{ip1}/{subnet.prefixlen}"})

def _get_intf_type_and_id(device_dict, link_group):
    naming = device_dict.intf_naming
    if link_group in naming:
        return naming[link_group].name, naming[link_group].first_id
    return naming.default.name, naming.default.first_id

def _add_interface_metadata(nodes_intf, node, ifname, neighbor, neighbor_if, link):
    intf = nodes_intf[node].interfaces[ifname]
    # print(node, ifname, neighbor, neighbor_if, link)
    intf["description"] = f"{node}:{ifname} -> {neighbor}:{neighbor_if}"
    intf.setdefault("lldp", {}).update({"neighbor": neighbor, "neighbor_intf": neighbor_if})
    for k, v in link.items():
        intf[k] = deepcopy(v)


def _assign_loopback_and_mgmt(master, nodes_intf):
    loop_prefix = ipaddress.ip_network(master.link_groups.loopback0.v4_prefix)
    mgmt_prefix = ipaddress.ip_network(master.link_groups.mgmt.v4_prefix)
    reserved_loop = [loop_prefix[1], loop_prefix[-2]]
    reserved_mgmt = [mgmt_prefix[1], mgmt_prefix[-2]]
    iter_loop = (ip for ip in loop_prefix.hosts() if ip not in reserved_loop)
    iter_mgmt = (ip for ip in mgmt_prefix.hosts() if ip not in reserved_mgmt)

    for node in nodes_intf:
        if master.devices[node].clab.kind == "host":
            nodes_intf[node].interfaces.mgmt.ipv4_address = master.devices[node].interfaces.mgmt.ipv4_address
            continue
        loop_name = f"{master.devices[node].intf_naming.loopback0.name}0"
        nodes_intf[node].interfaces[loop_name].update({
            "ipv4_address": f"{next(iter_loop)}/32",
            "description": f"{node} {loop_name}"
        })
        nodes_intf[node].interfaces.mgmt.ipv4_address = f"{next(iter_mgmt)}/{mgmt_prefix.prefixlen}"

def _update_master_with_interfaces(master, nodes_intf):
    for node, intfs in nodes_intf.items():
        for intf, details in intfs.interfaces.items():
            if intf in master.devices[node].interfaces:
                master.devices[node].interfaces[intf].update(details)
            else:
                master.devices[node].interfaces[intf] = details

        for intf, details in intfs.interfaces.items():
            if "bundle" in details:
                bundle_id = get_bundle_id(node, details.lldp.neighbor, intfs.interfaces)
                master.devices[node].interfaces[intf].bundle.id = bundle_id



def generate_clab_startup(master_complete_dotted, clab_links):
    """
    Generate clab_startup.yaml inventory.
    """
    # add mgmt prefix and docker subnet
    clab_startup = Box(nested_dict(), default_box=True)
    clab_startup.name = master_complete_dotted.clab_name
    clab_startup.mgmt.network = master_complete_dotted.clab_name
    clab_startup.mgmt["ipv4-subnet"] = master_complete_dotted.link_groups.mgmt.v4_prefix

    # add clab parameters for each device type
    for grp, group_details in master_complete_dotted.device_groups.items():
        if "clab" in group_details:
            clab_kind = group_details.clab.kind

            clab_startup.topology.kinds[clab_kind] = deepcopy(group_details.clab)

            if "image" in group_details.clab:
                clab_startup.topology.kinds[clab_kind].image = group_details.clab.image

            # Continerlab parameters
            # - use default clab credentials (clab/clab@123), because these are baked into xrv9k docker image!
            # - same reason for CLAB_MGMT_VRF (clab-mgmt)
            clab_startup.topology.kinds[clab_kind].env.CLAB_MGMT_VRF = "clab-mgmt"
            clab_startup.topology.kinds[clab_kind].env.USERNAME = group_details.username
            clab_startup.topology.kinds[clab_kind].env.PASSWORD = group_details.password

    for node, node_details in master_complete_dotted.devices.items():
        if "clab" in node_details:
            # add node type and mgmt_ip for each node
            clab_startup.topology.nodes[node].kind = node_details.clab.kind
            mgmt_ipv4 = node_details.interfaces.mgmt.ipv4_address
            clab_startup.topology.nodes[node]["mgmt-ipv4"] = str(ipaddress.ip_interface(mgmt_ipv4).ip)
            # TBD: add promisc mode cmd for external macvlan links on xrv9k/csr1000 (exec: ip link set Gi0-0-0-0 promisc on)

    # add all links for each node
    clab_startup.topology.links = clab_links["links"]

    return clab_startup.to_dict()


def generate_cml_startup(master_complete_dotted, clab_links):
    """
    TODO: Generate CML startup file.
    """


def generate_nornir_vars(master_complete_dotted):
    """
    Generate minimal nornir_groups.yaml and nornir_hosts.yaml inventory.
    """
    nornir_groups = Box(default_box=True)
    nornir_hosts = Box(default_box=True)
    nornir_config = Box(default_box=True)

    # nornir_groups.yaml
    for clab_grp, group_details in master_complete_dotted.device_groups.items():
        group = group_details.nornir.platform
        timeout = group_details.nornir.get('timeout', 30)
        nornir_groups[group].update({
            "platform": group_details.nornir.platform,
            "username": group_details.username,
            "password": group_details.password,
            "connection_options": {
                "netmiko": {
                    "extras": {
                        "conn_timeout": timeout,
                        "timeout": timeout,
                        "banner_timeout": timeout
                    }
                },
                "napalm": {
                    "extras": {
                        "optional_args": {
                            "conn_timeout": timeout,
                            "timeout": timeout,
                            "banner_timeout": timeout
                        }
                    }
                }
            }
        })

    # nornir_hosts.yaml
    for node, node_details in master_complete_dotted.devices.items():

        mgmt_ipv4 = node_details.interfaces.mgmt.ipv4_address
        nornir_hosts[node].hostname = str(ipaddress.ip_interface(mgmt_ipv4).ip)

        nornir_hosts[node].groups = [master_complete_dotted.devices[node].nornir.platform]
        nornir_hosts[node].data.device_roles = master_complete_dotted.devices[node].device_roles
        nornir_hosts[node].data.mgmt = deepcopy(master_complete_dotted.devices[node].interfaces.mgmt)

    # nornir_config.yaml
    nornir_config["inventory"] = deepcopy(master_complete_dotted.nornir_startup.inventory)
    nornir_config["runner"] = deepcopy(master_complete_dotted.nornir_startup.runner)
    nornir_config["logging"] = deepcopy(master_complete_dotted.nornir_startup.logging)

    return nornir_groups.to_dict(), nornir_hosts.to_dict(), nornir_config.to_dict()


if __name__ == "__main__":

    # os.chdir(sys.path[0])
    args = parseArgs()

    # User-defined lab inventory
    master = utils.load_vars(args.master)

    # Resolve "inherit_from:" blocks
    master_inherit = utils.resolve_inheritance(master)
    utils.save_inventory(master_inherit, "master_inherit.yaml")

    # Allow dotted notation to access nested objects
    master_inherit_dotted = Box(master_inherit)

    # Add interfaces for each node into master_inherit (auto allocate interface names and IPs)
    # -> in same function we also compute clab_links
    master_complete, clab_links = intf_ip_allocation(master_inherit_dotted)
    utils.save_inventory(master_complete, "master_complete.yaml")

    # Allow dotted notation to access nested objects
    master_complete_dotted = Box(master_complete, default_box=True)

    # Generate clab startup inventory
    clab_startup = generate_clab_startup(master_complete_dotted, clab_links)
    utils.save_inventory(clab_startup, "clab_startup/clab_startup.yaml")

    # Generate nornir inventory files
    nornir_groups, nornir_hosts, nornir_config = generate_nornir_vars(master_complete_dotted)
    utils.save_inventory(nornir_groups, "nornir/nornir_groups.yaml")
    utils.save_inventory(nornir_hosts, "nornir/nornir_hosts.yaml")
    utils.save_inventory(nornir_config, "nornir/nornir_config.yaml")

    # Generate Drawio topology diagram - only clab links (eg. Bundles are not included ..
    # TODO: I guess I need to improve this so we draw all links
    utils.create_network_diagram(clab_links["links"], master_complete_dotted)

    # Create vlan subinterfaces in the host, for clab nodes data links with physical routers
    # https://github.com/vlisjak/lab-qd?tab=readme-ov-file#connect-data-interface-from-clab-node-to-physical-router-macvlan
    utils.create_clab2host_vlans(clab_links=clab_links["links"])
