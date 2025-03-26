#!/usr/bin/env python

import subprocess
import psutil
import json
from subprocess import PIPE, Popen, DEVNULL

start_port = 12000
clab_yaml = 'clab_startup/clab_startup.yaml'

def get_deployed_clab_nodes(clab_yaml):
    command = f"containerlab -t {clab_yaml} inspect -f json"
    with Popen(command, stdout=PIPE, stderr=DEVNULL, shell=True) as process:
        output = process.communicate()[0].decode("utf-8")
        return json.loads(output)

def create_socat_bindings(vm_list, start_port):
    for index, vm in enumerate(vm_list, start=1):
        n = start_port + index
        command = f"socat TCP-LISTEN:{n},reuseaddr,fork TCP:{vm}:22 &"
        try:
            subprocess.Popen(command, shell=True)
            print(f"Command executed for VM {vm}: {command}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to execute command for VM {vm}: {e}")

def kill_socat(vm_list, start_port):
    for index, vm in enumerate(vm_list, start=1):
        n = start_port + index
        expected_command = f"socat TCP-LISTEN:{n},reuseaddr,fork TCP:{vm}:22"
        
        for process in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            try:
                cmdline = ' '.join(process.info['cmdline'])
                if expected_command in cmdline:
                    process.terminate()
                    print(f"Terminated PID: {process.pid} for {expected_command}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


clab_nodes = get_deployed_clab_nodes(clab_yaml=clab_yaml)
vm_list = [container['name'] for container in clab_nodes.get('containers', []) if 'lab_name' in container]

kill_socat(vm_list, start_port=start_port)

# create_socat_bindings(vm_list, start_port=start_port)
