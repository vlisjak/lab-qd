#!/usr/bin/env python

from nornir import InitNornir
from nornir.core.task import Result
from nornir.core.inventory import Group
from nornir_utils.plugins.functions import print_result
# from nornir_netmiko.tasks import netmiko_send_config
from nornir_napalm.plugins.tasks import napalm_get, napalm_configure
from nornir_jinja2.plugins.tasks import template_string, template_file
from nornir.core.filter import F
import os
import sys
from jinja2 import Environment
import logging
import utils
from box import Box
import argparse
import pprint as pp

"""
Usage examples:

.../scripts/lab_configure.py network --sections day0
../scripts/lab_configure.py network --sections day0 --node p2
../scripts/lab_configure.py network --sections day0 --dry_run=False

../scripts/lab_configure.py network --sections isis
../scripts/lab_configure.py network --sections isis --node p2
../scripts/lab_configure.py network --sections isis --dry_run=False

../scripts/lab_configure.py network --sections srte
../scripts/lab_configure.py network --sections srte --node p2
../scripts/lab_configure.py network --sections srte --dry_run=False

../scripts/lab_configure.py network --sections ibgp
../scripts/lab_configure.py network --sections ibgp --node rr1_top
../scripts/lab_configure.py network --sections ibgp --node pe1
../scripts/lab_configure.py network --sections ibgp --dry_run=False

../scripts/lab_configure.py network --sections day0,isis,ibgp --dry_run=False
../scripts/lab_configure.py network --sections isis,day0 --dry_run=True --role pe
../scripts/lab_configure.py network --sections ibgp --node rr1
../scripts/lab_configure.py network --sections isis,srte --dry_run=True --node rr1 --role pce

../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1002_B

../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001 --dry_run False
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1002_B --dry_run False

../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001 --endpoints cpe1
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001 --endpoints cpe2,cpe3

Common behavior:
- task is skipped when required jinja2 file does not exist
"""


def parseArgs():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", help='Select command')

    network = subparsers.add_parser('network', help='Configure network infrastructure.')
    network.add_argument("--sections", help="Render jinja2 templates for sections, such as: day0[,isis,bgp,..]", required=True)
    network.add_argument(
        "--dry_run",
        help="True (default): show tentative config diffs / False: apply config to devices",
        choices=["False", "True"],
        default="True")
    network.add_argument("--role", help="Render jinja2 templates only for specific role, such as 'pe'.", required=False)
    network.add_argument("--node", help="Render jinja2 templates only for specific host, such as 'rr1'.", required=False)

    service = subparsers.add_parser('service', help='Configure service instances.')
    service.add_argument("--kind", help="Kind of network service, such as 'l3vpn'.", required=True)
    service.add_argument(
        "--dry_run",
        help="True (default): show tentative config diffs / False: apply config to devices",
        choices=["False", "True"],
        default="True")
    service.add_argument(
        "--instance", help="Render network service only for specific service instance, such as 'vrf_1001'.", required=True
    )
    service.add_argument(
        "--endpoints",
        help="Render only specific endpoints of network service, such as 'cpe1' (cpe and pe side is rendered).",
        required=False,
    )
    service.add_argument("--role", help="Render jinja2 templates only for specific role, such as 'pe'.", required=False)

    return parser



def generate_config(task, section, role, t_file, inv, service, instance, trans_scope):

    task.host["config"] = None

    # print(f"generate_config: {section}, {role}, {t_file}, {service}, {instance}\n")

    config = task.run(
        task=template_file,
        template=t_file,
        path=f"templates/{section}",
        node=task.host.name,
        jinja_env=jinja_env,
        master=inv,
        service=service,
        instance=instance,
        trans_scope=trans_scope,
        severity_level=logging.DEBUG,  # comment this line out, if you want to see rendered config (already shown by napalm diffs below..)
    )
    task.host["config"] = config.result
    # print(config.result)
    return Result(
        host=task.host,
        result=f"{section} configuration generated for {task.host.name} in role of {role} (check for any napalm diffs below).",
    )


