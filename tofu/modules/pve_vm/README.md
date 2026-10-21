# pve_vm

One Proxmox VE virtual machine, a full clone of a cloud-init template (default VM ID 9000, a
Debian 13 genericcloud image with the QEMU guest agent), in the resource pool `lab`.

- cloud-init sets a static IPv4 address and creates the `ansible` user with the given keys.
- `protect` sets Proxmox VE's own protection flag, which blocks removing the virtual machine and
  its disks; it is understood by Terraform as well as OpenTofu
  ([ADR 0005](../../../docs/adr/0005-opentofu-instead-of-terraform.md)).
- Tags: `managed-by-tofu`, `env-<env>` and the extra tags, sorted.
- The bpg/proxmox provider talks to the API only. Nothing here uploads snippets or files, so the
  provider configuration needs no `ssh` block and OpenTofu never logs in to the host.

## Usage

```hcl
module "vm" {
  source   = "../../modules/pve_vm"
  for_each = var.hosts

  name      = each.key
  node_name = var.node_name
  vm_id     = each.value.vm_id
  cores     = each.value.cores
  memory    = each.value.memory
  ipv4_cidr = each.value.ipv4_cidr # for example 192.0.2.11/24
  gateway   = var.gateway
  ssh_keys  = var.ssh_keys
  protect   = each.value.protect
}
```

The provider reads `PROXMOX_VE_ENDPOINT` and `PROXMOX_VE_API_TOKEN` (an API token with privilege
separation whose permissions are limited to the pool, the datastore, the network zone and the
node), and `PROXMOX_VE_API_HEADERS` when an access proxy sits in front of the API.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | | Name of the virtual machine. |
| `env` | string | `"lab"` | `lab`, `demo` or `showcase`; becomes the tag `env-<env>`. |
| `node_name` | string | | Proxmox VE node. |
| `vm_id` | number | | VM ID (the lab uses 110 to 119); not the template's. |
| `template_vm_id` | number | `9000` | Template to clone. |
| `pool_id` | string | `"lab"` | Resource pool. |
| `datastore_id` | string | `"local-lvm"` | Datastore of the disk and the cloud-init drive. |
| `bridge` | string | `"vmbr0"` | Network bridge. |
| `cores` | number | `1` | CPU cores, 1 to 16. |
| `memory` | number | `2048` | Memory in MiB, at least 512. |
| `disk_gb` | number | `8` | System disk in GiB, at least 4. |
| `ipv4_cidr` | string | | Static address with prefix length. |
| `gateway` | string | | Default gateway in the same subnet. |
| `admin_user` | string | `"ansible"` | User created by cloud-init (not `root`). |
| `ssh_keys` | list(string) | | Public keys of the admin user (at least one). |
| `tags` | list(string) | `[]` | Extra tags. |
| `protect` | bool | `false` | Proxmox VE protection flag. |

## Outputs

| Name | Description |
|---|---|
| `id` | Resource ID. |
| `vm_id` | VM ID. |
| `name` | Name. |
| `ipv4` | Address without the prefix length. |
| `protection` | Whether the protection flag is set. |

## Tests

`tests/pve.tftest.hcl` runs against a mocked provider: the full clone of template 9000, the pool
and tags, the protection flag, the sizes, the cloud-init user and address, and the rejected
gateways, addresses, VM IDs, keys and admin user.
