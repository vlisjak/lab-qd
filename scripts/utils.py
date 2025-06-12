import yaml
import json
import re
from copy import deepcopy
from deepmerge import always_merger
from N2G import drawio_diagram
import xml.etree.ElementTree as ET
import os
import ipaddress
import shlex, subprocess


def load_vars(file_path):
    try:
        with open(file_path, "r") as file:
            try:
                return yaml.safe_load(file)
            except Exception as error:
                print(f"Error reading yaml content from {file_path}:", error) 
    except:
        exit(f"% Could not open: {file_path}")


def save_inventory(config, file_path):
    try:
        with open(file_path, "w") as file:
            yaml.dump(config, file, default_flow_style=False)
    except:
        exit(f"% Could not save: {file_path}")


def regex_search(value, pattern):
    return re.search(pattern, value) is not None


def json_print(object, filename=None):
    if filename:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(object, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(object, indent=2))


def yaml_print(object, filename=None):
    if filename:
        with open(filename, "w", encoding="utf-8") as f:
            yaml.dump(object, f, default_flow_style=False, sort_keys=False, indent=2)
    else:
        print(json.dumps(object, indent=2))


def clab_intf_map(clab_kind, device_if):
    """
    Containerlab interface naming in clab_startup.yaml is not always the same as interface
    names in device configurations.
    This function maps device interface name to clab naming.
    - Please add below an 'if' statement for each clab kind.
    """
    if clab_kind == "cisco_xrd":
        # https://containerlab.dev/manual/kinds/xrd/
        clab_if = re.sub("/", "-", device_if)
        return clab_if
    if clab_kind == "cisco_c8000":
        # https://containerlab.dev/manual/kinds/c8000/
        clab_if = re.sub("/", "_", device_if)
        return clab_if


def ipv4_to_isis_net(ipv4_address, area_id="49.0001", nsel="00"):
    """
    Convert an IPv4 address to an IS-IS NET.
    Assumes the IPv4 address is the Loopback0 interface IP.
    """
    head, sep, tail = ipv4_address.partition("/")
    tmp = "{:0>3}{:0>3}{:0>3}{:0>3}".format(*head.split("."))
    return "49.0000.{}.{}.{}.00".format(tmp[0:4], tmp[4:8], tmp[8:12])


def cidr_to_legacy(ipv4_cidr):
    """
    Converts CIDR notation (x.x.x./y) to IP address and legacy netmask (x.x.x.x yyy.yyy.yyy.yyy).
    Returns dict:
    {'ip': <ipv4 address>, 'netmask': <legacy netmask>}
    """
    return {
        "ip": str(ipaddress.ip_interface(ipv4_cidr).ip),
        "netmask": str(ipaddress.ip_interface(ipv4_cidr).netmask),
    }


def create_network_diagram(clab_links, master_complete_dotted):
    """
    Input: the same "links" bucket as in clab_startup.yaml
        links:
        - endpoints:
            - p1:Gi0-0-0-0
            - p2:Gi0-0-0-0
        - endpoints:
            - p2:Gi0-0-0-1
            - p3:Gi0-0-0-0
        - endpoints:
            - p3:Gi0-0-0-1
            - p4:Gi0-0-0-0

    TODO: in fact we shall fetch nodes/links from master_complete.yaml ("lldp:") so the drawio is produced also for physical labs
    """

    def get_node_pos(xml, node_id):
        """
        Input:
            <object id="cpe2" label="cpe2">
                <mxCell style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
                    <mxGeometry x="481" y="622" width="120" height="60" as="geometry" />
                </mxCell>
            </object>
        Returns:
            ('x', 'y')
        Library:
            https://n2g.readthedocs.io/en/latest/diagram_plugins/DrawIo%20Module.html
        """
        oldPos = xml.find(f".//object[@id='{node_id}']/mxCell/mxGeometry")
        if oldPos != None:
            (oldX, oldY) = (oldPos.attrib["x"], oldPos.attrib["y"])
            return (oldX, oldY)
        else:
            return ("0", "0")

    newD = drawio_diagram()
    newD.add_diagram("Topology", width=1000, height=1000)

    for link in [x["endpoints"] for x in clab_links]:
        (n1, if1) = link[0].split(":")
        (n2, if2) = link[1].split(":")
        newD.add_node(
            id=n1,
            width=80,
            label=f"{n1} {master_complete_dotted.devices[n1].interfaces.Loopback0.ipv4_address}",
        )
        newD.add_node(
            id=n2,
            width=80,
            label=f"{n2} {master_complete_dotted.devices[n2].interfaces.Loopback0.ipv4_address}",
        )
        newD.add_link(n1, n2, src_label=if1, trgt_label=if2)

    newD.layout(algo="rt_circular")
    newD.layout(algo="kk")
    newXml = ET.ElementTree(ET.fromstring(newD.dump_xml()))

    # if drawio topology has been previously arranged, respect the old (manual) positioning of nodes
    if os.path.isfile(f"./{master_complete_dotted.drawio_diagram}"):
        oldD = drawio_diagram()
        oldD.from_file(master_complete_dotted.drawio_diagram)
        oldXml = ET.fromstring(oldD.dump_xml())

        for node in newD.nodes_ids["Topology"]:
            oldPos = get_node_pos(oldXml, node)
            newPos = newXml.find(".//object[@id='{id}']/mxCell/mxGeometry".format(id=node))
            newPos.set("x", oldPos[0])
            newPos.set("y", oldPos[1])

    newXml.write(f"./{master_complete_dotted.drawio_diagram}")


