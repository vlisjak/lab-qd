#!/usr/bin/env python

"""
Usage examples:

../scripts/lab_reset.py --dry --node p1 [p2 pe2 cpe1]
../scripts/lab_reset.py --dry --role pe [cpe pe]

../scripts/lab_reset.py --commit --node p1 p2
../scripts/lab_reset.py --commit --role pe cpe

../scripts/lab_reset.py --nornir_inv ./nornir/nornir_config.yaml --templ_dir ./templates/min_cfg --cfg_backup_dir ./backups_20250319 --dry --node p2

Expected inputs:

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
from nornir_napalm.plugins.tasks import napalm_get, napalm_configure, napalm_cli
from nornir_utils.plugins.tasks.files import write_file
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
        "--templ_dir",
        help="Directory with templates or configs [./templates/min_cfg]",
        default="./templates/min_cfg",
        required=False,
    )
    parser.add_argument(
        "--nornir_inv",
        help="Nornir configuration file [./nornir/nornir_config.yaml]",
        default="./nornir/nornir_config.yaml",
        required=False,
    )
    parser.add_argument(
        "--cfg_backup_dir",
        help="Fetch and save current device configs, before resetting the lab.",
        required=False,
    )
    dry_parser = parser.add_mutually_exclusive_group(required=True)
    dry_parser.add_argument("--dry", dest="dry_run", action="store_true", help="Show the diffs, but do not push the config to devices.")
    dry_parser.add_argument("--commit", dest="dry_run", action="store_false", help="Commit the config to devices!")
    parser.set_defaults(dry_run=True)
    parser.add_argument("--role", help="Configure only devices of specific role, such as 'pe'.", required=False, nargs="+")
    parser.add_argument("--node", help="Configure only selected device, such as 'rr1'.", required=False, nargs="+")
    return parser


def render_j2_template(task, templ_dir, t_file, role):

    task.host["config"] = None

    config = task.run(
        task=template_file,
        template=t_file,
        path=templ_dir,
        node=task.host.name,
        jinja_env=jinja_env,
        node_inv=task.host.data,
        severity_level=logging.DEBUG,  # comment this line out, if you want to see rendered config (already shown by napalm diffs below..)
    )
    task.host["config"] = config.result

    return Result(
        host=task.host,
        result=f"% Configuration for node {task.host.name} [role {role}] generated from template {templ_dir}/{t_file}.",
    )


def apply_configs(task, templ_dir, roles=None, dry_run=True, replace=True):

    if roles == None:
        roles_to_apply = task.host["device_roles"]
    else:
        roles_to_apply = [role for role in roles if role in task.host["device_roles"]]

    for role in roles_to_apply:

        node_config = None

        cfg_input = f"{templ_dir}/{task.host.name}.txt"
        j2_input = f"{templ_dir}/{role}_{task.host.platform}.j2"

        # first check if we have hardcoded device configuration file: cfg_input
        if os.path.isfile(cfg_input):
            with open(cfg_input, "r") as cfg_file:
                node_config = cfg_file.read()

        # otherwise try jinja2 template for given device-role: j2_input
        elif os.path.isfile(j2_input):
            templ_file = f"{role}_{task.host.platform}.j2"
            task.run(task=render_j2_template, templ_dir=templ_dir, t_file=templ_file, role=role)
            node_config = task.host["config"]

        # else fail...
        else:
            raise Exception(f"% Could not open jinja template nor config file for {task.host.name}.")

        if node_config:
            task.run(task=napalm_configure, configuration=node_config, dry_run=dry_run, replace=replace)
            task.host.close_connections()

def fetch_configs(task, cfg_backup_dir):
    os.makedirs(args.cfg_backup_dir, exist_ok=True)
    fetched = task.run(task=napalm_get, getters=['config'])
    task.host.close_connections()
    task.run(
        task=write_file,
        filename=f"{cfg_backup_dir}/{task.host}-backup.txt",
        content=fetched[0].result["config"]["running"],
    )
    return Result(
        host=task.host,
        result=f"% Configuration for node {task.host.name} has been saved.",
    )

if __name__ == "__main__":

    parser = parseArgs()
    args = parser.parse_args()

    jinja_env = Environment(trim_blocks=True, lstrip_blocks=True)
    jinja_env.filters["regex_search"] = utils.regex_search
    jinja_env.filters["ipv4_to_isis_net"] = utils.ipv4_to_isis_net
    jinja_env.filters["cidr_to_legacy"] = utils.cidr_to_legacy

    try:
        nr = InitNornir(config_file=args.nornir_inv)
    except:
        exit(f"% Could not open Nornir configuration file: {args.nornir_inv}")

    if args.role:
        nr = nr.filter(F(device_roles__any=args.role))

    if args.node:
        nr = nr.filter(F(name__in=args.node))

    # Exclude linux host
    nr = nr.filter(~F(platform__eq="linux"))

    if nr.inventory.hosts.keys():
        if not args.dry_run:
            print(f"% We will reset the nodes: {list(nr.inventory.hosts)}")
            if input("Y[es] to continue?").lower() not in ("y", "yes"):
                print("Exiting.")
                exit()

        if args.cfg_backup_dir:
            fetch_results = nr.run(task=fetch_configs, cfg_backup_dir=args.cfg_backup_dir)
            for hostname in nr.inventory.hosts.keys():
                print_result(fetch_results[hostname][0])

        apply_results = nr.run(task=apply_configs, templ_dir=args.templ_dir, roles=args.role, dry_run=args.dry_run, replace=True)
        print_result(apply_results)

    else:
        exit(f"% Result of Nornir filter is empty -> verify {os.path.basename(__file__)} --role/--node arguments.")
