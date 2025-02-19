#!/usr/bin/env python

from nornir import InitNornir
from nornir.core.task import Result
from nornir.core.inventory import Group
from nornir_netmiko.tasks import netmiko_send_command
from nornir_utils.plugins.functions import print_result
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
********************** WORK IN PROGRESS **********************

Usage examples:

../scripts/lab_reset.py --min_cfg min_cfg
../scripts/lab_reset.py --min_cfg min_cfg --node p2
../scripts/lab_reset.py --min_cfg min_cfg --role pe
../scripts/lab_reset.py --min_cfg min_cfg --dry_run=False
../scripts/lab_reset.py --min_cfg min_cfg --replace=True

Note:
- task is skipped when required jinja2 file does not exist

TODO:
- if --min_cfg is not provided, deploy minimal mgmt config defined within the script below
- save current config before "commit replace" -> ./config_backups/<hostname>_<date:time>.txt

"""

def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min_cfg", help="Folder with minimal config templates for each device role.", required=True)
    parser.add_argument(
        "--dry_run",
        help="True (default): show tentative config diffs / False: apply config to devices.",
        choices=['False', 'True'],
        default='True')
    parser.add_argument("--role", help="Configure only devices of specific role, such as 'pe'.", required=False)
    parser.add_argument("--node", help="Configure only selected device, such as 'rr1'.", required=False)
    parser.add_argument("--replace", help="Replace current configuration ***** DANGER: ensure correct mgmt IP and credentials! *****", required=False, default='False')
    return parser



def generate_config(task, section, role, t_file, inv):

    task.host["config"] = None

    # print(f"generate_config: {section}, {role}, {t_file}, {service}, {instance}\n")

    config = task.run(
        task=template_file,
        template=t_file,
        path=f"templates/{section}",
        node=task.host.name,
        jinja_env=jinja_env,
        master=inv,
        severity_level=logging.DEBUG,  # comment this line out, if you want to see rendered config (already shown by napalm diffs below..)
    )
    task.host["config"] = config.result
    # print(config.result)
    return Result(
        host=task.host,
        result=f"{section} configuration generated for {task.host.name} in role of {role} (check for any napalm diffs below).",
    )


def apply_config(task, inv, section, role=None, dry_run=True, replace=False):

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
                inv=inv
            )
            if task.host["config"]:
                task.run(task=napalm_configure, configuration=task.host["config"], dry_run=dry_run, replace=replace)
                task.host.close_connections()

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

    if args.role:
        nr = nr.filter(F(device_role__contains=args.role))
    if args.node:
        nr = nr.filter(name=args.node)

    results = nr.run(task=apply_config, inv=lab_inventory, section=args.min_cfg, role=args.role, dry_run=(args.dry_run == 'True'), replace=(args.replace == 'True'))

    print_result(results)

