#!/usr/bin/env bash
# ==============================================================================
# deploy_oracle_vm.sh - 1-Command Oracle Cloud Always Free VM Deployment
# Runs 24/7/365 with ZERO time limits, no local Mac dependency, and full UI access.
# ==============================================================================

set -e

echo "================================================================="
echo "   ORACLE CLOUD ALWAYS FREE - 24/7 CAREER AUTOMATION SETUP       "
echo "================================================================="

# 1. Update OS and Install Base Tools
echo "--> Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl ufw libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

# 2. Setup Application Directory
INSTALL_DIR="/opt/career_automation"
sudo mkdir -p "$INSTALL_DIR"
sudo chown -R "$USER:$USER" "$INSTALL_DIR"

echo "--> Copying files to $INSTALL_DIR..."
cp -r . "$INSTALL_DIR/"
cd "$INSTALL_DIR"

# 3. Virtual Environment & Dependencies
echo "--> Setting up Python Virtual Environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install flask playwright schedule requests

echo "--> Installing Playwright Chromium & OS browser libraries..."
playwright install chromium
playwright install-deps chromium

# 4. Import Active Auth Sessions (LinkedIn, Naukri, Gmail)
if [ -f "data/session_cookies.json" ]; then
    echo "--> Importing authenticated login cookies..."
    python3 import_session.py
else
    echo "WARNING: data/session_cookies.json not found! Copy it over to keep sessions logged in."
fi

# 5. Configure Firewall (Port 5055 for Meraki UI Dashboard)
echo "--> Configuring Firewall for port 5055..."
sudo ufw allow 5055/tcp || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 5055 -j ACCEPT || true

# 6. Create Systemd Service for Meraki UI Dashboard
echo "--> Creating Systemd Service for Meraki UI Command Center..."
sudo bash -c "cat <<EOF > /etc/systemd/system/career-hub.service
[Unit]
Description=Meraki UI Career Command Center (Port 5055)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/app.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# 7. Create Systemd Service for 24/7 Autonomous Daily Scheduler
echo "--> Creating Systemd Service for Autonomous 24/7 Scheduler..."
sudo bash -c "cat <<EOF > /etc/systemd/system/career-scheduler.service
[Unit]
Description=24/7 Autonomous Career Scheduler (Naukri Boost, 50+ Apply, Gmail Sweep)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/daily_scheduler.py
Restart=always
RestartSec=15
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF"

# 8. Reload & Start Services
echo "--> Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable career-hub.service
sudo systemctl restart career-hub.service

sudo systemctl enable career-scheduler.service
sudo systemctl restart career-scheduler.service

PUBLIC_IP=$(curl -s ifconfig.me || echo "<YOUR_VM_PUBLIC_IP>")

echo ""
echo "================================================================="
echo "   DEPLOYMENT COMPLETED SUCCESSFULLY!                            "
echo "================================================================="
echo "Your Meraki UI Command Center is live 24/7 on your Cloud VM:"
echo "   http://$PUBLIC_IP:5055"
echo ""
echo "Autonomous Services Running 24/7/365 in background:"
echo " • career-hub.service       (Meraki UI Dashboard & APIs)"
echo " • career-scheduler.service (Naukri Boost, 50+ Apply, Gmail Sweep)"
echo "================================================================="
