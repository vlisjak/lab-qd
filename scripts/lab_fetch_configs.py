#!/usr/bin/env python

import utils
from nornir import InitNornir
from nornir_utils.plugins.functions import print_result
from nornir_netmiko.tasks import netmiko_send_command
from nornir_utils.plugins.tasks.files import write_file
import os
import sys

# TODO: this is a very basic script that works only for xrd nodes!

show_run_cmd = {
    'iosxr': 'show run formal',
    'ios': 'show run'
}

def backup_config(task):
    output = task.run(task=netmiko_send_command, command_string=show_run_cmd[task.host.platform])
    task.run(
        task=write_file,
        filename=f"device_configs/{task.host}-backup.cfg",
        content=output[0].result,
    )


if __name__ == "__main__":

    # os.chdir(sys.path[0])
    os.makedirs('device_configs', exist_ok=True)

    nr = InitNornir(config_file="nornir/nornir_config.yaml", dry_run=False)

    results = nr.run(task=backup_config)
    print_result(results)