def apply_config(task, inv, section, role=None, dry_run=True, service=None, instance=None, trans_scope=None):

    if role:
        roles_to_apply = [role]
    else:
        roles_to_apply = inv.devices[task.host.name].device_roles

    # device_roles is an array because eg. RR can also have the role of PCE - by default we apply all roles
    for role in roles_to_apply:
        # we only apply the template that indeed exists
        t_file = f"{section}_{role}_{task.host.platform}.j2"
        if os.path.isfile(f"templates/{section}/{t_file}"):
            task.run(
                task=generate_config,
                section=section,
                role=role,
                t_file=t_file,
                inv=inv,
                service=service,
                instance=instance,
                trans_scope=trans_scope,
            )
            if task.host["config"]:
                task.run(task=napalm_configure, configuration=task.host["config"], dry_run=dry_run)


def get_trans_scope(inv, service, instance, cpe):
    """
    Nornir will by default try to deploy config to all nodes in the inventory -> this is no good with large networks.
    We really want to target nornir only to those PEs, that are subject to change in this transaction.

    Logic for L3VPN instances:
    - if CPE has manually defined "uplinks, we respect these: 'services[service][instance].endpoints[cpe].uplinks'
    - otherwise, we collect all PEs "seen" over CPE's links, that match our service flavor: eg. 'inv.devices[cpe].interfaces.link_group' == 'l3vpn'

    Result: list of LLDP-like dicts:

    [
    {'cpe': 'cpe1', 'cpe_intf': 'Gi0/0/0/0', 'pe': 'pe1', 'pe_intf': 'Gi0/0/0/2'},
    {'cpe': 'cpe2', 'cpe_intf': 'Gi0/0/0/1', 'pe': 'pe3', 'pe_intf': 'Gi0/0/0/2'},
    {'cpe': 'cpe3', 'cpe_intf': 'Gi0/0/0/0', 'pe': 'pe2', 'pe_intf': 'Gi0/0/0/3'}
    ]

    Note that other service types may require different structure for transaction scope
      -> hence the need per-service handling in get_trans_scope function
    """

    # Computation of transaction scope is service-specific (eg. service may only need PE config - no CPEs)
    if service in ("l3vpn", "l2vpn"):
        links = []

        # if "uplinks" is manually defined in service instance:
        if "uplinks" in inv.services[service][instance].endpoints[cpe]:
            for uplink in inv.services[service][instance].endpoints[cpe].uplinks:
                uplink_lldp = inv.devices[cpe].interfaces[uplink].lldp
                links.append(
                    Box({"cpe": cpe, "cpe_intf": uplink, "pe": uplink_lldp.neighbor, "pe_intf": uplink_lldp.neighbor_intf})
                )

        # otherwise, include all neighbor PEs where link_group matches service type (eg. l3vpn)
        else:
            for intf, intf_det in inv.devices[cpe].interfaces.items():
                if "link_group" in intf_det and intf_det.link_group == service:
                    links.append(
                        Box({"cpe": cpe, "cpe_intf": intf, "pe": intf_det.lldp.neighbor, "pe_intf": intf_det.lldp.neighbor_intf})
                    )
        return links

    elif service == "eg:l3vpn_unmanaged_cpe":
        # TODO: implement for each service type
        pass

    else:
        print(f"Please add the code for Nornir scope for service {service} in function {get_trans_scope.__name__}... exiting!")
        exit(1)


