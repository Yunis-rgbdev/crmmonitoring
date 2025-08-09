import logging
import logging.handlers
import json
import os
import sys
import platform
import subprocess
import threading
import re
import queue
import time
from collections import deque
import tkinter as tk
from tkinter import ttk
import pystray
from PIL import Image, ImageDraw
from datetime import datetime, timezone
from pythonjsonlogger import jsonlogger


# Json Format
class JsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record['@time'] = datetime.now(timezone.utc).isoformat()
        log_record['logger'] = record.name
        log_record['line'] = record.lineno
        log_record['function'] = record.funcName
        log_record['message'] = record.getMessage()

# fallback logger for errors during logger setup
fallback_logger = logging.getLogger('fallback')
fallback_logger.setLevel(logging.INFO)
fallback_console_handler = logging.StreamHandler()
fallback_console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
fallback_logger.addHandler(fallback_console_handler)
##

# Setting up Logging Service
logger = logging.getLogger("CRM Ping Monitoring")
logger.setLevel(logging.DEBUG)

# Configure log file path (use absolute path)
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
log_file = os.path.join(log_dir, f'pingapp.log')
fallback_logger.info(f"Attempting to use log file: {log_file}")

# Create log directory
try:
    os.makedirs(log_dir, exist_ok=True)
    fallback_logger.info(f"Log directory created or exists: {log_dir}")
except Exception as e:
    fallback_logger.error(f"Failed to create log directory {log_dir}: {e}")
    sys.exit(1)

# Setting TimedRotatingFileHandler
try:
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_file,
        when='midnight',
        interval=1,
        backupCount=10,
        encoding='utf-8',
        utc=True
    )
    fallback_logger.info("TimedRotatingFileHandler configured successfully")
except Exception as e:
    fallback_logger.error(f"Failed to configure TimedRotatingFileHandler for {log_file}: {e}")
    fallback_logger.error("Check file permissions, directory access, disk space.")
    # Fallback to a basic file handler
    try:
        fallback_handler = logging.FileHandler('fallback.log', encoding='utf-8')
        fallback_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fallback_handler)
        logger.error(f"Fallback logging to fallback.log due to TimedRotatingFileHandler failure: {e}")
    except Exception as fe:
        fallback_logger.error(f"Failed to configure fallback FileHandler: {fe}")
        sys.exit(1)
