#!/usr/bin/env python

"""
Usage examples:

../scripts/lab_reset.py --h
../scripts/lab_reset.py --dry --node p2
../scripts/lab_reset.py --dry --role pe
../scripts/lab_reset.py --commit --node p2
../scripts/lab_reset.py --templ_dir ./templates/my_day0_config --dry --node p2
../scripts/lab_reset.py --nornir_cfg ./nornir/nornir_config.yaml --templ_dir ./templates/min_cfg --dry --node p2

Expected inputs:

./master_complete.yaml
./nornir/nornir_config.yaml
./templates/min_cfg/
    ├── BASE_ios.j2
    ├── BASE_iosxr.j2
    ├── cpe_ios.j2
    ├── cpe3.txt
    ├── cpe_iosxr.j2
    ├── pe_iosxr.j2
    ├── p_iosxr.j2
    ├── p1.txt
    ├── rr_iosxr.j2
    └── etc.

Notes:
- jinja2 templates get the name and IP address of MgmtEth interface from master_complete.yaml (lab-qd inventory)
- if a static (hardcoded) device configuration file (<hostname>.txt) exists, respective device_role .j2 is ignored
    - this is handy for devices that are not part of lab-qd inventory, or completely standalone lab setup (without any yaml inventory)
    - just make sure that hostname and MgmtEth IP address in the config file is indeed correct!

TODO:
- save current config before "commit replace" -> ./config_backups/<hostname>_<date:time>.txt
- DONE: lab_create.py should embed mgmth Eth interface name into nornir_hosts.yaml -> then lab_reset.py does not need master_complete.yaml for basic day0 config
"""

from nornir import InitNornir
from nornir.core.task import Result
from nornir.core.inventory import Group
from nornir_netmiko.tasks import netmiko_send_command
from nornir_utils.plugins.functions import print_result
from nornir_napalm.plugins.tasks import napalm_get, napalm_configure
from nornir_jinja2.plugins.tasks import template_string, template_file
from nornir.core.filter import F
import os
from jinja2 import Environment
import logging
import utils
from box import Box
import argparse


def parseArgs():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument(
        "--templ_dir", help="Directory with templates or configs [./templates/min_cfg]", default="./templates/min_cfg", required=False
    )
    parser.add_argument(
        "--nornir_cfg", help="Nornir configuration file [./nornir/nornir_config.yaml]", default="./nornir/nornir_config.yaml", required=False
    )
    dry_parser = parser.add_mutually_exclusive_group(required=True)
    dry_parser.add_argument("--dry", dest="dry_run", action="store_true", help="Show the diffs, but do not push the config to devices.")
    dry_parser.add_argument("--commit", dest="dry_run", action="store_false", help="Commit the config to devices!")
    parser.set_defaults(dry_run=True)
    parser.add_argument("--role", help="Configure only devices of specific role, such as 'pe'.", required=False)
    parser.add_argument("--node", help="Configure only selected device, such as 'rr1'.", required=False)
    return parser


def generate_config(task, templ_dir, t_file, role):

    task.host["config"] = None

    config = task.run(
        task=template_file,
        template=t_file,
        path=templ_dir,
        node=task.host.name,
        node_inv=task.host.data,
        severity_level=logging.DEBUG,  # comment this line out, if you want to see rendered config (already shown by napalm diffs below..)
    )
    task.host["config"] = config.result

    return Result(
        host=task.host,
        result=f"% Configuration for node {task.host.name} [role {role}] generated from template {templ_dir}/{t_file}.",
    )


def apply_config(task, templ_dir, role=None, dry_run=True, replace=True):

    roles_to_apply = [role] if role else task.host["device_roles"]

    for role in roles_to_apply:
        # first check if we have per-device hardcoded configuration file
        if os.path.isfile(f"{templ_dir}/{task.host.name}.txt"):
            with open(f"{templ_dir}/{task.host.name}.txt", "r") as cfg_file:
                node_config = cfg_file.read()
                task.run(task=napalm_configure, configuration=node_config, dry_run=dry_run, replace=replace)
                task.host.close_connections()
        # otherwise try jinja2 template for given device-role
        elif os.path.isfile(f"{templ_dir}/{role}_{task.host.platform}.j2"):
            templ_file = f"{role}_{task.host.platform}.j2"
            task.run(task=generate_config, templ_dir=templ_dir, t_file=templ_file, role=role)
            if task.host["config"]:
                task.run(task=napalm_configure, configuration=task.host["config"], dry_run=dry_run, replace=replace)
                task.host.close_connections()
        # else fail...
        else:
            exit(f"% Could not open jinja template: {templ_dir}/{templ_file} nor config file: {templ_dir}/{task.host.name}.txt.")


if __name__ == "__main__":

    parser = parseArgs()
    args = parser.parse_args()

    try:
        nr = InitNornir(config_file=args.nornir_cfg)
    except:
        exit(f"% Could not open Nornir configuration file: {args.nornir_cfg}")

    if args.role:
        nr = nr.filter(F(device_roles__contains=args.role))
    if args.node:
        nr = nr.filter(name=args.node)

    if nr.inventory.hosts.keys():
        results = nr.run(task=apply_config, templ_dir=args.templ_dir, role=args.role, dry_run=args.dry_run, replace=True)
        print_result(results)
    else:
        exit(f"% Result of Nornir filter is empty -> verify {os.path.basename(__file__)} --role/--node arguments.")
