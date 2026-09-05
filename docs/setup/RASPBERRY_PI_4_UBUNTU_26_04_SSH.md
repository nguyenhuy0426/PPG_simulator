# Raspberry Pi 4 — Ubuntu 26.04 LTS over direct Ethernet and SSH

This guide connects an Ubuntu 24.04 laptop directly to a Raspberry Pi 4
running Ubuntu 26.04 LTS, copies this repository without copying x86 virtual
environments or caches, and runs software checks before hardware mode.

The examples below use the values configured on the development laptop on
2026-09-04:

| Item | Value |
|---|---|
| Laptop Ethernet interface | `enx00e04c6807fc` |
| NetworkManager profile | `rpi4-direct` |
| Laptop address | `10.42.0.1/24` |
| Stable Pi address | `10.42.0.2/24` |
| Current Pi Wi-Fi address | `192.168.16.101/24` |
| Current Pi user | `huy` |
| Working SSH alias | `ppg-rpi4` / `ppg-rpi4-wifi` |
| Reserved Ethernet alias | `ppg-rpi4-ethernet` |
| Project on Pi | `~/final_project/PPG_simulator_raspi` |

Replace `<PI_USER>` with the account created during Ubuntu's first-boot setup.
Ubuntu does not guarantee a default `pi` account.

On 2026-09-04 the verified connection is Wi-Fi at `192.168.16.101`. Both ends
of the direct Ethernet link reported `NO-CARRIER`, so the Ethernet alias below
is reserved until the cable/link LEDs are working. `ping` uses the IP address;
unlike `ssh`, it does not read aliases from `~/.ssh/config`.