def create_clab2host_vlans(clab_links):
    """
    https://github.com/vlisjak/lab-qd?tab=readme-ov-file#connect-data-interface-from-clab-node-to-physical-router-macvlan

    links:
    - endpoints:
        - p1:Gi0-0-0-0
        - macvlan:ens256.111

    Example for vlan 111:
        ip link set ens256 up
        ip link add link ens256 name ens256.111 address de:ad:be:ef:01:11 type vlan id 111
        ip link set ens256.111 up
    """
    for link_pair in [x["endpoints"] for x in clab_links]:
        for link in link_pair:
            (node, intf) = link.split(":")
            if node == "macvlan":
                (host_phy, host_vlan) = intf.split(".")
                mac_addr = f"{host_vlan:0>4}"[:-2] + ":" + f"{host_vlan:0>4}"[-2:]
                cmds = [
                    f"sudo ip link set {host_phy} up",
                    f"sudo ip link add link {host_phy} name {intf} address de:ad:be:ef:{mac_addr} type vlan id {host_vlan}",
                    f"sudo ip link set {intf} up",
                ]
                for cmd in cmds:
                    print(f"Executing: {cmd}")
                    proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, text=True)


def resolve_inheritance(config):
    """
    Recursively processes the "inherit_from" directives at any level of YAML inventory.
    - code ensures that child attributes override parent attributes, and any missing attributes are inherited from the parent.
    - code allows multiple levels of "inherit_from".
    - code allows dotted path so "inherit_from" can point to nested element in top-level object
    - arrays are merged with elements from child
    """

    # Create a deep copy of the config to preserve the original
    config_copy = deepcopy(config)

    def get_nested_value(config, path):
        keys = path.split(".")
        value = config
        for key in keys:
            if key in value:
                value = value[key]
            else:
                raise ValueError(f"Key '{key}' not found in configuration path '{path}'")
        return value

    def recursive_inherit(value, config):
        if isinstance(value, dict):
            if "inherit_from" in value:
                parent_paths = value.pop("inherit_from")
                if not isinstance(parent_paths, list):
                    parent_paths = [parent_paths]
                for parent_path in parent_paths:
                    parent_value = get_nested_value(config, parent_path)
                    if isinstance(parent_value, dict):
                        # If the parent value is a dictionary, merge it
                        parent = deepcopy(parent_value)
                        value = always_merger.merge(parent, value)
                    else:
                        # If the parent value is a single value, add it to the dictionary
                        value[parent_path.split(".")[-1]] = parent_value
            for subkey in list(value.keys()):
                value[subkey] = recursive_inherit(value[subkey], config)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = recursive_inherit(item, config)
        return value

    for key in list(config_copy.keys()):
        config_copy[key] = recursive_inherit(config_copy[key], config_copy)

    return config_copy
