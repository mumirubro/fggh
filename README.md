# TOJI CHK Telegram Bot

A feature-rich Telegram bot for card checking, BIN lookup, and various utility tools.

## 🚀 Quick Start for VPS Deployment

### Prerequisites

Before you begin, make sure you have:
- A VPS with Ubuntu/Debian (or any Linux distribution)
- Python 3.11 or higher installed
- Your Telegram Bot Token (get it from [@BotFather](https://t.me/botfather))

### Step-by-Step Installation

#### 1. Connect to Your VPS

```bash
ssh your_username@your_vps_ip
```

#### 2. Update Your System

```bash
sudo apt update && sudo apt upgrade -y
```

#### 3. Install Python and Required Tools

```bash
sudo apt install python3 python3-pip python3-venv git -y
```

#### 4. Create a Directory for the Bot

```bash
mkdir -p ~/toji-chk-bot
cd ~/toji-chk-bot
```

#### 5. Download/Upload the Bot Files

You can either:

**Option A: Use Git (if you have a repository)**
```bash
git clone your-repository-url .
```

**Option B: Upload files manually using SCP from your local machine**
```bash
scp -r /path/to/bot/files/* your_username@your_vps_ip:~/toji-chk-bot/
```

**Option C: Create files directly**
```bash
nano main.py
# Paste the bot code and save (Ctrl+X, Y, Enter)

nano pyproject.toml
# Paste the dependencies and save

nano .env
# Add your configuration and save
```

#### 6. Create and Configure Environment File

```bash
nano .env
```

Add the following (replace with your actual values):
```env
BOT_TOKEN=your_bot_token_here
ADMIN_USERNAME=mumiru
```

Save and exit (Ctrl+X, Y, Enter)

#### 7. Install Dependencies

```bash
pip3 install python-telegram-bot requests python-dotenv
```

Or if using uv (faster):
```bash
pip3 install uv
uv pip install -r requirements.txt
```

#### 8. Test the Bot

```bash
python3 main.py
```

If everything works, you should see:
```
INFO - Bot started successfully!
```

Press Ctrl+C to stop the test.

### 🔄 Running the Bot 24/7

To keep the bot running even after you disconnect from SSH, use one of these methods:

#### Method 1: Using Screen (Recommended for Beginners)

**Install screen:**
```bash
sudo apt install screen -y
```

**Create a new screen session:**
```bash
screen -S toji-chk-bot
```

**Start the bot:**
```bash
cd ~/toji-chk-bot
python3 main.py
```

**Detach from screen (keep bot running):**
Press `Ctrl+A` then `D`

**Reattach to screen later:**
```bash
screen -r toji-chk-bot
```

**List all screen sessions:**
```bash
screen -ls
```

#### Method 2: Using Systemd (Recommended for Production)

**Create a service file:**
```bash
sudo nano /etc/systemd/system/toji-chk-bot.service
```

**Add this content (replace YOUR_USERNAME with your actual username):**
```ini
[Unit]
Description=TOJI CHK Telegram Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/toji-chk-bot
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart=/usr/bin/python3 /home/YOUR_USERNAME/toji-chk-bot/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start the service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable toji-chk-bot
sudo systemctl start toji-chk-bot
```

**Check status:**
```bash
sudo systemctl status toji-chk-bot
```

**View logs:**
```bash
sudo journalctl -u toji-chk-bot -f
```

**Stop the bot:**
```bash
sudo systemctl stop toji-chk-bot
```

**Restart the bot:**
```bash
sudo systemctl restart toji-chk-bot
```

#### Method 3: Using PM2 (Alternative)

**Install Node.js and PM2:**
```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

**Start the bot with PM2:**
```bash
cd ~/toji-chk-bot
pm2 start main.py --name toji-chk-bot --interpreter python3
```

**Save PM2 configuration:**
```bash
pm2 save
pm2 startup
```

**Useful PM2 commands:**
```bash
pm2 status              # Check status
pm2 logs toji-chk-bot      # View logs
pm2 restart toji-chk-bot   # Restart bot
pm2 stop toji-chk-bot      # Stop bot
pm2 delete toji-chk-bot    # Remove from PM2
```

### 🔧 Updating the Bot

When you need to update the bot:

1. **Stop the bot** (choose method you're using):
   ```bash
   # If using screen: Ctrl+C in the screen session
   # If using systemd:
   sudo systemctl stop ayaka-bot
   # If using PM2:
   pm2 stop ayaka-bot
   ```

2. **Update the files**:
   ```bash
   cd ~/toji-chk-bot
   # Edit main.py or upload new version
   nano main.py
   ```

3. **Restart the bot**:
   ```bash
   # If using screen:
   screen -r toji-chk-bot
   python3 main.py
   # If using systemd:
   sudo systemctl restart toji-chk-bot
   # If using PM2:
   pm2 restart toji-chk-bot
   ```

### 📋 Common Commands Summary

| Task | Command |
|------|---------|
| Start bot (screen) | `screen -S toji-chk-bot && python3 main.py` |
| Detach from screen | `Ctrl+A` then `D` |
| Reattach to screen | `screen -r toji-chk-bot` |
| Start bot (systemd) | `sudo systemctl start toji-chk-bot` |
| Stop bot (systemd) | `sudo systemctl stop toji-chk-bot` |
| Restart bot (systemd) | `sudo systemctl restart toji-chk-bot` |
| View logs (systemd) | `sudo journalctl -u toji-chk-bot -f` |
| Check status (systemd) | `sudo systemctl status toji-chk-bot` |

### 🐛 Troubleshooting

**Bot doesn't start:**
1. Check if Python is installed: `python3 --version`
2. Check if dependencies are installed: `pip3 list | grep telegram`
3. Verify your bot token in `.env` file
4. Check logs for errors

**Bot stops after some time:**
- Make sure you're using screen, systemd, or PM2
- Check system logs: `sudo journalctl -xe`
- Verify your VPS has enough memory: `free -h`

**Can't connect to bot:**
- Verify bot token is correct
- Check if VPS has internet connection: `ping google.com`
- Ensure no firewall is blocking connections

### 🔐 Security Tips

1. **Never commit `.env` file** to git (it's already in `.gitignore`)
2. **Keep your bot token secret** - don't share it
3. **Regularly update** your system and dependencies
4. **Use a firewall**: `sudo ufw enable && sudo ufw allow ssh`
5. **Consider using environment variables** instead of hardcoding tokens

### 📱 Bot Features

- ✅ User registration system
- ✅ BIN checking (single and mass)
- ✅ Card cleaning and formatting
- ✅ File splitting utility
- ✅ User info commands
- ✅ Admin panel
- ✅ Multiple payment gateway support (in development)

### 🆘 Support

If you need help:
1. Check the logs first
2. Verify all installation steps
3. Make sure your bot token is correct
4. Contact the developer

---

**Version:** 1.0 (Beta)  
**Last Updated:** November 2025
