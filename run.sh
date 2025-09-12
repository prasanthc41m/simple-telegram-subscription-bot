#!/data/data/com.termux/files/usr/bin/bash

# Script to set up and run Python scripts in Termux with autostart capability
echo "Starting setup process..."

# Get the current directory
SCRIPT_DIR=$(pwd)

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if a process is running
process_running() {
    pgrep -f "$1" >/dev/null
}

# Install Python if not installed
if ! command_exists python; then
    echo "Installing Python..."
    pkg install python -y
else
    echo "Python is already installed."
fi

# Create virtual environment if it doesn't exist
if [ ! -d "bot-env" ]; then
    echo "Creating virtual environment..."
    python -m venv bot-env
else
    echo "Virtual environment already exists."
fi

# Activate virtual environment
echo "Activating virtual environment..."
source bot-env/bin/activate

# Install requirements if not already installed
if [ ! -f ".requirements_installed" ]; then
    echo "Installing requirements..."
    pip install -r requirements.txt
    touch .requirements_installed
else
    echo "Requirements already installed."
fi

# Check if scripts are already running and start them if not
if ! process_running "main.py"; then
    echo "Starting main.py..."
    nohup python main.py > main.log 2>&1 &
else
    echo "main.py is already running."
fi

if ! process_running "linkgen.py"; then
    echo "Starting linkgen.py..."
    nohup python linkgen.py > linkgen.log 2>&1 &
else
    echo "linkgen.py is already running."
fi

# Set wake lock
echo "Setting wake lock..."
termux-wake-lock

# Setup autostart
echo "Setting up autostart..."
# Create the boot directory if it doesn't exist
mkdir -p ~/.termux/boot

# Create the autostart script
AUTOSTART_SCRIPT="$HOME/.termux/boot/start_bot.sh"

cat > "$AUTOSTART_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Navigate to the script directory
cd "$SCRIPT_DIR"

# Activate virtual environment
source bot-env/bin/activate

# Navigate to ambili directory
cd ambili

# Start the Python scripts
nohup python main.py > main.log 2>&1 &
nohup python linkgen.py > linkgen.log 2>&1 &

# Set wake lock
termux-wake-lock
EOF

# Make the autostart script executable
chmod +x "$AUTOSTART_SCRIPT"

echo "Autostart script created at: $AUTOSTART_SCRIPT"
echo ""
echo "Setup complete! Both scripts are running in the background."
echo "Logs are being saved to main.log and linkgen.log"
echo ""
echo "IMPORTANT: For autostart to work:"
echo "1. Install Termux:Boot from F-Droid"
echo "2. Open Termux:Boot once to grant necessary permissions"
echo "3. Disable battery optimization for Termux and Termux:Boot in Android settings"
