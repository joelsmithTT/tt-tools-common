# SPDX-FileCopyrightText: © 2024 Tenstorrent Inc.
# SPDX-License-Identifier: Apache-2.0

"""
This file contains functions used to do a PCIe level reset for Wormhole chip.
"""

import os
import sys
import time
import fcntl
import struct
from typing import List
from pyluwen import PciChip
from tt_tools_common.ui_common.themes import CMD_LINE_COLOR
from tt_tools_common.utils_common.tools_utils import read_refclk_counter
from tt_tools_common.utils_common.system_utils import (
    # check_driver_version,
    get_host_info,
)

class BHChipReset:
    """Class to perform a chip level reset on WH PCIe boards"""

    # WH magic numbers for reset
    TENSTORRENT_IOCTL_MAGIC = 0xFA
    TENSTORRENT_IOCTL_RESET_DEVICE = (TENSTORRENT_IOCTL_MAGIC << 8) | 6
    TENSTORRENT_RESET_DEVICE_RESTORE_STATE = 0
    TENSTORRENT_RESET_DEVICE_RESET_PCIE_LINK = 1
    TENSTORRENT_RESET_DEVICE_CONFIG_WRITE = 2
    A3_STATE_PROP_TIME = 0.03
    POST_RESET_MSG_WAIT_TIME = 2
    MSG_TRIGGER_SPI_COPY_LtoR = 0x50
    MSG_TYPE_ARC_STATE3 = 0xA3
    MSG_TYPE_TRIGGER_RESET = 0x56

    def reset_device_ioctl(self, interface_id: int, flags: int) -> bool:
        dev_path = f"/dev/tenstorrent/{interface_id}"
        dev_fd = os.open(
            dev_path, os.O_RDWR | os.O_CLOEXEC
        )  # Raises FileNotFoundError and other appropriate exceptions.
        try:
            reset_device_in_struct = "II"
            reset_device_out_struct = "II"
            reset_device_struct = reset_device_in_struct + reset_device_out_struct

            input_size_bytes = struct.calcsize(reset_device_in_struct)
            output_size_bytes = struct.calcsize(reset_device_out_struct)
            reset_device_buf = bytearray(
                struct.pack(reset_device_struct, output_size_bytes, flags, 0, 0)
            )
            fcntl.ioctl(
                dev_fd, self.TENSTORRENT_IOCTL_RESET_DEVICE, reset_device_buf
            )  # Raises OSError

            output_buf = reset_device_buf[input_size_bytes:]
            _, result = struct.unpack(reset_device_out_struct, output_buf)

            return result == 0
        finally:
            os.close(dev_fd)

    def full_lds_reset(
        self, pci_interfaces: List[int], reset_m3: bool = False, silent: bool = False
    ) -> List[PciChip]:
        """Performs a full LDS reset of a list of chips"""

        # TODO: FOR BH Check the driver version and bail if link reset cannot be supported 
        # check_driver_version(operation="board reset")

        # Due to how Arm systems deal with PCIe device rescans, WH device resets don't work on that platform.
        # Check for platform and bail if it's Arm
        platform = get_host_info()["Platform"]
        if platform.startswith("arm") or platform.startswith("aarch"):
            print(
                CMD_LINE_COLOR.RED,
                "Cannot perform WH board reset on Arm systems, please reboot the system to reset the boards. Exiting...",
                CMD_LINE_COLOR.ENDC,
            )
            sys.exit(1)

        # Remove duplicates from the input list of PCI interfaces
        pci_interfaces = list(set(pci_interfaces))
        if not silent:
            print(
                f"{CMD_LINE_COLOR.BLUE} Starting PCI link reset on BH devices at PCI indices: {str(pci_interfaces)[1:-1]} {CMD_LINE_COLOR.ENDC}"
            )
        
        pci_bdf_list = {}
       
        # Collect device bdf and trigger resets for all BH chips in order
        for pci_interface in pci_interfaces:
            # TODO: Make this check fallible 
            pci_bdf = PciChip(pci_interface=pci_interface).get_pci_bdf()
            pci_bdf_list[pci_interface] = pci_bdf
            self.reset_device_ioctl(
                pci_interface, self.TENSTORRENT_RESET_DEVICE_CONFIG_WRITE
            )

        # check command.memory in config space to see if reset bit is set
            # 0 means config space reset happened correctly
            # 1 means config space reset didn't go through correctly 

        completed = 0
        files_map = {pci_interface: open(f'/sys/bus/pci/devices/{pci_bdf_list[pci_interface]}/config', 'rb') for pci_interface in pci_interfaces}
        
        elapsed = 0
        start_time = time.time()
        # Map of PCI interface to reset bit
        reset_bit_map = {pci_interface: 1 for pci_interface in pci_interfaces}
        while elapsed < self.POST_RESET_MSG_WAIT_TIME:
            for pci_interface, file in files_map.items():
                command_memory_byte =  os.pread(file.fileno(), 1, 4)
                reset_bit = (int.from_bytes(command_memory_byte, byteorder='little') >> 1) & 1
                # Overwrite to store the last value
                reset_bit_map[pci_interface] = reset_bit
            if completed == len(files_map.values()):
                break
            time.sleep(0.001)
            elapsed = time.time() - start_time

        # Check the last value of all the reset bits and report if any of them are not 0
        for pci_interface in pci_interfaces:
            if reset_bit_map[pci_interface] == 0:
                print(f"{CMD_LINE_COLOR.GREEN} Config space reset completed for device {pci_interface} {CMD_LINE_COLOR.ENDC}")
                completed += 1
            else:
                print(f"{CMD_LINE_COLOR.RED} Config space reset not completed for device {pci_interface}! {CMD_LINE_COLOR.ENDC}")
        
        for pci_interface in pci_interfaces:
            self.reset_device_ioctl(
                pci_interface, self.TENSTORRENT_RESET_DEVICE_RESTORE_STATE
            )
        #  All went well print success message
        # other sanity checks go here
        if not silent:
            print(
                f"{CMD_LINE_COLOR.BLUE} Finishing PCI link reset on BH devices at PCI indices: {str(pci_interfaces)[1:-1]} {CMD_LINE_COLOR.ENDC}"
            )
        
        pci_chips = [PciChip(pci_interface=interface) for interface in pci_interfaces]
        return pci_chips
