#!/usr/bin/env python

import utils
from nornir import InitNornir
from nornir_utils.plugins.functions import print_result
from nornir_netmiko.tasks import netmiko_send_command
from nornir_utils.plugins.tasks.files import write_file
from nornir_napalm.plugins.tasks import napalm_get
from nornir.core.filter import F
import os
import sys

def backup_config(task):
    output = task.run(task=napalm_get, getters=['config'])
    task.run(
        task=write_file,
        filename=f"device_configs/{task.host}-backup.cfg",
        content=output[0].result['config']['running'],
    )

if __name__ == "__main__":

    os.makedirs("device_configs", exist_ok=True)

    nr = InitNornir(config_file="nornir/nornir_config.yaml")

    # Exclude linux host
    nr = nr.filter(~F(platform__eq="linux"))

    results = nr.run(task=backup_config)
    print_result(results, vars=["stdout"])


