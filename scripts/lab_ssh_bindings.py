#!/usr/bin/env python

"""
! Creating reverse-ssh bindings:
../scripts/lab_ssh_bindings.py --create --start_port 12000 --clab_yaml clab_startup/clab_startup.yaml
    Command executed for clab_node clab-vxlan_pod1-cpe1: socat TCP-LISTEN:12000,reuseaddr,fork TCP:clab-vxlan_pod1-cpe1:22 &
    Command executed for clab_node clab-vxlan_pod1-cpe2: socat TCP-LISTEN:12001,reuseaddr,fork TCP:clab-vxlan_pod1-cpe2:22 &
    <snip>

! SSH to containerlab node clab-vxlan_pod1-cpe2 (that runs on VM vlisjak.cisco.com) from remote laptops:
ssh cisco@vlisjak.cisco.com -p 12001

! Kill reverse-ssh bindings:
../scripts/lab_ssh_bindings.py --kill --start_port 12000 --clab_yaml clab_startup/clab_startup.yaml
    Terminated PID: 626292 for socat TCP-LISTEN:12000,reuseaddr,fork TCP:clab-vxlan_pod1-cpe1:22
    Terminated PID: 626294 for socat TCP-LISTEN:12001,reuseaddr,fork TCP:clab-vxlan_pod1-cpe2:22
    <snip>
"""

import psutil
import json
from subprocess import PIPE, Popen, DEVNULL
import argparse

start_port = 12000
clab_yaml = 'clab_startup/clab_startup.yaml'

def parseArgs():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument(
        "--start_port",
        type=int,
        help="Start of reverse ssh bindings, eg. 12000",
        required=True,
    )
    parser.add_argument(
        "--clab_yaml",
        help="Containerlab startup inventory, eg. clab_startup/clab_startup.yaml",
        required=True,
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--create", dest="create", action="store_true", help="Create socat bindings.")
    action.add_argument("--kill", dest="kill", action="store_true", help="Kill socat bindings.")
    return parser

def get_deployed_clab_nodes(clab_yaml):
    command = f"containerlab -t {clab_yaml} inspect -f json"
    with Popen(command, stdout=PIPE, stderr=DEVNULL, shell=True) as process:
        output = process.communicate()[0].decode("utf-8")
        return json.loads(output)

def create_socat_bindings(clab_list, start_port):
    for index, clab_node in enumerate(clab_list, start=0):
        n = start_port + index
        command = f"socat TCP-LISTEN:{n},reuseaddr,fork TCP:{clab_node}:22 &"
        try:
            Popen(command, shell=True)
            print(f"Command executed for clab_node {clab_node}: {command}")
        except Exception as e:
            print(f"Failed to execute command for clab_node {clab_node}: {e}")

def kill_socat(clab_list, start_port):
    for index, clab_node in enumerate(clab_list, start=0):
        n = start_port + index
        expected_command = f"socat TCP-LISTEN:{n},reuseaddr,fork TCP:{clab_node}:22"
        
        for process in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            try:
                cmdline = ' '.join(process.info['cmdline'])
                if expected_command in cmdline:
                    process.terminate()
                    print(f"Terminated PID: {process.pid} for {expected_command}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

if __name__ == "__main__":

    parser = parseArgs()
    args = parser.parse_args()

    clab_nodes = get_deployed_clab_nodes(clab_yaml=args.clab_yaml)
    clab_list = [container['name'] for container in clab_nodes.get('containers', []) if 'lab_name' in container]

    if args.kill:
        kill_socat(clab_list, start_port=args.start_port)
    if args.create:
        create_socat_bindings(clab_list, start_port=args.start_port)
