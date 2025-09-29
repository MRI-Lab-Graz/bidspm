#!/bin/bash
# Comprehensive disk cleanup script
# Run this to free up space on the system

echo "🧹 Starting comprehensive cleanup..."

# 1. Docker cleanup (if Docker is installed)
echo "1. Cleaning Docker data..."
docker system prune -a -f --volumes 2>/dev/null || echo "   Docker not available or already clean"

# 2. Clean package cache
echo "2. Cleaning package cache..."
sudo apt-get clean
sudo apt-get autoclean
sudo apt-get autoremove -y

# 3. Clean log files (keep recent ones)
echo "3. Cleaning old log files..."
sudo journalctl --vacuum-time=7d
sudo find /var/log -type f -name "*.log" -mtime +30 -delete 2>/dev/null || true
sudo find /var/log -type f -name "*.gz" -mtime +30 -delete 2>/dev/null || true

# 4. Clean temporary files
echo "4. Cleaning temporary files..."
sudo rm -rf /tmp/* 2>/dev/null || true
sudo rm -rf /var/tmp/* 2>/dev/null || true

# 5. Clean user cache
echo "5. Cleaning user cache..."
rm -rf ~/.cache/* 2>/dev/null || true

# 6. Clean thumbnails and browser cache
echo "6. Cleaning thumbnails and browser data..."
rm -rf ~/.thumbnails/* 2>/dev/null || true
rm -rf ~/.mozilla/firefox/*/Cache/* 2>/dev/null || true
rm -rf ~/.config/google-chrome/*/Cache/* 2>/dev/null || true

# 7. Find large files for manual review
echo "7. Finding largest files (for manual review)..."
echo "Largest files in /:"
sudo find / -xdev -type f -size +100M 2>/dev/null | head -10 | xargs ls -lh 2>/dev/null || true

# Show disk usage before and after
echo ""
echo "📊 Current disk usage:"
df -h /
echo ""
echo "✅ Cleanup complete!"
echo ""
echo "💡 Additional cleanup suggestions:"
echo "   - Check /var/log/ for large log files"
echo "   - Check ~/.local/share/ for large application data"
echo "   - Use 'ncdu /' to interactively find large directories"