Canonical lists Raspberry Pi 4B as supported by Ubuntu 26.04 LTS and publishes
the ARM64 Raspberry Pi image in its
[Raspberry Pi installation matrix](https://documentation.ubuntu.com/hardware-support/boards/how-to/ubuntu_supported/raspberry-pi/).
The EEPROM minimum and A/B boot-layout notes come from the
[Ubuntu 26.04 LTS summary](https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/).

## 1. One-time setup on the laptop

Find the wired interface and confirm that the cable has carrier:

```bash
ip -brief link
sudo ethtool enx00e04c6807fc | grep 'Link detected'
```

Create an isolated shared-Ethernet profile. `ipv4.method shared` gives the Pi
internet access through the laptop's Wi-Fi while keeping SSH on the cable:

```bash
nmcli connection add type ethernet \
  ifname enx00e04c6807fc \
  con-name rpi4-direct \
  ipv4.method shared \
  ipv4.addresses 10.42.0.1/24 \
  ipv6.method link-local \
  connection.autoconnect yes

nmcli connection up rpi4-direct
ip -brief address show dev enx00e04c6807fc
```

If the profile already exists, do not add it again:

```bash
nmcli connection up rpi4-direct
```

Expected laptop address: `10.42.0.1/24`.

## 2. One-time setup on the Pi console

The laptop cannot SSH until the Pi has an address and an SSH server. Attach a
keyboard/display (or serial console) to the Pi once and inspect its wired
interface name:

```bash
ip -brief link
cat /etc/os-release
uname -m
cat /proc/device-tree/model
```

Expected: Ubuntu `26.04`, `aarch64`, and `Raspberry Pi 4`. The interface is
normally `eth0`; substitute the name printed by `ip -brief link` if different.

Give the cable a stable address outside NetworkManager's shared DHCP pool:

```bash
sudo nano /etc/netplan/99-rpi4-direct.yaml
```

Enter the following, replacing `eth0` if necessary:

```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - 10.42.0.2/24
      routes:
        - to: default
          via: 10.42.0.1
          metric: 500
      nameservers:
        addresses:
          - 10.42.0.1
      optional: false
```

Validate before applying. Do not ignore an error from `netplan generate`:

```bash
sudo chmod 600 /etc/netplan/99-rpi4-direct.yaml
sudo netplan generate
sudo netplan apply
ip -brief address
ip route
```

Install and enable SSH:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
systemctl --no-pager --full status ssh
ss -ltn | grep ':22'
```

If UFW is active, allow SSH only from the direct cable:

```bash
sudo ufw status
sudo ufw allow from 10.42.0.0/24 to any port 22 proto tcp
```

Ubuntu 26.04 on Pi 4 requires boot EEPROM firmware dated 2022-11-25 or newer
for its A/B boot layout. Check it without changing it:

```bash
sudo rpi-eeprom-update
```

## 3. Commands used every time from the laptop

### Current working Wi-Fi connection

These are the short commands for this Pi as it is configured now:

```bash
ping -c 4 192.168.16.101
ssh ppg-rpi4
ssh -Y ppg-rpi4                 # open a GUI on the laptop through X11
ssh ppg-rpi4 'hostname; uptime' # run one remote command and return
```

The matching entries already written to `/home/huynn/.ssh/config` are:

```sshconfig
Host ppg-rpi4 ppg-rpi4-wifi
    HostName 192.168.16.101
    User huy
    IdentityFile /home/huynn/.ssh/id_ed25519
    IdentitiesOnly yes
    ForwardX11 yes
    ForwardX11Trusted yes
    ServerAliveInterval 30
    ServerAliveCountMax 3

Host ppg-rpi4-ethernet
    HostName 10.42.0.2
    User huy
    IdentityFile /home/huynn/.ssh/id_ed25519
    IdentitiesOnly yes
    ForwardX11 yes
    ForwardX11Trusted yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

If DHCP later changes the Wi-Fi address, find the new address on the Pi with
`ip -brief address show wlan0` and change only the `HostName` line under the
first entry.

### Direct Ethernet after carrier is restored

Bring the cable profile up, verify reachability, then connect:

```bash
nmcli connection up rpi4-direct
ping -c 4 10.42.0.2
ssh <PI_USER>@10.42.0.2
```

The first SSH connection asks whether to trust the host key. Check the
fingerprint shown on the Pi with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`
before answering `yes` when practical.

Create a key once so later connections do not need the account password:

```bash
ssh-keygen -t ed25519 -a 100
ssh-copy-id <PI_USER>@10.42.0.2
ssh <PI_USER>@10.42.0.2
```

The equivalent direct-cable alias in `~/.ssh/config` is:

```sshconfig
Host ppg-rpi4-ethernet
    HostName 10.42.0.2
    User huy
    IdentityFile /home/huynn/.ssh/id_ed25519
    IdentitiesOnly yes
    ForwardX11 yes
    ForwardX11Trusted yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

After that, the short commands are:

```bash
ping -c 4 10.42.0.2
ssh ppg-rpi4-ethernet
```

If the OS image was reflashed and SSH reports a changed host key, verify the
new fingerprint on the Pi first, then remove only the old entry:

```bash
ssh-keygen -R 10.42.0.2
ssh-keygen -R 192.168.16.101
```

## 4. Copy the current source tree to the Pi

Create the destination:

```bash
ssh <PI_USER>@10.42.0.2 \
  'mkdir -p ~/final_project/PPG_simulator_raspi'
```

From the repository root on the laptop, copy source and the current
`config.json`, but never copy laptop virtual environments, Git/tool indexes,
or generated bytecode to ARM64:

```bash
cd /home/huynn/final_project/PPG_simulator_raspi

rsync -av --info=progress2 \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='.cad_venv/' \
  --exclude='.pio/' \
  --exclude='.pytest_cache/' \
  --exclude='.codegraph/' \
  --exclude='.codebase-memory/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  ./ <PI_USER>@10.42.0.2:~/final_project/PPG_simulator_raspi/
```

This command intentionally omits `--delete`; it cannot silently remove files
that already exist on the Pi. Re-run the same command after later edits.

## 5. Build the Pi's own ARM64 environment

Run the setup in an interactive SSH terminal because `apt` and the optional
I2C changes use `sudo`:

```bash
ssh -t <PI_USER>@10.42.0.2 \
  'cd ~/final_project/PPG_simulator_raspi && ./scripts/setup_rpi_ubuntu.sh --enable-i2c'
```

Never copy `.venv` from the x86_64 laptop. The Pi must create its own ARM64
environment. If the script requests a reboot or re-login, do that before the
next checks.

Reconnect and run the read-only environment verifier:

```bash
ssh <PI_USER>@10.42.0.2 \
  'cd ~/final_project/PPG_simulator_raspi && PYTHONNOUSERSITE=1 .venv/bin/python scripts/verify_rpi_env.py'
```

Then explicitly scan the I2C bus:

```bash
ssh -t <PI_USER>@10.42.0.2 'i2cdetect -y 1'
```

Expected addresses are `0x08` (Grove MM32 ADC), `0x60` (IR MCP4725), and
`0x61` (Red MCP4725). An ACK proves bus reachability only; it does not prove
DAC voltage, LED current, OPT101 response, or optical isolation.

## 6. Run and debug over SSH

First verify the hardware-independent subset:

```bash
ssh <PI_USER>@10.42.0.2 \
  'cd ~/final_project/PPG_simulator_raspi && PYTHONNOUSERSITE=1 PPG_DRY_RUN=1 .venv/bin/python -m unittest tests.test_calibration tests.test_phase3_acdc tests.test_phase4_dac tests.test_phase5_rx tests.test_led_driver_dac tests.test_led_driver_compliance tests.test_led_driver_power tests.test_led_driver_error_budget'
```

The application is graphical. To show its window on the laptop, use X11
forwarding and keep the terminal open:

```bash
ssh -X <PI_USER>@10.42.0.2
cd ~/final_project/PPG_simulator_raspi
PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 .venv/bin/python main.py 2>&1 | tee ~/ppg-simulator-debug.log
```

For a software-only GUI run that does not access I2C/GPIO:

```bash
PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 .venv/bin/python main.py --dry-run
```

### Open the remote project in Antigravity IDE

The installed Antigravity IDE includes its own **Antigravity Remote - SSH**
extension. After the `ppg-rpi4` alias works in a normal terminal:

1. Press `Ctrl+Shift+P` in Antigravity IDE.
2. Run `Remote-SSH: Connect to SSH Host...`.
3. Select `ppg-rpi4` and open
   `/home/<PI_USER>/final_project/PPG_simulator_raspi`.
4. Open **Run and Debug** and select either `PPG Simulator (dry-run)` or
   `PPG Simulator (Raspberry Pi hardware)`.
5. Press `F5`.

The repository includes [`.vscode/launch.json`](../../.vscode/launch.json) and
`.vscode/settings.json`, so the remote window uses the Pi-local `.venv` and
runs `main.py` in Antigravity's integrated terminal. Add breakpoints normally.

The editor/debugger appears inside Antigravity. CustomTkinter is a native GUI,
so its application surface appears as a separate desktop window through X11,
not embedded inside an editor tab. On the Pi, install the forwarding helper if
the GUI reports that no display is available:

```bash
sudo apt install -y xauth
```

Then disconnect and reconnect the Antigravity Remote-SSH window. Verify the
remote terminal has a display before pressing `F5`:

```bash
echo "$DISPLAY"
```

It must print a value such as `localhost:10.0`. If it is empty, run the program
from a local Antigravity integrated terminal with `ssh -Y ppg-rpi4` instead;
the Tk window will still be displayed on the laptop.

Useful diagnostics from the laptop:

```bash
ssh <PI_USER>@10.42.0.2 'hostnamectl; ip -brief address; systemctl is-active ssh'
ssh <PI_USER>@10.42.0.2 'cd ~/final_project/PPG_simulator_raspi && tail -n 100 ~/ppg-simulator-debug.log'
ssh <PI_USER>@10.42.0.2 'ls -l /dev/i2c-* /dev/gpiochip*'
```

Press `Ctrl-C` in the running terminal to request a clean shutdown. The runtime
then stops acquisition and parks both DAC channels at the configured safe idle
value. A clean software shutdown still needs bench confirmation at the physical
outputs before it counts as hardware validation.

## Troubleshooting the direct cable

| Symptom | Check |
|---|---|
| Ethernet says `NO-CARRIER` | Pi power, cable seating, adapter LEDs, then `ethtool <interface>` |
| Laptop is missing `10.42.0.1` | `nmcli connection up rpi4-direct` |
| `ping 10.42.0.2` fails | Run `ip -brief address` on the Pi console; verify `eth0` and the Netplan file |
| Ping works but SSH is refused | `sudo systemctl enable --now ssh` on the Pi |
| SSH times out with UFW active | Apply the scoped UFW rule in section 2 |
| Pi cannot reach package servers | Verify laptop Wi-Fi, `ip route` on Pi, and `ping -c 2 10.42.0.1` |
| Tk reports no display | Reconnect with `ssh -X`; install `xauth` on the Pi if missing |
| `apt update` fails on `seeed.list` / `stretch` | Disable that obsolete source with `sudo mv /etc/apt/sources.list.d/seeed.list /etc/apt/sources.list.d/seeed.list.disabled`, then run `sudo apt update` again |
| Both `RPi.GPIO` and `rpi-lgpio` appear | Keep `PYTHONNOUSERSITE=1`; this hides an unrelated classic `RPi.GPIO` from `~/.local` while retaining Ubuntu's `rpi-lgpio` |
| Venv executable is wrong architecture | Remove only the Pi-side `.venv` and rerun `./scripts/setup_rpi_ubuntu.sh --recreate` |