if __name__ == "__main__":

    parser = parseArgs()
    args = parser.parse_args()
    # os.chdir(sys.path[0])

    master_complete = utils.load_vars("master_complete.yaml")
    # allow dotted dict notation
    lab_inventory = Box(master_complete)

    jinja_env = Environment(trim_blocks=True, lstrip_blocks=True)
    jinja_env.filters["regex_search"] = utils.regex_search
    jinja_env.filters["ipv4_to_isis_net"] = utils.ipv4_to_isis_net
    jinja_env.filters["cidr_to_legacy"] = utils.cidr_to_legacy

    nr = InitNornir(config_file="nornir/nornir_config.yaml")

    # ----- MAIN CHOICE 1: are we applying infrastructure config sections, such as: day0, isis, ibgp
    if args.cmd == 'network':
        if args.role:
            nr = nr.filter(F(device_role__contains=args.role))
        if args.node:
            nr = nr.filter(name=args.node)
        for section in args.sections.split(","):
            results = nr.run(
                task=apply_config, inv=lab_inventory, section=section, role=args.role, dry_run=(args.dry_run == "True")
            )
            print_result(results)

    # ----- MAIN CHOICE 2: Are we deploying network service instance, such as l3vpn/vrf_1001
    # ----- Note: computation of transaction scope is service-specific (eg. service may only need PE config - no CPEs)
    #             and is defined in function get_trans_scope()
    elif args.cmd == 'service':

        if args.kind not in lab_inventory.services:
            print(f"{args.kind} service does not exist in inventory.. exiting.")
            exit(1)

        if not args.instance:
            # service instance must be provided as script argument
            parser.print_help()
            exit(1)

        if args.instance not in lab_inventory.services[args.kind]:
            print(f"{args.instance} does not exist in {args.kind}.. exiting.")
            exit(1)

        if args.role:
            nr = nr.filter(F(device_role__contains=args.role))

        # determine CPEs to configure (either defined by args.endpoints or all endpoints in services/l3vpn/instance)
        cpe_list = set()
        if args.endpoints:
            for cpe in args.endpoints.split(","):
                if cpe in lab_inventory.services[args.kind][args.instance].endpoints:
                    cpe_list.add(cpe)
                else:
                    print(f"CPE {cpe} not found as endpoint in {args.kind}->{args.instance} ... skipping.")
        else:
            # we'll configure all CPEs from this service instance
            cpe_list.update([ep for ep in lab_inventory.services[args.kind][args.instance].endpoints])

        # nothing to do ..
        if len(cpe_list) == 0:
            print(f"No valid endpoint provided for {args.kind}/{args.instance} ... exiting.")
            exit(1)

        # print(cpe_list)

        # Compute LLDP-like list of CPE-PE links for chosen CPEs - needed for two reasons:
        #  - select subset of nornir cpe/pe nodes that are in the scope of this transaction (nr.filter)
        #  - pass the list to jinja, so during each render jinja knows which CPE downlinks are to be configured in this transaction
        # Note: each CPE can peer with one or two PEs
        lldp = []
        for cpe in cpe_list:
            lldp.extend(get_trans_scope(inv=lab_inventory, service=args.kind, instance=args.instance, cpe=cpe))

        pp.pprint(lldp)

        # extract subset of nornir nodes to be provisioned in this transaction
        # -> we could simply loop sequentially all CPEs and respective PEs (in above for loop),
        #    but that is much slower than parallel execution by nornir
        target_nodes = {d.cpe for d in lldp} | {d.pe for d in lldp}
        print(target_nodes)

        nr_hosts = nr.filter(F(name__in=target_nodes))

        # print(nr_hosts.inventory.hosts)

        # finally we can apply service instance (subset of CPEs) to target nodes
        # -> jinja for each node must understand if it needs to render anything, ie. what service/instance/cpe/uplink is in scope of this run
        results = nr_hosts.run(
            task=apply_config,
            inv=lab_inventory,
            section=args.kind,
            role=args.role,
            dry_run=(args.dry_run == "True"),
            service=args.kind,
            instance=args.instance,
            trans_scope=lldp,
        )
        print_result(results)

    # Nothing to do ... :)
    else:
        parser.print_help()
        exit(1)
