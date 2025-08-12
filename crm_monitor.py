import tkinter as tk
from tkinter import ttk
import subprocess
import threading
import time
import platform
import re
import os
from PIL import Image, ImageDraw
import io
import pystray
from pystray import MenuItem as item
import json
import logging
from logging.handlers import TimedRotatingFileHandler

# Setup logging folder & rotation every 24h with date in filename
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("PingLogger")
logger.setLevel(logging.INFO)

log_formatter = logging.Formatter('%(message)s')  # We log raw JSON strings

log_file_path = os.path.join(LOG_DIR, "ping_monitor.log")
handler = TimedRotatingFileHandler(log_file_path, when='midnight', backupCount=7, encoding='utf-8')
handler.setFormatter(log_formatter)
logger.addHandler(handler)

# Console handler (optional), logs normal readable messages
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

class PingMonitorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Network Monitor")
        self.root.geometry("600x300")
        self.root.configure(bg='#2b2b2b')
        self.root.resizable(False, False)
        
        # Configure modern style
        style = ttk.Style()
        style.theme_use('clam')
        
        # Status variables
        self.status = {
            'overall': False,
            'gateway': False,
            'voip': False,
            'wireguard': False
        }
        
        # Domain and IP configurations
        self.DOMAINS = [
            {"name": "digikala", "domain": "digikala.com"},
            {"name": "download", "domain": "download.ir"},
            {"name": "aparat", "domain": "aparat.com"}
        ]
        
        self.IP_TARGETS = {
            'gateway': {"name": "gateway", "ip": "79.127.78.196"},
            'voip': {"name": "VoIP", "ip": "10.60.0.1"},
            'wireguard': {"name": "WireGaurd", "ip": "10.60.0.4"}
        }
        
        self.PING_TIMEOUT = 2
        self.running = True
        
        # Setup GUI
        self.setup_gui()
        
        # Setup system tray
        self.setup_system_tray()
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        # Protocol for window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_gui(self):
        # Main frame
        main_frame = tk.Frame(self.root, bg='#2b2b2b')
        main_frame.pack(expand=True, fill='both', padx=20, pady=20)
        
        # Title
        title_label = tk.Label(
            main_frame, 
            text="Network Status Monitor", 
            font=('Segoe UI', 16, 'bold'),
            fg='#ffffff',
            bg='#2b2b2b'
        )
        title_label.pack(pady=(0, 20))
        
        # Status indicators frame
        indicators_frame = tk.Frame(main_frame, bg='#2b2b2b')
        indicators_frame.pack(expand=True)
        
        # Create status indicators
        self.indicators = {}
        statuses = [
            ('overall', 'Overall Internet'),
            ('gateway', 'Gateway'),
            ('voip', 'VoIP'),
            ('wireguard', 'WireGuard')
        ]
        
        for i, (key, label) in enumerate(statuses):
            indicator_frame = tk.Frame(indicators_frame, bg='#2b2b2b')
            indicator_frame.grid(row=0, column=i, padx=15)
            
            # Create canvas for circle
            canvas = tk.Canvas(
                indicator_frame, 
                width=90, 
                height=90, 
                bg='#2b2b2b', 
                highlightthickness=0
            )
            canvas.pack()
            
            # Draw initial circle (red)
            circle = canvas.create_oval(5, 5, 90, 90, fill='#ff4444', outline='#333333', width=2)
            
            # Label
            label_widget = tk.Label(
                indicator_frame,
                text=label,
                font=('Segoe UI', 10),
                fg='#cccccc',
                bg='#2b2b2b'
            )
            label_widget.pack(pady=(5, 0))
            
            self.indicators[key] = {
                'canvas': canvas,
                'circle': circle,
                'label': label_widget
            }

    def setup_system_tray(self):
        # Create tray icon
        image = self.create_tray_icon('#ff4444')  # Start with red
        
        menu = pystray.Menu(
            item('Show', self.show_window),
            item('Hide', self.hide_window),
            pystray.Menu.SEPARATOR,
            item('Exit', self.quit_application)
        )
        
        self.tray_icon = pystray.Icon("NetworkMonitor", image, "Network Monitor", menu)
        
        # Start tray in separate thread
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

    def create_tray_icon(self, color):
        # Create a simple colored circle for tray icon
        image = Image.new('RGB', (64, 64), color)  # ✅ Fixed size
        draw = ImageDraw.Draw(image)
        draw.ellipse([8, 8, 56, 56], fill=color)   # ✅ Fixed coordinates
        return image


    def parse_ping_delay(self, output):
        match = re.search(r'time[=<]\s*(\d+\.?\d*)\s*ms', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        match = re.search(r'time=(\d+\.?\d*)\s*ms', output)
        if match:
            return float(match.group(1))
        return None

    def log_ping_result(self, ip_or_domain, name, status, delay, speed, color):
    
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "target": ip_or_domain,
            "status": status,
            "delay_ms": delay,
            "speed": speed,
            "color": color
        }
        logger.info(json.dumps({"result": log_entry}))

    def ping_host(self, host=None, name=None):
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(self.PING_TIMEOUT * 1000), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(self.PING_TIMEOUT), host]
    
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.PING_TIMEOUT + 1,
            )
        
            if result.returncode == 0:
                delay = self.parse_ping_delay(result.stdout)
                if delay is not None and 0 <= delay <= 200:
                    self.log_ping_result(host, name, "connected", delay, "fast", "green")
                    return True  # ✅ Return boolean
                elif 200 <= delay <= 1500:
                    self.log_ping_result(host, name, "connected", delay, "slow", "yellow")
                    return True  # ✅ Return boolean
                else:
                    self.log_ping_result(host, name, "disconnected", delay, "dead", "red")
                    return False # ✅ Return boolean
            else:
                self.log_ping_result(host, name, "disconnected", None, "dead", "red")
                return False
            
        except (subprocess.TimeoutExpired, Exception):
            self.log_ping_result(host, name, "timeout", None, "dead", "red")
            return False

    def check_domains(self):
        results = []
        for domain_dict in self.DOMAINS:
            domain = domain_dict["domain"]
            name = domain_dict["name"]
            result = self.ping_host(domain, name=name)
            # Convert ping result to boolean
            connected = result is not False and result is not None
            results.append(connected)
        return any(results)  # True if ANY domain is reachable

    def check_single_ip(self, ip):
        # Find the matching IP target
        for target_key, ip_dict in self.IP_TARGETS.items():
            if ip_dict["ip"] == ip:
                result = self.ping_host(ip, name=ip_dict["name"])
                return result is not False  # Convert to boolean
        return False


    def update_indicator(self, key, connected):
        if key in self.indicators:
            color = '#44ff44' if connected else '#ff4444'
            self.indicators[key]['canvas'].itemconfig(
                self.indicators[key]['circle'], 
                fill=color
            )

    def update_tray_icon(self):
    # Get worst status (prioritize disconnected states)
        if any(self.status.values()):  # ✅ Fixed: NOT any = all disconnected
            color = '#ff4444'  # All disconnected - red
        else:
            color = '#44ff44'  # All connected - green
            
    
        self.tray_icon.icon = self.create_tray_icon(color)

        
        
        self.tray_icon.icon = self.create_tray_icon(color)

    def show_notification(self, title, message):
        try:
            self.tray_icon.notify(message, title)
        except:
            pass  # Notifications might not be available on all systems

    def monitor_loop(self):
        last_status = self.status.copy()
        
        while self.running:
            try:
                # Check domain connectivity (Overall Internet)
                overall_connected = self.check_domains()
                
                # Check individual IPs
                gateway_connected = self.check_single_ip(self.IP_TARGETS['gateway']['ip'])
                voip_connected = self.check_single_ip(self.IP_TARGETS['voip']['ip'])
                wireguard_connected = self.check_single_ip(self.IP_TARGETS['wireguard']['ip'])
                
                # Update status
                new_status = {
                    'overall': overall_connected,
                    'gateway': gateway_connected,
                    'voip': voip_connected,
                    'wireguard': wireguard_connected
                }
                
                # Update GUI in main thread
                self.root.after(0, self.update_gui, new_status)
                
                # Check for status changes and send notifications
                for key, value in new_status.items():
                    if last_status[key] != value:
                        status_text = "Connected" if value else "Disconnected"
                        service_name = key.replace('_', ' ').title()
                        self.show_notification(
                            f"{service_name} Status Changed",
                            f"{service_name} is now {status_text}"
                        )
                
                last_status = new_status.copy()
                time.sleep(2)  # Check every 7 seconds (between 5-10 as requested)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(5)

    def update_gui(self, new_status):
        self.status = new_status
        
        # Update visual indicators
        for key, connected in self.status.items():
            self.update_indicator(key, connected)
        
        # Update tray icon
        self.update_tray_icon()

    def show_window(self, icon=None, item=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self, icon=None, item=None):
        self.root.withdraw()

    def on_closing(self):
        self.hide_window()

    def quit_application(self, icon=None, item=None):
        self.running = False
        self.tray_icon.stop()
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = PingMonitorGUI()
        app.run()
    except KeyboardInterrupt:
        print("Application stopped by user.")