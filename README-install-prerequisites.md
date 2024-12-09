Below are my installation notes - please check official manuals for latest procedures!

# Docker

https://docs.docker.com/engine/install/ubuntu/

Remove old docker (optional)
```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do sudo apt-get remove $pkg; done
```

Add Docker's official GPG key:
```bash
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Add the repository to Apt sources:
```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

```bash
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-compose
```
Note: above will also install python3

Proxy for docker: 
https://docs.docker.com/engine/cli/proxy/
https://docs.docker.com/engine/daemon/proxy/

```bash
cat /etc/systemd/system/docker.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://proxy.esl.cisco.com:80"
Environment="HTTPS_PROXY=http://proxy.esl.cisco.com:80"
Environment="no_proxy=localhost,127.0.0.1"
```

Couple of docker commands:
```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
sudo systemctl show --property=Environment docker

sudo groupadd docker
sudo usermod -aG docker $USER
newgrp docker

docker run hello-world
docker ps
docker container ls
docker images
docker logs -f <container_name>
docker exec -it <container_name> bash
docker exec -it <xrv9k_container> telnet 0 5000

# remove stopped containers
docker container prune
```

# Venv

https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/
```bash
sudo apt install python3.10-venv

python3 -m venv myvenv310

vlisjak@vlisjak:~$ vi ~/.bashrc 
source ~/myvenv310/bin/activate
```
Then logout/login again ..

# Containerlab

https://containerlab.dev/quickstart/

Install clab:
```bash
bash -c "$(curl -sL https://get.containerlab.dev)"
```


# Instal python libraries, including Nornir

```bash
pip install -r requirements.txt

# not sure why python-igraph does not make it in requirements.txt ... install separately
pip install python-igraph

# if you need to update requirements.txt:
- pip install pipreqs
- pipreqs . --force --mode no-pin
```

# Onboard XRD

Make sure to use control-plane version:
https://software.cisco.com/download/home/286331236/type/280805694/release/24.2.11

Upload XRD image to Docker

```bash
gunzip xrd-control-plane-container-x86.24.2.11.tgz
tar xvf xrd-control-plane-container-x86.24.2.11.tar 
mv \{platform\}-container-x64.dockerv1.tgz xrd-control-plane-container-x64.dockerv1.tgz

docker load -i xrd-control-plane-container-x64.dockerv1.tgz

(myvenv310) vlisjak@vlisjak:~/containerlab/srte$ docker image list|grep xrd
ios-xr/xrd-control-plane   24.2.11          f160dc83ee7e   2 months ago    1.28GB
```

If you downloaded different XRD release, please update docker image name and version in `master.yaml`:

```yaml
clab_startup:
  iosxr:
    image: ios-xr/xrd-control-plane:24.2.11
    kind: cisco_xrd
    startup-config: xrd_initial_cfg.j2
```
Update `/etc/sysctl.conf`

https://containerlab.dev/manual/kinds/xrd/
https://xrdocs.io/virtual-routing/tutorials/2022-08-22-setting-up-host-environment-to-run-xrd/

```bash
(myvenv310) vlisjak@vlisjak:~/containerlab/srte$ sudo sysctl -w user.max_inotify_instances=64000
user.max_inotify_instances = 64000
(myvenv310) vlisjak@vlisjak:~/containerlab/srte$ sudo sysctl -w fs.inotify.max_user_watches=64000
fs.inotify.max_user_watches = 64000

(myvenv310) vlisjak@vlisjak:~/containerlab/srte$ cat  /etc/sysctl.conf  | tail -2
fs.inotify.max_user_instances=64000
fs.inotify.max_user_watches=64000
```

# Onboard XRV9k

Discord channel: https://discord.com/channels/860500297297821756/865572914346065920

## Install Vrntelab 

Offical repo
```bash
cd containerlab
git clone https://github.com/hellt/vrnetlab && cd vrnetlab
```

## Build docker image with vrnetlab
Upload large image from my laptop to server where I run containerlab (below method will continue if connection is lost during transfer)
```bash
rsync -v --progress --stats --partial xrv9k-fullk9-x-7.10.2.qcow2 \
-e ssh vlisjak@vlisjak.cisco.com:containerlab/vrnetlab/xrv9k/xrv9k-fullk9-x-7.10.2.qcow2
```

Build the image and upload to docker
```bash
cd vrnetlab/xrv9k
make docker-image
```

## Update master.yaml
```yaml
clab_startup:
  xrv9k:
    image: vrnetlab/cisco_xrv9k:7.10.2
    kind: cisco_xrv9k
    startup-config: xrd_initial_cfg.j2
    env:
      VCPU: 4
      RAM: 20480
```

* Note1: official vrnetlab repo did not work for xrv9k (makefile.include) - so I had to use:
```bash
git clone https://github.com/kaelemc/vrnetlab

# and also modified the launch.py:
(myvenv310) vlisjak@vlisjak:~/containerlab/vrnetlab/xrv9k$ git diff
diff --git a/xrv9k/docker/launch.py b/xrv9k/docker/launch.py
index 601b624..b29bdcd 100755
--- a/xrv9k/docker/launch.py
+++ b/xrv9k/docker/launch.py
@@ -260,7 +260,7 @@ class XRV_vm(vrnetlab.VM):
         self.wait_write("ssh server vrf clab-mgmt")
         self.wait_write("ssh server netconf port 830")  # for 5.1.1
         self.wait_write("ssh server netconf vrf clab-mgmt")  # for 5.3.3
-        self.wait_write("netconf agent ssh")  # for 5.1.1
+        self.wait_write("netconf agent tty")  # for 5.1.1
         self.wait_write("netconf-yang agent ssh")  # for 5.3.3
         # configure gNMI
         self.wait_write("grpc port 57400")
@@ -277,6 +277,7 @@ class XRV_vm(vrnetlab.VM):
         self.wait_write("ipv4 address 10.0.0.15/24")
         self.wait_write("exit")
         self.wait_write("commit")
+        self.wait_write("show configuration failed")
         self.wait_write("exit")
 
         return True
```

# Onboard CSR1000

Follow the same procedure as with XRV9k, just pick correct image (eg. csr1000v-universalk9.17.04.03-serial.qcow2)

Update master.yaml
```yaml
clab_startup:
  ios:
    image: vrnetlab/cisco_csr1000v:17.04.03
    kind: cisco_csr1000v
    startup-config: ios_initial_cfg.j2
```

# Proxy - if needed
```bash
root@vlisjak:/home/vlisjak# cat /etc/profile.d/proxy.sh
# set proxy config via profile.d - should apply for all users

export http_proxy="http://proxy.esl.cisco.com:80/"
export https_proxy="http://proxy.esl.cisco.com:80/"
export ftp_proxy="http://proxy.esl.cisco.com:80/"
export no_proxy="127.0.0.1,localhost,.cisco.com,`echo 192.168.101.{1..254}`,`echo 10.48.188.{1..254}`"

# For curl
export HTTP_PROXY="http://proxy.esl.cisco.com:80/"
export HTTPS_PROXY="http://proxy.esl.cisco.com:80/"
export FTP_PROXY="http://proxy.esl.cisco.com:80/"
export NO_PROXY="127.0.0.1,localhost,.cisco.com,`echo 192.168.101.{1..254}`,`echo 10.48.188.{1..254}`"

# make it executable
sudo chmod +x  /etc/profile.d/proxy.sh

# add in .bashrc
source /etc/profile.d/proxy.sh

# verify
env | grep -i proxy
```