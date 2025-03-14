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
from jinja2 import Environment
import logging
import utils
from box import Box
import argparse

"""
********************** WORK IN PROGRESS **********************

Usage examples:

../scripts/lab_reset.py --h
../scripts/lab_reset.py --dry --node p2
../scripts/lab_reset.py --dry --role pe
../scripts/lab_reset.py --commit --node p2
../scripts/lab_reset.py --templ_dir ./templates/my_day0_config --dry --node p2
../scripts/lab_reset.py --nornir_cfg ./nornir/nornir_config.yaml --lab_qd_inv ./master_complete.yaml --templ_dir ./templates/min_cfg --dry --node p2

Expected inputs:

./master_complete.yaml
./nornir/nornir_config.yaml
./templates/min_cfg/
    ├── BASE_ios.j2
    ├── BASE_iosxr.j2
    ├── cpe_ios.j2
    ├── cpe_iosxr.j2
    ├── pe_iosxr.j2
    ├── p_iosxr.j2
    └── rr_iosxr.j2

Instead of jinja2 templates, you can also provide per-device config files:

./templates/min_cfg/
    ├── p1.txt
    ├── p2.txt
    ├── p3.txtx
    ├── cpe1.txt
    └── etc.


Note:
- name and IP addressof Mgmt interface is gathered from master_complete.yaml (lab-qd inventory)


TODO:
- save current config before "commit replace" -> ./config_backups/<hostname>_<date:time>.txt
"""


def parseArgs():
    parser = argparse.ArgumentParser(description="Script will *REPLACE* current device configuration - make sure you don't lock yourself out!")
    parser.add_argument("--templ_dir", help="Directory with templates or configs [./templates/min_cfg]", default="./templates/min_cfg", required=False)
    parser.add_argument("--nornir_cfg", help="Nornir configuration file [./nornir/nornir_config.yaml]", default="./nornir/nornir_config.yaml", required=False)
    parser.add_argument("--lab_qd_inv", help="Lab-qd inventory file [./master_complete.yaml]", default="./master_complete.yaml", required=False)
    dry_parser = parser.add_mutually_exclusive_group(required=True)
    dry_parser.add_argument("--dry", dest="dry_run", action="store_true", help="Show the diffs, but do not push the config to devices.")
    dry_parser.add_argument("--commit", dest="dry_run", action="store_false", help="Commit the config to devices!")
    parser.set_defaults(dry_run=True)
    parser.add_argument("--role", help="Configure only devices of specific role, such as 'pe'.", required=False)
    parser.add_argument("--node", help="Configure only selected device, such as 'rr1'.", required=False)
    return parser


def generate_config(task, templ_dir, role, t_file, inv):

    task.host["config"] = None

    config = task.run(
        task=template_file,
        template=t_file,
        path=templ_dir,
        node=task.host.name,
        node_inv=inv.devices[task.host.name],
        severity_level=logging.DEBUG,  # comment this line out, if you want to see rendered config (already shown by napalm diffs below..)
    )
    task.host["config"] = config.result

    return Result(
        host=task.host,
        result=f"Configuration for node {task.host.name} [role {role}] generated from {templ_dir}/{t_file}.",
    )


def apply_config(task, inv, templ_dir, role=None, dry_run=True, replace=True):

    roles_to_apply = [role] if role else task.host["device_role"]

    for role in roles_to_apply:
        templ_file = f"{role}_{task.host.platform}.j2"
        if os.path.isfile(f"{templ_dir}/{templ_file}"):
            task.run(task=generate_config, templ_dir=templ_dir, role=role, t_file=templ_file, inv=inv)
            if task.host["config"]:
                task.run(task=napalm_configure, configuration=task.host["config"], dry_run=dry_run, replace=replace)
                task.host.close_connections()
        elif os.path.isfile(f"{templ_dir}/{task.host.name}.txt"):
            with open(f"{templ_dir}/{task.host.name}.txt", 'r') as cfg_file:
                node_config = cfg_file.read()
                task.run(task=napalm_configure, configuration=node_config, dry_run=dry_run, replace=replace)
                task.host.close_connections()
        else:
            exit(f"% Could not open jinja template: {templ_dir}/{templ_file} nor config file: {templ_dir}/{task.host.name}.txt.")


if __name__ == "__main__":

    parser = parseArgs()
    args = parser.parse_args()

    master_complete = utils.load_vars(args.lab_qd_inv)
    lab_inventory = Box(master_complete)

    try:
        nr = InitNornir(config_file=args.nornir_cfg)
    except:
        exit(f"% Could not open Nornir configuration file: {args.nornir_cfg}")

    if args.role:
        nr = nr.filter(F(device_role__contains=args.role))
    if args.node:
        nr = nr.filter(name=args.node)

    if nr.inventory.hosts.keys():
        results = nr.run(task=apply_config, inv=lab_inventory, templ_dir=args.templ_dir, role=args.role, dry_run=args.dry_run, replace=True)
        print_result(results)
    else:
        exit(f"% Result of Nornir filter is empty -> verify {os.path.basename(__file__)} --role/--node arguments.")
