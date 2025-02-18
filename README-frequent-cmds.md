## Create lab startup files

```bash
# by default use master.yaml:
../scripts/lab_create.py

# alternatively:
../scripts/lab_create.py -m master-MINI.yaml
```

The following inventories will be (re)created by lab_create.py:
```
.
├── clab_startup
│   ├── clab_startup.yaml
│   ├── ios_initial_cfg.j2 <<< pre-defined in git repo (update to your needs)
│   └── xrd_initial_cfg.j2 <<< pre-defined in git repo (update to your needs)
├── master_complete.yaml   <<< final lab inventory (resolved inheritance, intf-names and ip addresses allocated)
└── nornir
    ├── nornir_config.yaml
    ├── nornir_groups.yaml
    └── nornir_hosts.yaml
```

> Note: lab_create.py will not start the topology.

## Containerlab operations

```bash
# Start lab
sudo containerlab -t clab_startup/clab_startup.yaml deploy

# Show summary of all started
sudo containerlab -t clab_startup/clab_startup.yaml inspect

# Configs of Xrd nodes is preserved, but not xrv9k!
sudo containerlab -t clab_startup/clab_startup.yaml destroy

# Wipe the lab completely
sudo containerlab -t clab_startup/clab_startup.yaml destroy --cleanup

# Few useful docker commands
docker container ls
docker network ls
docker images
docker network inspect <network>
docker logs -f <container_name>
docker exec -it <container_name> bash
docker exec -it <xrv9k_container> telnet 0 5000
```

## Configure network with Nornir
```bash
../scripts/lab_configure.py network --sections day0
../scripts/lab_configure.py network --sections day0 --node p2
../scripts/lab_configure.py network --sections day0 --dry_run=False

../scripts/lab_configure.py network --sections isis
../scripts/lab_configure.py network --sections isis --node p2
../scripts/lab_configure.py network --sections isis --dry_run=False

../scripts/lab_configure.py network --sections srte
../scripts/lab_configure.py network --sections srte --node p2
../scripts/lab_configure.py network --sections srte --dry_run=False

../scripts/lab_configure.py network --sections ibgp
../scripts/lab_configure.py network --sections ibgp --node rr1_top
../scripts/lab_configure.py network --sections ibgp --node pe1
../scripts/lab_configure.py network --sections ibgp --dry_run=False

../scripts/lab_configure.py network --sections day0,isis,ibgp --dry_run=False
../scripts/lab_configure.py network --sections isis,day0 --dry_run=True --role pe
../scripts/lab_configure.py network --sections ibgp --node rr1
../scripts/lab_configure.py network --sections isis,srte --dry_run=True --node rr1 --role pce
```

## Reset lab config

This will come handy when many people share the lab: we replace running config with templates/<min_cfg>/

```bash
../scripts/lab_reset.py --min_cfg min_cfg --role p
../scripts/lab_reset.py --min_cfg min_cfg --role p --dry_run False --replace True
```

## Deploy network services
```bash
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1002_B

../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001 --dry_run False
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1002_B --dry_run False

../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001 --endpoints cpe1
../scripts/lab_configure.py service --kind l3vpn --instance vrf_1001 --endpoints cpe2,cpe3
```
