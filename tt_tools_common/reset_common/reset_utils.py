# SPDX-FileCopyrightText: © 2024 Tenstorrent Inc.
# SPDX-License-Identifier: Apache-2.0

"""
This file contains functions used to generate and save reset logs
"""

import os
import sys
import json
import datetime
from pathlib import Path
import tt_tools_common.reset_common.host_reset_log as log
from tt_tools_common.ui_common.themes import CMD_LINE_COLOR
from tt_tools_common.utils_common.system_utils import get_host_info
from tt_tools_common.utils_common.tools_utils import init_logging

LOG_FOLDER = os.path.expanduser("~/.config/tenstorrent")


def generate_reset_logs(devices, result_filename: str = None):
    """
    Generate and save reset logs
    Separate PCI indexes for gs and wh devices
    Generate a reset log with a sample mobo reset config
    """

    time_now = datetime.datetime.now()
    gs_pci_idx = []
    wh_pci_idx = []
    for i, dev in enumerate(devices):
        if dev.as_wh() and not dev.is_remote():
            wh_pci_idx.append(dev.get_pci_interface_id())
        elif dev.as_gs():
            gs_pci_idx.append(dev.get_pci_interface_id())
    reset_log = log.HostResetLog(
        time=time_now,
        host_name=get_host_info()["Hostname"],
        gs_tensix_reset=log.PciResetDeviceInfo(pci_index=gs_pci_idx),
        wh_link_reset=log.PciResetDeviceInfo(pci_index=wh_pci_idx),
        re_init_devices=True,
        wh_mobo_reset=[
            log.MoboReset(
                nb_host_pci_idx=wh_pci_idx,
                mobo="<MOBO NAME>",
                credo=["<group id>:<credo id>", "<group id>:<credo id>"],
                disabled_ports=["<group id>:<credo id>", "<group id>:<credo id>"],
            ),
            log.MoboReset(
                nb_host_pci_idx=wh_pci_idx,
                mobo="<MOBO NAME>",
                credo=["<group id>:<credo id>", "<group id>:<credo id>"],
                disabled_ports=["<group id>:<credo id>", "<group id>:<credo id>"],
            ),
        ],
    )
    if result_filename:
        dir_path = os.path.dirname(os.path.realpath(result_filename))
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        log_filename = result_filename
    else:
        log_filename = f"{LOG_FOLDER}/reset_config.json"
        if not os.path.exists(LOG_FOLDER):
            init_logging(LOG_FOLDER)
    reset_log.save_as_json(log_filename)
    return log_filename


def parse_reset_input(value):
    """Validate the reset inputs - either list of int PCI IDs or a json config file"""
    try:
        # Attempt to parse as a JSON file
        with open(value, "r") as json_file:
            data = json.load(json_file)
            return data
    except json.JSONDecodeError as e:
        print(
            CMD_LINE_COLOR.RED,
            f"Please check the format of the json file.\n {e}",
            CMD_LINE_COLOR.ENDC,
        )
        sys.exit(1)
    except FileNotFoundError:
        # If no file found, attempt to parse as a list of comma separated integers
        try:
            return [int(item) for item in value.split(",")]
        except ValueError:
            print(
                CMD_LINE_COLOR.RED,
                "Invalid input! Provide list of comma separated numbers or a json file.\n To generate a reset json config file run tt-smi -g",
                CMD_LINE_COLOR.ENDC,
            )
            sys.exit(1)
