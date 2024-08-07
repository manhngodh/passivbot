provider "google" {
  credentials = file("~/.gcp/gcp-key.json")
  project     = "stellar-utility-170606"
  region      = "asia-east1"
}

resource "google_compute_address" "autobot_static_ip" {
  name         = "autobot"
  region       = "asia-east1"
  address_type = "EXTERNAL"
  address      = "35.194.148.150"  # Pre-defined IP address
}

resource "google_compute_instance" "default" {
  name         = "autobot-vm"
  machine_type = "e2-medium"  # Cheapest machine type
  zone         = "asia-east1-a"  # Specify the zone within the region

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"  # Choose an image suitable for you
    }
  }
  network_interface {
    network = "default"
    subnetwork = "default"  # Use the appropriate subnetwork if different
    access_config {
      nat_ip = google_compute_address.autobot_static_ip.address
    }
  }

  network_interface {
    network_tier = "PREMIUM"
  }

  tags = ["http-server"]

  metadata_startup_script = <<-EOF
    #!/bin/bash
    apt-get update
    apt-get install -y git wget bzip2 supervisor

    # Clone the GitHub repository
    git clone https://github.com/manhngodh/passivbot.git /opt/passivbot

    # Create directories for secrets and download the secrets files
    mkdir -p /opt/passivbot/secrets /opt/passivbot/test

    # Set proper permissions for the /opt/passivbot directory
    chown -R $(whoami) /opt/passivbot

    # Fetch the secrets files from metadata
    curl -o /opt/passivbot/api-keys.json http://metadata.google.internal/computeMetadata/v1/instance/attributes/secrets -H "Metadata-Flavor: Google"

    # Download and install Miniconda
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p /opt/miniconda
    export PATH="/opt/miniconda/bin:$PATH"

    # Initialize conda
    conda init bash
    source ~/.bashrc

    # Create a conda environment and activate it
    conda create -y -n passivbot-env python=3.9
    conda activate passivbot-env


    # Change directory to the app
    cd /opt/passivbot

    # Install the requirements using conda
    pip install -r requirements.txt

    # Ensure the script is executable
    chmod +x /opt/passivbot/update_supervisor_configs.sh
  EOF

  metadata = {
    secrets     = file("api-keys.json")
  }
}


output "instance_ip" {
  value = google_compute_instance.default.network_interface.0.access_config.0.nat_ip
}