else:
    # Apply JSON Formatter
    formatter = JsonFormatter('%(message)s %(levelname)s %(name)s %(filename)s %(lineno)s %(funcName)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Add console handler for debugging
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class PingMonitor:
    def __init__(self, root):
        logger.info("PingMonitor UI initialized")
        self.root = root
        self.root.title("CRM Ping Monitor")
        self.root.geometry("650x450")
        self.root.configure(bg="#2E2E2E")  # Dark grey background
        self.pre_status = None
        self.last_repeat_time = 0
        self.repeat_interval = 10
        threading.Thread(target=self.connection_notification_loop, daemon=True).start()

        # Detect DPI scaling factor
        self.dpi_scale = self.root.winfo_fpixels('1i') / 72
        # logger.debug(f"DPI scaling factor: {self.dpi_scale}", extra={"dpi_scale": self.dpi_scale})

        self.ping_targets = [
            {"name": "Internet", "ip": "79.127.78.196"},
            {"name": "WireGuard", "ip": "10.60.0.1"},
            {"name": "VoIP", "ip": "10.60.0.4"}
        ]
        self.results = {target["name"]: deque(maxlen=5) for target in self.ping_targets}
        self.result_queue = queue.Queue()
        self.running = True
        self.status_frames = {}
        self.icon = None  # System tray icon

        self.setup_gui()
        self.setup_system_tray()
        logger.debug("GUI setup complete, starting ping threads...", extra={"stage": "gui_complete"})
        self.ping_and_store()

    def setup_gui(self):
        logger.debug("Setting up GUI...", extra={"stage": "gui_setup"})
        main_frame = tk.Frame(self.root, bg="#2E2E2E")
        main_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        status_frame = tk.Frame(main_frame, bg="#2E2E2E", bd=2, relief="flat")
        status_frame.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        main_frame.grid_columnconfigure(0, weight=1)

        base_size = int(120 * self.dpi_scale)
        for i, target in enumerate(self.ping_targets):
            frame = tk.Frame(status_frame, bg="#2E2E2E")
            frame.grid(row=0, column=i, padx=20, sticky="n")
            label = tk.Label(frame, text=target["name"], font=("Segoe UI", 14, "bold"), fg="#FFFFFF", bg="#2E2E2E")
            label.pack(pady=(0, 5))
            status_canvas = tk.Canvas(frame, width=base_size, height=base_size, bg="#2E2E2E", highlightthickness=0)
            status_canvas.create_oval(5, 5, base_size-5, base_size-5, fill="#4A4A4A", outline="")
            status_canvas.create_oval(2, 2, base_size-2, base_size-2, fill="#3A3A3A", outline="")
            status_canvas.create_oval(0, 0, base_size-4, base_size-4, fill="gray", outline="")
            status_canvas.pack()
            self.status_frames[target["name"]] = status_canvas

        self.log_frame = tk.Frame(main_frame, bg="#3C3C3C", bd=2, relief="flat")
        self.log_text = tk.Text(self.log_frame, height=8, font=("Segoe UI", 12), bg="#3C3C3C", fg="#FFFFFF", wrap="word", bd=0)
        scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(state="disabled")
        self.log_frame.grid(row=2, column=0, padx=5, pady=(0, 10), sticky="nsew")
        self.log_visible = True

        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

    def setup_system_tray(self):
        logger.debug("Setting up system tray...", extra={"stage": "system_tray"})
        image = Image.new('RGB', (64, 64), color="#2E2E2E")
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill="gray", outline="#4A4A4A")
        self.icon = pystray.Icon("Ping Monitor", image, "CRM Ping Monitor", menu=pystray.Menu(
            pystray.MenuItem("Show", self.show_window),
            pystray.MenuItem("Exit", self.stop_monitoring)
        ))
        threading.Thread(target=self.icon.run, daemon=True).start()

    def update_tray_icon(self, color):
        print(f"Updating system tray icon to color: {color}")
        image = Image.new('RGB', (64, 64), color="#2E2E2E")
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill=color, outline="#4A4A4A")
        self.icon.icon = image

    def minimize_to_tray(self):
        logger.info("Minimizing to system tray...", extra={"stage": "minimize"})
        self.root.withdraw()
        self.icon.notify("Ping Monitor minimized to tray", "CRM Ping Monitor")

    def show_window(self):
        logger.info("Restoring window...", extra={"stage": "restore"})
        self.root.deiconify()
        self.icon.remove_notification()

    def ping_and_store(self):
        logger.info("Starting ping threads...", extra={"stage": "ping_start"})
        threads = []
        for target in self.ping_targets:
            
            thread = threading.Thread(target=self.ping_target_continuously, args=(target["ip"], target["name"]))
            thread.daemon = True
            threads.append(thread)
            thread.start()
        # for i, thread in enumerate(threads):
        #     logger.debug(f"Thread {i} for {self.ping_targets[i]['name']} is alive: {thread.is_alive()}", extra={"thread_id": i, "target_name": self.ping_targets[i]["name"]})

    def ping_target_continuously(self, ip, name):
        while self.running:
            try:
                # logger.info(f"Pinging {ip} ({name})...", extra={"ip": ip, "target_name": name})
                cmd = ["ping", "-n" if os.name == "nt" else "-c", "1", "-w", "2000", ip]
                # logger.debug(f"Executing command: {' '.join(cmd)}", extra={"command": cmd})
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                # logger.debug(f"Raw ping output for {ip}: {result.stdout}", extra={"ip": ip, "output": result.stdout})
                # logger.debug(f"Ping return code for {ip}: {result.returncode}", extra={"ip": ip, "returncode": result.returncode})
                if result.returncode == 0:
                    delay = self.parse_ping_delay(result.stdout)
                    status = "success"
                else:
                    delay = None
                    status = "failed"
                    stderr_output = result.stderr.strip() if result.stderr else "No error output"
                    logger.warning(f"Ping failed for {ip}: {stderr_output}", extra={
                        "ip": ip,
                        "target_name": name,
                        "error": stderr_output
                    })


                self.result_queue.put({
                    "name": name,
                    "ip": ip,
                    "status": status,
                    "delay": delay,
                    "timestamp": time.time()
                })

            except subprocess.TimeoutExpired:
                stderr_output = result.stderr.strip() if result.stderr else "No error output"
                logger.warning(f"Error subprocess timeout for {ip}: {stderr_output}", extra={
                    "ip": ip,
                    "target_name": name,
                    "error": stderr_output
                })
                self.result_queue.put({
                    "name": name,
                    "ip": ip,
                    "status": "timeout",
                    "delay": None,
                    "timestamp": time.time()
                })
            except Exception as e:
                stderr_output = result.stderr.strip() if result.stderr else "No error output"
                logger.warning(f"Ping failed for {ip}: {stderr_output}", extra={
                    "ip": ip,
                    "target_name": name,
                    "error": stderr_output
                })
                self.result_queue.put({
                    "name": name,
                    "ip": ip,
                    "status": "error",
                    "delay": None,
                    "timestamp": time.time()
                })
            time.sleep(5)

    def parse_ping_delay(self, output):
        # logger.debug(f"Parsing ping output: {output}")
        pattern = r'time=([\d]+(?:\.\d+)?)|time<1ms'
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            if match.group(0).lower().startswith('time<1ms'):
                logger.info("Found sub-millisecond ping might be VPN Tunnel Conflict")
                return None
            try:
                delay = float(match.group(1))
                # logger.info(f"Parsed delay: {delay} ms")
                return delay
            except ValueError:
                logger.warning(f"Failed to parse delay: {match.group(1)}")
                return None
        logger.warning("No delay found in output")
        return None
       
            # logger.debug(f"Matched delay pattern: {match.group(0)}", extra={"matched": match.group(0)})
        

    def process_results(self):
        try:
            result = self.result_queue.get_nowait()
            # logger.info(f"Processing result: {result}", extra={"result": result})
            name = result["name"]
            self.results[name].append(result)

            recent_results = list(self.results[name])
            if len(recent_results) > 0:
                failed_pings = sum(1 for r in recent_results if r["status"] in ["timeout", "error", "failed"])
                if failed_pings >= 2:
                    condition = "Disconnected"
                    avg_delay = None
                    color = "#FF0000"  # Red
                    logger.warning(f"2 or more failed pings for {name}", extra={"target_name": name, "failed_pings": failed_pings})
                else:
                    delays = [r["delay"] for r in recent_results if r["delay"] is not None]
                    if delays:
                        avg_delay = sum(delays) / len(delays)
                        if avg_delay < 200:
                            condition = "Fast"
                            status = "Connected"
                            color = "#00FF00"  # Green
                        elif 200 <= avg_delay <= 1500:
                            condition = "Slow"
                            status = "Connected"
                            color = "#FFFF00" # Yellow
                        else:
                            condition = "Dead"
                            status = "Diconnected"
                            color = "#FF0000"  # Red
                        logger.info(f"Ping condition for {name}: {condition}, Avg Delay: {avg_delay:.2f} ms",
                                    extra={"target_name": name, "condition": condition, "avg_delay": avg_delay})
                    else:
                        avg_delay = None
                        condition = "No valid data"
                        status = "NotAvailable"
                        color = "#808080"  # Gray
                        logger.info(f"No valid data for {name}", extra={"target_name": name})
                        
                if failed_pings >= 2:
                    logger.warning(f"{name} disconnected: {failed_pings}/5 failed")
                elif avg_delay:
                    logger.info(f"{name} connected - Avg Delay: {avg_delay:.2f} ms")


                self.status_frames[name].delete("all")
                base_size = int(120 * self.dpi_scale)
                self.status_frames[name].create_oval(5, 5, base_size-5, base_size-5, fill="#4A4A4A", outline="")
                self.status_frames[name].create_oval(2, 2, base_size-2, base_size-2, fill="#3A3A3A", outline="")
                self.status_frames[name].create_oval(0, 0, base_size-4, base_size-4, fill=color, outline="")

                overall_status = "green"
                for target_name in self.results:
                    target_results = list(self.results[target_name])
                    target_failed = sum(1 for r in target_results if r["status"] in ["timeout", "error", "failed"])
                    if target_failed >= 2:
                        overall_status = "red"
                        break
                self.update_tray_icon("#00FF00" if overall_status == "green" else "#FF0000")
                self.current_status = "Connected" if overall_status == "green" else "Disconnected"

                avg_delay_str = f"{avg_delay:.2f}" if avg_delay is not None else "N/A"
                log_message = (
                    f"{time.strftime('%H:%M:%S')} - {name} ({result['ip']}): "
                    f"Delay={result['delay'] if result['delay'] is not None else 'N/A'} ms,"
                    f"Avg={avg_delay_str} ms, "
                    f"Condition={condition}, Failed={failed_pings}/5\n"
                )

                self.log_text.config(state="normal")
                self.log_text.insert("end", log_message)
                self.log_text.see("end")
                self.log_text.config(state="disabled")               

            self.result_queue.task_done()
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self.process_results)
            
    def connection_notification_loop(self):
        while self.running:
            if self.current_status != self.pre_status:
                self.on_status_change_trigger(self.current_status)
                self.pre_status = self.current_status
                self.last_repeat_time = time.time()

            elif self.current_status == "Disconnected":
                if time.time() - self.last_repeat_time >= self.repeat_interval:
                    self.on_disconnected_repeat(self.current_status)
                    self.last_repeat_time = time.time()
            
            if self.pre_status == "Disconnected" and self.current_status == "Connected":
                self.icon.notify("All connections restored", "CRM Ping Monitor")
                
            time.sleep(1)
    
    def on_status_change_trigger(self, status):
        self.icon.notify(
            f"Status changed to {status}", "CRM Ping Monitor"
        )
        
    def on_disconnected_repeat(self, status):
        self.icon.notify("Still Disconnected", "CRM Ping Monitor")
        

    def start_monitoring(self):
        logger.info("Starting monitoring...")
        self.process_results()

    def stop_monitoring(self):
        logger.info("Stopping monitoring...")
        self.running = False
        if self.icon:
            self.icon.stop()
        self.root.quit()

if __name__ == "__main__":
    logger.info("Starting PingMonitor...")
    try:
        root = tk.Tk()
        monitor = PingMonitor(root)
        logger.info("PingMonitor initialized, starting monitoring...", extra={"stage": "initialized"})
        monitor.start_monitoring()
        logger.info("Starting Tkinter mainloop...", extra={"stage": "mainloop"})
        root.mainloop()
        logger.info("Mainloop exited", extra={"stage": "mainloop_exit"})
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught, stopping monitoring...", extra={"stage": "keyboard_interrupt"})
        monitor.stop_monitoring()
    except Exception as e:
        logger.error(f"Unexpected error: {e}", extra={"error": str(e), "stage": "unexpected_error"})