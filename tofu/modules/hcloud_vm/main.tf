# One cloud server for the demo and showcase environments. No public SSH: Ansible reaches the
# server through the tunnel (or, as a fallback, through the CI firewall from one runner).
# Protection uses the provider's own flags, which Terraform understands too.

locals {
  labels = merge(var.labels, {
    env        = var.env
    managed-by = "tofu"
  })

  # The tunnel token, read only when asked for (the data source needs write permission). It
  # reaches the server once, in the first-boot user data, and lands in a 0600 file; the
  # cloudflared role takes the file over later. It is never an output.
  tunnel_token = var.fetch_tunnel_token ? data.cloudflare_zero_trust_tunnel_cloudflared_token.this[0].token : ""

  cloudflared_deb_url = "https://github.com/cloudflare/cloudflared/releases/download/${var.cloudflared_version}/cloudflared-linux-amd64.deb"
  cloudflared_install = join("; ", [
    "set -eu",
    "deb=/run/cloudflared.deb",
    "trap 'rm -f \"$deb\"' EXIT",
    "curl -fsSL -o \"$deb\" '${local.cloudflared_deb_url}'",
    "printf '%s  %s\\n' '${var.cloudflared_deb_sha256}' \"$deb\" | sha256sum -c -",
    "apt-get install -y \"$deb\"",
  ])

  # The token is read from a file, so it never shows up in the process list or in
  # "systemctl status" (no "cloudflared service install <token>").
  cloudflared_unit = <<-EOT
    [Unit]
    Description=Cloudflare Tunnel connector (first boot; the cloudflared role takes it over)
    After=network-online.target
    Wants=network-online.target

    [Service]
    User=cloudflared
    ExecStart=/usr/bin/cloudflared --no-autoupdate --metrics 127.0.0.1:2000 tunnel run --token-file /etc/cloudflared/token
    Restart=on-failure
    RestartSec=5
    NoNewPrivileges=yes

    [Install]
    WantedBy=multi-user.target
  EOT

  # First-boot configuration: the admin user with its key (no password, no root login) and
  # cloudflared. The package repository of cloudflared serves its newest release only, so the
  # pinned release is installed from GitHub, and only if its sha256 matches; cloud-init runs the
  # runcmd lines without "set -e", so download, check and install are one command that stops at
  # the first failure.
  cloud_config_base = {
    users = [
      {
        name                = var.admin_user
        shell               = "/bin/bash"
        groups              = ["sudo"]
        sudo                = "ALL=(ALL) NOPASSWD:ALL"
        lock_passwd         = true
        ssh_authorized_keys = [var.ssh_public_key]
      },
      {
        name           = "cloudflared"
        system         = true
        shell          = "/usr/sbin/nologin"
        no_create_home = true
      },
    ]
    disable_root   = true
    ssh_pwauth     = false
    package_update = true
    packages       = ["ca-certificates", "curl"]
    runcmd         = [["sh", "-c", local.cloudflared_install]]
  }

  # With the token: the token file and the unit, then start the connector. Deferred files are
  # written after the users exist, so the token file belongs to the cloudflared user from the
  # start. cloud-init rejects an empty write_files list, so the key exists only in this case.
  cloud_config_token = {
    write_files = [
      {
        path        = "/etc/cloudflared/token"
        owner       = "cloudflared:cloudflared"
        permissions = "0600"
        content     = local.tunnel_token
        defer       = true
      },
      {
        path        = "/etc/systemd/system/cloudflared.service"
        permissions = "0644"
        content     = local.cloudflared_unit
        defer       = true
      },
    ]
    runcmd = concat(local.cloud_config_base.runcmd, [
      ["systemctl", "daemon-reload"],
      ["systemctl", "enable", "--now", "cloudflared.service"],
    ])
  }

  # Each branch is encoded on its own: the two objects have different attributes.
  cloud_config = (
    var.fetch_tunnel_token
    ? yamlencode(merge(local.cloud_config_base, local.cloud_config_token))
    : yamlencode(local.cloud_config_base)
  )
  user_data = "#cloud-config\n${local.cloud_config}"
}

data "cloudflare_zero_trust_tunnel_cloudflared_token" "this" {
  count = var.fetch_tunnel_token ? 1 : 0

  account_id = var.account_id
  tunnel_id  = var.tunnel_id
}

# Hetzner Cloud accepts each public key only once per project. Environments that share a project
# and an operator key pass the ID of a key created once (ssh_key_ids); otherwise the module
# creates the key here.
resource "hcloud_ssh_key" "this" {
  count = var.ssh_key_ids == null ? 1 : 0

  name       = "${var.name}-${var.admin_user}"
  public_key = var.ssh_public_key
  labels     = local.labels
}

# Inbound traffic from the internet: ping, and the game port (TCP and UDP) on a game server only
# (game_port_open). No SSH; the firewall is stateful, so replies to outbound connections (the
# tunnel) pass.
resource "hcloud_firewall" "public" {
  name   = "${var.name}-public"
  labels = local.labels

  dynamic "rule" {
    for_each = var.game_port_open ? ["tcp", "udp"] : []

    content {
      description = "Game traffic (${upper(rule.value)})"
      direction   = "in"
      protocol    = rule.value
      port        = tostring(var.game_port)
      source_ips  = ["0.0.0.0/0", "::/0"]
    }
  }

  rule {
    description = "Ping"
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

# Fallback for the first Ansible run: SSH from one CI runner. The pipeline adds and removes the
# runner's address with the hcloud CLI, so OpenTofu ignores rule changes after creation.
resource "hcloud_firewall" "ci_ssh" {
  count = var.enable_ci_ssh_fw ? 1 : 0

  name   = "${var.name}-ci-ssh"
  labels = local.labels

  dynamic "rule" {
    for_each = length(var.ci_ssh_source_ips) > 0 ? [var.ci_ssh_source_ips] : []

    content {
      description = "SSH from the CI runner"
      direction   = "in"
      protocol    = "tcp"
      port        = "22"
      source_ips  = rule.value
    }
  }

  lifecycle {
    ignore_changes = [rule]
  }
}

resource "hcloud_primary_ip" "ipv4" {
  count = var.use_primary_ip ? 1 : 0

  name              = "${var.name}-ipv4"
  type              = "ipv4"
  location          = var.location
  auto_delete       = false
  delete_protection = var.protect
  labels            = local.labels
}

resource "hcloud_server" "this" {
  name        = var.name
  server_type = var.server_type
  image       = var.image
  location    = var.location
  ssh_keys    = var.ssh_key_ids != null ? var.ssh_key_ids : hcloud_ssh_key.this[*].id
  user_data   = local.user_data
  labels      = local.labels

  firewall_ids = concat([hcloud_firewall.public.id], hcloud_firewall.ci_ssh[*].id)

  # Both flags come from one variable: the provider requires them to be equal.
  delete_protection  = var.protect
  rebuild_protection = var.protect

  public_net {
    ipv4_enabled = true
    ipv4         = var.use_primary_ip ? hcloud_primary_ip.ipv4[0].id : null
    ipv6_enabled = true
  }

  lifecycle {
    # User data matters at first boot only. Without this, a read-only plan (token not read)
    # would propose to replace the server.
    ignore_changes = [user_data]
  }
}
