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
        if excludeIDs is None:
            excludeIDs = {}
        self.nodes = defaultdict(lambda: defaultdict(int))
        self.excludeIDs = excludeIDs

    def __iter__(self):
        return self

    def __next__(self):
        raise NotImplementedError("Use next(node, interface, first_id) to get the next value for a specific node and interface.")

    def next(self, node, interface, first_id):
        if node not in self.nodes or interface not in self.nodes[node]:
            self.nodes[node][interface] = first_id

        next_id = self.nodes[node][interface]

        # Get the list of excluded IDs for the specific node and interface
        node_exclude_ids = self.excludeIDs.get(node, defaultdict(list))
        interface_exclude_ids = node_exclude_ids.get(interface, [])

        while next_id in interface_exclude_ids:
            next_id += 1

        self.nodes[node][interface] = next_id + 1
        return next_id


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
    """
    Generate interfaces inventory: auto allocate interface IDs and IP subnets
     - p2p links (core and access)
     - loopback0s
     - mgmt

    Returns:
      - nodes_intf: dict of all interfaces/IPs for each node
      - clab_links: topology entries for clab_startup.yaml

    TODO: this function is way too long - need to refactor..
    """

    # interfaces and IP addresses for each node
    nodes_intf = Box(nested_dict(), default_box=True)

    # only links that will be created by clab (eg. Bundles are excluded)
    clab_links = []

    # We will auto-allocate /30 subnets for p2p links
    subnet_allocator = Subnet_Allocator()

    # We will auto-allocate interface names, except for those manually defined in master.yaml->links
    excludeIDs = exclude_manual_intf(master_inherit_dotted.links)
    print(f"Manually defined interface names in master.yaml:")
    for exc_node, exc_node_details in excludeIDs.items():
        for exc_intf, excIDs in exc_node_details.items():
            print(f"   {exc_node:8s} {exc_intf:15s} {excIDs}")

    p2p_if_allocator = P2p_Intf_Allocator(excludeIDs=excludeIDs)

    # handle p2p core and access links
    # - parallel links are allowed
    # - if intf name is manually defined in master.yaml
    #      -> do not autoallocate
    #      -> do translate router intf name to clab name, if clab_startup->[device_type]->clab_intf->re_sub exists
    #      -> do auto-allocate IP address (if prefix for that link exists .. inherited from link_group)
    for link in master_inherit_dotted.links:

        # link example:{ link: pe1:Gi0/0/0/9---p1, inherit_from: link_groups.core }
        (node1, full_ifname1, node2, full_ifname2) = parse_link(link.link)

        # if both nodes are clab devices, we can (unless intf manually defined in master.yaml) auto-allocate intf names and IPs
        # - else: we assume that user wants to provision physical lab, so interface names for both
        #         nodes must be provided in master.yaml (and this entry will not get in clab_links)
        # TODO: shall we create clab links in separate function?
        #       - with an argument: list of interface names that must be excluded from clab?
        n1_dict = master_inherit_dotted.devices[node1]
        n2_dict = master_inherit_dotted.devices[node2]

        if "clab" in n1_dict and "clab" in n2_dict:

            # loopkup interface name and first_id for specific link_group (such as Bundle-Ether), else return default (such as Gi0/0/0/)
            intf_naming1 = n1_dict.intf_naming
            intf_naming2 = n2_dict.intf_naming

            if link.link_group in intf_naming1:
                intf_type1 = intf_naming1[link.link_group].name
                intf_first_id1 = intf_naming1[link.link_group].first_id
            else:
                intf_type1 = intf_naming1.default.name
                intf_first_id1 = intf_naming1.default.first_id

            if link.link_group in intf_naming2:
                intf_type2 = intf_naming2[link.link_group].name
                intf_first_id2 = intf_naming2[link.link_group].first_id
            else:
                intf_type2 = intf_naming2.default.name
                intf_first_id2 = intf_naming2.default.first_id

            # intf1 was not provided in master.yaml -> auto-allocate
            if not full_ifname1:
                intf_id1 = p2p_if_allocator.next(node1, intf_type1, intf_first_id1)  # eg. 4
                full_ifname1 = f"{intf_type1}{intf_id1}"  # eg. Gi0/0/0/4

            # intf2 was not provided in master.yaml -> auto-allocate
            if not full_ifname2:
                intf_id2 = p2p_if_allocator.next(node2, intf_type2, intf_first_id2)  # eg. 4
                full_ifname2 = f"{intf_type2}{intf_id2}"  # eg. Gi0/0/0/4

            clab1 = master_inherit_dotted.devices[node1].clab
            clab2 = master_inherit_dotted.devices[node2].clab

            if "clab_intf_map" in n1_dict and n1_dict.clab_intf_map == True:
                clab_ifname1 = utils.clab_intf_map(clab1.kind, full_ifname1)
            else:
                clab_ifname1 = full_ifname1

            if "clab_intf_map" in n2_dict and n2_dict.clab_intf_map == True:
                clab_ifname2 = utils.clab_intf_map(clab2.kind, full_ifname2)
            else:
                clab_ifname2 = full_ifname2

            # clab_startup.yaml expects the following topology structure:
            # links:
            # - endpoints:
            #     - p1:Gi0-0-0-0
            #     - p2:Gi0-0-0-0
            # - endpoints:
            #     - p2:Gi0-0-0-1
            #     - p3:Gi0-0-0-0

            # We must not include Bundle-Ether in clab startup (marked with 'clab_exclude' in master.yaml)
            if link.get("clab_exclude", False):
                print("Link excluded from clab:", f"{node1}:{clab_ifname1}", f"{node2}:{clab_ifname2}")
                pass
            else:
                clab_n1 = "macvlan" if node1 == "host" else node1
                clab_n2 = "macvlan" if node2 == "host" else node2
                clab_links.append(
                    {
                        "endpoints": [
                            f"{clab_n1}:{clab_ifname1}",
                            f"{clab_n2}:{clab_ifname2}",
                        ]
                    }
                )
            # TBD: add extended link defintion for macvlan links on xrv9k, with passthru

        # now add interfaces also in master_complete.yaml
        nodes_intf[node1].interfaces[full_ifname1] = {
            "description": f"{node1}:{full_ifname1} -> {node2}:{full_ifname2}",
        }
        nodes_intf[node2].interfaces[full_ifname2] = {
            "description": f"{node2}:{full_ifname2} -> {node1}:{full_ifname1}",
        }

        # copy all parameters from master_inherit.yaml->interfaces into master_complete.yaml
        for k, v in link.items():
            nodes_intf[node1].interfaces[full_ifname1][k] = deepcopy(v)
            nodes_intf[node2].interfaces[full_ifname2][k] = deepcopy(v)

        # add lldp-like entry for each interface
        # - note: we must not overwrite 'lldp' dict which might be inherited from link_group - hence .update()
        if "lldp" not in nodes_intf[node1].interfaces[full_ifname1]:
            nodes_intf[node1].interfaces[full_ifname1].lldp = {}

        if "lldp" not in nodes_intf[node2].interfaces[full_ifname2]:
            nodes_intf[node2].interfaces[full_ifname2].lldp = {}

        nodes_intf[node1].interfaces[full_ifname1].lldp.update({"neighbor": f"{node2}", "neighbor_intf": f"{full_ifname2}"})
        nodes_intf[node2].interfaces[full_ifname2].lldp.update({"neighbor": f"{node1}", "neighbor_intf": f"{full_ifname1}"})

        # allocate new /30 for p2p links from 'prefix' (inherited from respective link_group)
        # -> if prefix attrinute is not present, we assume it is a l2 link (or a Bundle member) so IP is not be allocated
        if "prefix" in link:
            subnet = subnet_allocator.next_subnet(link["prefix"], 30)
            ip1, ip2 = list(subnet.hosts())[:2]

            nodes_intf[node1].interfaces[full_ifname1].update({"ipv4_address": f"{ip1}/{subnet.prefixlen}"})
            nodes_intf[node2].interfaces[full_ifname2].update({"ipv4_address": f"{ip2}/{subnet.prefixlen}"})

            # also update our "lldp" entry (which proves handy in jinja templates)
            nodes_intf[node1].interfaces[full_ifname1].lldp.update({"neighbor_ipv4": f"{ip2}/{subnet.prefixlen}"})
            nodes_intf[node2].interfaces[full_ifname2].lldp.update({"neighbor_ipv4": f"{ip1}/{subnet.prefixlen}"})

    # add Loopabck0 and mgmt_ip to all nodes
    prefix_loop = ipaddress.ip_network(master_inherit_dotted.link_groups.loopback0.prefix)
    prefix_mgmt = ipaddress.ip_network(master_inherit_dotted.link_groups.mgmt.prefix)

    # exclude .1 and .254 which may be used by docker
    reserved_loop = [
        prefix_loop[1],
        prefix_loop[-2],
    ]
    # MgmtEth using the same last digit as Loopback0
    reserved_mgmt = [
        prefix_mgmt[1],
        prefix_mgmt[-2],
    ]

    iter_loop = (host for host in prefix_loop.hosts() if host not in reserved_loop)
    iter_mgmt = (host for host in prefix_mgmt.hosts() if host not in reserved_mgmt)

    for node in nodes_intf:
        if master_inherit_dotted.devices[node].clab.kind == "host":
            nodes_intf[node].interfaces.mgmt.ipv4_address = master_inherit_dotted.devices[node].interfaces.mgmt.ipv4_address
            continue
        loop0_name = f"{master_inherit_dotted.devices[node].intf_naming.loopback0.name}0"
        nodes_intf[node].interfaces[loop0_name].ipv4_address = f"{str(next(iter_loop))}/32"
        nodes_intf[node].interfaces[loop0_name].description = f"{node} {loop0_name}"
        nodes_intf[node].interfaces.mgmt.ipv4_address = f"{str(next(iter_mgmt))}/{prefix_mgmt.prefixlen}"

    for node, intf_list in nodes_intf.items():
        # finally copy all interface parameters/IPs into master_inherit, which is returned as result
        # - must preserve parameters previously inherited from device/link groups
        for intf, intf_details in intf_list.interfaces.items():
            if intf in master_inherit_dotted.devices[node].interfaces:
                master_inherit_dotted.devices[node].interfaces[intf].update(intf_details)
            else:
                master_inherit_dotted.devices[node].interfaces.update({intf: intf_details})

        # and assign bundle_members to respective Bundle (note: a single Bundle is allowed between any pair of nodes)
        for intf, intf_details in intf_list.interfaces.items():
            if "bundle" in intf_details:
                bundle_id = get_bundle_id(node, intf_details.lldp.neighbor, intf_list.interfaces)
                master_inherit_dotted.devices[node].interfaces[intf].bundle.id = bundle_id

    # return master_inherit that we received as function argument, now enriched with device ineterfaces -> becomes master_complete.yaml
    return master_inherit_dotted.to_dict(), {"links": clab_links}


def generate_clab_startup(master_complete_dotted, clab_links):
    """
    Generate clab_startup.yaml inventory.
    """
    # add mgmt prefix and docker subnet
    clab_startup = Box(nested_dict(), default_box=True)
    clab_startup.name = master_complete_dotted.clab_name
    clab_startup.mgmt.network = master_complete_dotted.clab_name
    clab_startup.mgmt["ipv4-subnet"] = master_complete_dotted.link_groups.mgmt.prefix

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
    for grp, group_details in master_complete_dotted.device_groups.items():
        group = group_details.nornir.group
        nornir_groups[group].platform = group_details.nornir.platform
        nornir_groups[group].username = group_details.username
        nornir_groups[group].password = group_details.password

    # nornir_hosts.yaml
    for node, node_details in master_complete_dotted.devices.items():

        mgmt_ipv4 = node_details.interfaces.mgmt.ipv4_address
        nornir_hosts[node].hostname = str(ipaddress.ip_interface(mgmt_ipv4).ip)

        nornir_hosts[node].groups = [master_complete_dotted.devices[node].nornir.group]
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
