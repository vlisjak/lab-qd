# TODOs (in no particular order)


- allow multiple nodes/roles in CLI argument of all scripts

- Implement lab-reset and lab_upgrade scripts - mainly for physical routers
  - lab_reset.py: replace current config with minimal mgmt. config
    - challenge: how to prevent users from modifying root user and mgmt_intf?
    - can we make day0 and min_cfg templates the same?
  - lab_upgrade: replace OS version on physical routers

- allow clab nodes data links with physical routers
  - Documented and tested:   
    https://github.com/vlisjak/lab-qd?tab=readme-ov-file#connect-data-interface-from-clab-nodes-to-physical-router
  - automate vlan creation on host in lab_create.py: done for xrd nodes
  - TBD: figure how to connect xrv9k (VM in container) because macvlan concept of xrd does not seem to work :(   
      --> This works:   

      ```
          topology:
            links:
            - type: macvlan
              endpoint:
                node: p1
                interface: Gi0/0/0/0
              host-interface: ens256.111
              mode: passthru
            nodes:
              p1:
                kind: cisco_xrv9k
                mgmt-ipv4: 10.255.0.2
                exec:
                  - ip link set Gi0-0-0-0 promisc on
      ```
    - lab_create.py: handle external link definition for macvlan links on xrv9k/csr1000, with passthru (extended format)
    - lab_create.py: add promisc mode cmd for all macvlan links on xrv9k/csr1000 (exec: ip link set Gi0-0-0-0 promisc on)

- generate CML topology (in addition to clab)

- add gnmi config capability
  https://github.com/akarneliuk/pygnmi/tree/master/examples/nornir
  https://nornir-salt.readthedocs.io/en/latest/Tasks/pygnmi_call.html
  
- add nornir/netconf example
  https://github.com/h4ndzdatm0ld/nornir_netconf/tree/develop/examples/example-project

- new repo name:
  lab_qd - Lab Quickly Done
  lab_fx - Fast eXecution

- refactor spaghetti intf_ip_allocation() function:
  - port_allocation()
  - ipv4_allocation()
  - IP address auto-allocate should be done also for loop0/mgmt
  - even better: complete OOP rewrite!

- allow manual IPv4 address in topology (links) defintion
  - mainly to allow physical routers, which may already have IPs assigned

- implement remote ssh using 'socat' port mapping
  https://github.com/chadell/nornir-playground/tree/main
    socat TCP-LISTEN:12001,reuseaddr,fork TCP:clab-mini-pe1:22 &
          ssh cisco@vlisjak -p 12001
    socat TCP-LISTEN:12002,reuseaddr,fork TCP:clab-mini-pe2:22 &
        ssh cisco@vlisjak -p 12002
    socat TCP-LISTEN:12003,reuseaddr,fork TCP:clab-mini-p1:22 &
        ssh cisco@vlisjak -p 12003

- put all jinja filters in separate include .py

- allow jumphost for nornir

- handle full-mesh iBGP:
    device_roles:
      pe:
        device_roles: [pe]
        ibgp:
          asn: 100
          # TBD: currently this is not handled in iBGP .j2
          full_mesh: [pe]

- LxVPN: Develop "undo" for all jinja templates

- L3VPN: implement example for primary/backup uplink (yaml + jinja)

- LxVPN: think how to implement cascaded CPEs..
  - L3_cpe --- L3_CPE(s) --- PE
  - L3_cpe --- L2_CPE(s) --- PE

- L3VPN: implement un-managed CPEs
  - master.yaml/services/instance/endpoint: managed: False

- drawio diagram:
  - prevent overlap of parallel links
  - fetch nodes/links from master_complete.yaml ("lldp:"), so the drawio diagram is produced also for physical labs

- documentation: show a conceptual/block diagram of solution

- add "logging debugs" function so we can see the progress of ./create_lab_vars.py execution

- additional node types
  - linux (cpe, tgen)

- install edgeshark (wireshark with gui)
  https://github.com/siemens/edgeshark

- Automate test cases

  - Results:
    - .txt, .doc

  - Checks:
    - simple string match
    - regex match
    - custom python function

  - Test chaining / post-processing between steps

- Add scale testing templates
  - BGP peers
  - BGP routes
  - LxVPN instances
  - LxVPN routes
  - Etc.

# Implemented TODOs

- generate also nornir_config.yaml
- jinja2 example: hierarchical RRs
- jinja2 example: multi-instance ISIS
- execute nornir scripts only for specific sections/roles/nodes
- generate drawio topology diagram
  - previous node positions are preserved
- allow dotted parameter access in jinja2 - with use of Box()
- allow multiple links between two nodes
- need for separate inventory due to lack of custom groups in nornir
  - nornir hosts will inherit "data" from groups, and groups from defaults
  - but there's no way to define eg. "core", "edge", etc. interface groups, which would be then inherited in hosts
- create myvenv
- add lldp-like record in each interface (in master_complete.yaml)
- allow manually defined interface names in master.yaml (auto-allocation will 'skip' already used intf. IDs)
- L2 interfaces: if 'prefix' attribute is missing, we do not auto-allocate IP address
- network services example: YAML and jinja for L3VPN
- make sure that lab_create.py works for a minimal `lab_mini` setup

- Bundle interfaces
  - assume one bundle between two nodes n1-n2
  - assign all n1-n2 links with 'link.link_group == core_bundle_member' to this Bundle
  - Bundle IP from the same range as other core links
  - Bundles must not be included in clab startup! (these are only logical links in XR)
      - bundle members however must be in clab startup!
  - logic:
    for link in links:
      if link.link_group == core_bundle:
        if not full_ifname: allocate new bundle_id
        for all links towards the same node, with 'link.link_group == core_bundle_member':
            create attribute link.bundle.member_of = bundle_id

- Interface-specific ID auto-allocation:
  - allocate ID per node and per interface type
  - this is to allow separate IDs for Gig0/0/0/X, TenGig0/X, Bundle-EtherX, etc.

- additional node types
  - csr1000v - https://software.cisco.com/download/home/284364978/type/282046477/release/Amsterdam-17.3.8a
  - xrv9k - xrv9k-fullk9-x-7.10.2.qcow2

- clab<->device interface mapping should be more flexible
  - mapping for each type of nodes can be defined in utils.py->clab_intf_map()

- argparse: add submenu cmds to lab_configure.py: network, services

- device is added to clab_startup.yaml only if it has 'clab' element (variables inherited from clab_startup)

- folder structure that allows multiple labs

# Discarded TODOs

- allow xpath search in jinja templates: 
  - xpath expressions are perhaps too complicated on itself ..

- documentation: show a sample master.yaml with all possible fields/features, and mark bold all mandatory variables
  - will show step by step how we add functionality to master.yaml (starting from minimal 4-node topo and day0)

- Move master_complete.yaml (devices subtree) to nornir_hosts.yaml => CAN'T DO THAT (because we also have services subtree!)
  - Reasoning:
    - links and link_groups (in master.yaml) is used only to generate (inheritance) content within devices subtree (master_complete.yaml)
    - and then per-device content can be also embeded directly in nornir_hosts.yaml (data subtree)
    - this way all scripts (that use Nornir anyway) could get any per-device parameter from nornir->data subtree
