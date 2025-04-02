import tkinter as tk
from tkinter import messagebox, font as tkFont, colorchooser # Added colorchooser
import threading
import json # Added for settings saving/loading
import os # Added for settings file path check
import time
from pynput import mouse as pynput_mouse, keyboard
import pyautogui
from PIL import Image, ImageGrab
import mss
import mss.tools
import ctypes
import winsound
import win32api, win32con, win32gui # Kept win32gui just in case (might be used elsewhere)
import functools # Added for partial

# --- Settings File ---
SETTINGS_FILE = "settings.json"

# --- ctypes Structure Definitions (for SendInput) ---
# C struct redefinitions
PUL = ctypes.POINTER(ctypes.c_ulong)
class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]

class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput),
                 ("mi", MouseInput),
                 ("hi", HardwareInput)]

class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", Input_I)]

# --- Global Variables ---
monitoring_rect = {'x1': None, 'y1': None, 'x2': None, 'y2': None}
click_point = {'x': None, 'y': None}
# --- Color Settings ---
MAX_COLORS = 2
target_colors = [{'R': 196, 'G': 43, 'B': 39}, None] # Default Color 1 to red, Color 2 to None
target_color_tolerance = 30 # Default tolerance (internal value) - common
color_set_status = [True, False] # Whether each color is set (Color 1 is True by default)
detection_mode_var = None # StringVar to hold 'single' or 'dual' (initialized later)
current_setting_color_index = 0 # Index of the color currently being set (0 or 1)

# --- Sensitivity Settings ---
SENSITIVITY_MAP = {
    "Detection: Wide": 50,    # Tolerance 50
    "Detection: Wider": 40,   # Tolerance 40
    "Detection: Normal": 30,    # Tolerance 30
    "Detection: Narrower": 20,   # Tolerance 20
    "Detection: Narrow": 10     # Tolerance 10
}
DEFAULT_SENSITIVITY_TEXT = "Detection: Normal" # Default display text

# --- State Management ---
current_state = "Stopped" # Status name
monitoring_thread = None
stop_event = threading.Event()
consecutive_detections = [0] * MAX_COLORS # Consecutive detection count for each color

# --- Others ---
overlay_window = None
keyboard_listener = None
HOTKEY = keyboard.Key.f9
DEFAULT_BG_COLOR = None
click_count = 0
click_limit = None
click_delay = 1.0 # Default detection delay back to 1.0 second
sensitivity_var = None # Variable to hold Combobox value

# --- Settings Save and Load ---
def save_settings():
    """Saves the current settings to a JSON file."""
    settings_data = {
        'monitoring_rect': monitoring_rect,
        'click_point': click_point,
        'target_colors': target_colors,
        'target_color_tolerance': target_color_tolerance,
        'color_set_status': color_set_status,
        'detection_mode': detection_mode_var.get() if detection_mode_var else 'single',
        'click_limit': click_limit_entry.get() if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists() else "",
        'click_delay': click_delay_entry.get() if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists() else str(click_delay),
        'sensitivity': sensitivity_var.get() if sensitivity_var else DEFAULT_SENSITIVITY_TEXT,
    }
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, indent=4, ensure_ascii=False)
        print(f"Settings saved to {SETTINGS_FILE}.")
    except Exception as e:
        print(f"Error saving settings: {e}")
        # Saving error is not critical, so no messagebox

def load_settings():
    """Loads settings from the JSON file and applies them to global variables and GUI."""
    global monitoring_rect, click_point, target_colors, target_color_tolerance, color_set_status, click_delay
    if not os.path.exists(SETTINGS_FILE):
        print(f"{SETTINGS_FILE} not found. Using default settings.")
        # Default values are already set, so do nothing here
        # Could explicitly reset defaults here if needed
        return

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings_data = json.load(f)
        print(f"Settings loaded from {SETTINGS_FILE}.")

        # Apply loaded settings to global variables
        monitoring_rect = settings_data.get('monitoring_rect', monitoring_rect)
        click_point = settings_data.get('click_point', click_point)
        loaded_target_colors = settings_data.get('target_colors', target_colors)
        # Handle case where loaded_target_colors might be None or too short
        if loaded_target_colors is None:
            target_colors = [{'R': 196, 'G': 43, 'B': 39}, None]
        elif len(loaded_target_colors) < MAX_COLORS:
            target_colors = loaded_target_colors + [None] * (MAX_COLORS - len(loaded_target_colors))
        else:
             target_colors = loaded_target_colors[:MAX_COLORS] # Ensure it's not too long

        target_color_tolerance = settings_data.get('target_color_tolerance', target_color_tolerance)
        loaded_color_set_status = settings_data.get('color_set_status', color_set_status)
        # Handle case where loaded_color_set_status might be None or too short
        if loaded_color_set_status is None:
            color_set_status = [True, False]
        elif len(loaded_color_set_status) < MAX_COLORS:
             default_status = [True, False]
             color_set_status = loaded_color_set_status + default_status[len(loaded_color_set_status):]
        else:
             color_set_status = loaded_color_set_status[:MAX_COLORS] # Ensure it's not too long


        # Set values in GUI widgets (check if widgets exist first)
        if detection_mode_var:
            detection_mode_var.set(settings_data.get('detection_mode', 'single'))
        if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists():
            click_limit_entry.delete(0, tk.END)
            click_limit_entry.insert(0, settings_data.get('click_limit', ""))
        if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists():
            loaded_delay = settings_data.get('click_delay', str(click_delay))
            click_delay_entry.delete(0, tk.END)
            click_delay_entry.insert(0, loaded_delay)
            # Update click_delay global variable as well
            try:
                delay_val = float(loaded_delay)
                if delay_val >= 0: click_delay = delay_val
            except ValueError: pass # Keep default if invalid value
        if sensitivity_var:
            sensitivity_var.set(settings_data.get('sensitivity', DEFAULT_SENSITIVITY_TEXT))
            # Update target_color_tolerance as well
            on_sensitivity_change() # This will update tolerance

        print("Settings loaded and applied successfully.")

    except json.JSONDecodeError as e:
        print(f"JSON decode error reading settings file ({SETTINGS_FILE}): {e}")
        messagebox.showwarning("Settings Load Error", f"Settings file ({SETTINGS_FILE}) might be corrupted.\nStarting with default settings.", parent=root if 'root' in globals() and root.winfo_exists() else None)
    except Exception as e:
        print(f"Unexpected error loading settings: {e}")
        import traceback; traceback.print_exc()
        messagebox.showerror("Settings Load Error", f"Error loading settings:\n{e}", parent=root if 'root' in globals() and root.winfo_exists() else None)


# --- Screen Size Acquisition ---
def get_screen_size():
    try:
        user32 = ctypes.windll.user32
        screensize = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return screensize
    except Exception as e:
        print(f"Failed to get screen size: {e}")
        try: return pyautogui.size()
        except Exception:
            print("Failed to get screen size with pyautogui as well. Returning default values.")
            return (1920, 1080)

SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_size()

# --- Overlay Window Class ---
class OverlayWindow(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.current_setting_color_index = 0 # Added: Index of the color currently being set
        self.attributes('-alpha', 0.3)
        self.attributes('-topmost', True)
        self.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}+0+0")
        self.overrideredirect(True)
        self.canvas = tk.Canvas(self, bg='gray', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.mode = None # Only 'range', 'click', 'color'
        self.start_x = None; self.start_y = None
        self.current_rect_id = None; self.current_circle_id = None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", self.close_overlay)
        self.withdraw()

    def activate(self, mode, color_index=0): # Added color_index (default is 0)
        self.mode = mode
        self.current_setting_color_index = color_index # Store the target color index
        print(f"Overlay activate: mode={mode}, color_index={color_index}") # For debugging
        self.canvas.delete("all")
        # Draw existing range and click point
        if monitoring_rect['x1'] is not None: self.draw_monitor_rect(monitoring_rect['x1'], monitoring_rect['y1'], monitoring_rect['x2'], monitoring_rect['y2'])
        if click_point['x'] is not None: self.draw_click_point(click_point['x'], click_point['y'])
        # Set cursor
        if self.mode == 'range': self.config(cursor="crosshair")
        elif self.mode == 'click': self.config(cursor="fleur")
        elif self.mode == 'color': self.config(cursor="dotbox") # Color selection cursor
        else: self.config(cursor="")
        self.deiconify(); self.lift(); self.focus_force()

    def on_press(self, event):
        # if self.mode == 'color': return # Press is not needed for color mode, but handled in release
        self.start_x = event.x_root; self.start_y = event.y_root
        if self.mode == 'range':
            if self.current_rect_id: self.canvas.delete(self.current_rect_id)
            self.current_rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=2, tags="shape")
        elif self.mode == 'click':
            if click_point['x'] is not None and self.current_circle_id:
                coords = self.canvas.coords(self.current_circle_id)
                if coords:
                    cx = (coords[0] + coords[2]) / 2; cy = (coords[1] + coords[3]) / 2
                    radius_sq = ((coords[2] - coords[0]) / 2) ** 2
                    dist_sq = (event.x_root - cx)**2 + (event.y_root - cy)**2
                    if dist_sq <= radius_sq: self.canvas.itemconfig(self.current_circle_id, outline='blue')
                    else: self.start_x = None
                else: self.start_x = None
            else:
                 if self.current_circle_id: self.canvas.delete(self.current_circle_id)
                 self.draw_click_point(event.x_root, event.y_root, outline='blue')

    def on_drag(self, event):
        # if self.mode == 'color' or self.start_x is None: return # Not needed
        if self.start_x is None: return
        cur_x, cur_y = event.x_root, event.y_root
        if self.mode == 'range' and self.current_rect_id: self.canvas.coords(self.current_rect_id, self.start_x, self.start_y, cur_x, cur_y)
        elif self.mode == 'click' and self.current_circle_id:
            radius = 10
            self.canvas.coords(self.current_circle_id, cur_x - radius, cur_y - radius, cur_x + radius, cur_y + radius)

    def on_release(self, event):
        global target_colors, color_set_status # target_color -> target_colors, added color_set_status
        # Handle color selection mode
        if self.mode == 'color':
            x, y = event.x_root, event.y_root
            color_index = self.current_setting_color_index # Get the target index
            try:
                with mss.mss() as sct:
                    monitor = {"top": y, "left": x, "width": 1, "height": 1}
                    img_bytes = sct.grab(monitor)
                    img = Image.frombytes("RGB", (1, 1), img_bytes.rgb)
                    rgb = img.getpixel((0, 0))
                # Update the corresponding index in the target_colors list
                if target_colors[color_index] is None: target_colors[color_index] = {} # Create dict if None
                target_colors[color_index]['R'], target_colors[color_index]['G'], target_colors[color_index]['B'] = rgb[0], rgb[1], rgb[2]
                color_set_status[color_index] = True # Set the configured flag
                print(f"Color {color_index + 1} set: RGB({rgb[0]}, {rgb[1]}, {rgb[2]}) at ({x},{y})")
                self.master.after(0, update_color_display) # Update GUI
                self.master.after(0, lambda: set_state("Stopped")) # Return to Stopped state
                self.close_overlay() # Close overlay
            except Exception as e:
                print(f"Color capture error: {e}")
                messagebox.showerror("Error", f"Failed to capture color:\n{e}", parent=self)
                self.master.after(0, lambda: set_state("Stopped"))
                self.close_overlay()
            return

        if self.start_x is None and self.mode == 'range': return
        end_x, end_y = event.x_root, event.y_root

        if self.mode == 'range':
            if self.current_rect_id is None: return
            x1, y1 = min(self.start_x, end_x), min(self.start_y, end_y)
            x2, y2 = max(self.start_x, end_x), max(self.start_y, end_y)
            if x1 == x2 or y1 == y2:
                messagebox.showerror("Error", "Range width or height cannot be zero.", parent=self)
                self.canvas.delete(self.current_rect_id); self.current_rect_id = None
                if monitoring_rect['x1'] is not None: self.draw_monitor_rect(monitoring_rect['x1'], monitoring_rect['y1'], monitoring_rect['x2'], monitoring_rect['y2'])
            else:
                monitoring_rect['x1'], monitoring_rect['y1'] = x1, y1
                monitoring_rect['x2'], monitoring_rect['y2'] = x2, y2
                print(f"Monitoring range set: ({x1},{y1})-({x2},{y2})")
                self.draw_monitor_rect(x1, y1, x2, y2)
                self.master.after(0, update_settings_indicator)
                self.master.after(0, lambda: set_state("Stopped"))
                self.close_overlay()
        elif self.mode == 'click':
            # Removed HWND logic
            click_point['x'] = end_x; click_point['y'] = end_y
            print(f"Click point set: ({end_x},{end_y})") # Removed HWND info
            if self.current_circle_id: self.draw_click_point(end_x, end_y, outline='green')
            else: self.draw_click_point(end_x, end_y, outline='green')
            self.master.after(0, update_settings_indicator)
            self.master.after(0, lambda: set_state("Stopped"))
            self.close_overlay()
        self.start_x = None; self.start_y = None

    def draw_monitor_rect(self, x1, y1, x2, y2):
         if self.current_rect_id: self.canvas.delete(self.current_rect_id)
         self.current_rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline='red', width=2, tags="shape")

    def draw_click_point(self, x, y, outline='green'):
        if self.current_circle_id: self.canvas.delete(self.current_circle_id)
        radius = 10
        self.current_circle_id = self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=outline, width=2, tags="shape")

    def close_overlay(self, event=None):
        self.withdraw(); self.mode = None; self.config(cursor="")
        # If in a setting state ("Setting Range", "Setting Click", "Setting Color"), return to Stopped
        if current_state in ["Setting Range", "Setting Click", "Setting Color"]:
             self.master.after(0, lambda: set_state("Stopped"))


# --- State Transition Function ---
def set_state(new_state):
    # Add new UI elements and state variables to global
    global current_state, status_label, range_button, click_button, color_button_1, color_button_2, toggle_button, DEFAULT_BG_COLOR, click_limit_entry, click_delay_entry, sensitivity_combobox, detection_mode_var, single_mode_radio, dual_mode_radio, target_color_swatch_1, target_color_swatch_2, color_indicator_label_1, color_indicator_label_2 # Added color indicator labels
    previous_state = current_state
    current_state = new_state
    if 'status_label' in globals() and status_label.winfo_exists():
        status_label.config(text=f"Status: {current_state}")
        if DEFAULT_BG_COLOR is None: DEFAULT_BG_COLOR = status_label.cget("background")
        if current_state == "Monitoring": status_label.config(background="lightgreen")
        elif current_state == "Clicking": status_label.config(background="lightblue")
        else: status_label.config(background=DEFAULT_BG_COLOR) # Stopped, Setting, etc.
    print(f"Status changed: {previous_state} -> {current_state}")

    is_stopped = current_state == "Stopped"
    is_monitoring = current_state == "Monitoring"
    is_setting = current_state in ["Setting Range", "Setting Click", "Setting Color"]

    # --- Determine if monitoring can start ---
    mode = detection_mode_var.get() if detection_mode_var else 'single' # Get value if detection_mode_var is initialized
    base_conditions_met = monitoring_rect['x1'] is not None and click_point['x'] is not None
    color_conditions_met = False
    if mode == 'single':
        color_conditions_met = color_set_status[0] # OK if Color 1 is set
    elif mode == 'dual':
        color_conditions_met = color_set_status[0] and color_set_status[1] # OK if Color 1 and Color 2 are set
    can_start_monitor = base_conditions_met and color_conditions_met

    # --- Button State Control ---
    button_state = tk.NORMAL if is_stopped else tk.DISABLED
    if 'range_button' in globals() and range_button.winfo_exists(): range_button.config(state=button_state)
    if 'click_button' in globals() and click_button.winfo_exists(): click_button.config(state=button_state)
    # Color extraction buttons
    if 'color_button_1' in globals() and color_button_1.winfo_exists(): color_button_1.config(state=button_state)
    if 'color_button_2' in globals() and color_button_2.winfo_exists():
        # Color 2 extraction button enabled only in dual mode
        color_button_2.config(state=button_state if mode == 'dual' else tk.DISABLED)
    # Color swatches
    swatch_cursor = "hand2" if is_stopped else ""
    if 'target_color_swatch_1' in globals() and target_color_swatch_1.winfo_exists():
        target_color_swatch_1.config(cursor=swatch_cursor)
    if 'target_color_swatch_2' in globals() and target_color_swatch_2.winfo_exists():
        # Color 2 swatch clickable only in dual mode
        target_color_swatch_2.config(cursor=swatch_cursor if mode == 'dual' else "")

    # Start/Stop button
    if 'toggle_button' in globals() and toggle_button.winfo_exists():
        if is_monitoring: toggle_button.config(text="Stop Monitoring", state=tk.NORMAL)
        elif is_stopped: toggle_button.config(text="Start Monitoring", state=tk.NORMAL if can_start_monitor else tk.DISABLED)
        else: toggle_button.config(text="Start Monitoring", state=tk.DISABLED) # Setting, etc.

    # --- Input Field and Radio Button State Control ---
    entry_state = tk.NORMAL if is_stopped else tk.DISABLED
    if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists(): click_limit_entry.config(state=entry_state)
    if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists(): click_delay_entry.config(state=entry_state)
    if 'sensitivity_combobox' in globals() and sensitivity_combobox.winfo_exists(): sensitivity_combobox.config(state=entry_state)
    # Radio buttons (changeable only when stopped)
    radio_state = tk.NORMAL if is_stopped else tk.DISABLED
    if 'single_mode_radio' in globals() and single_mode_radio.winfo_exists(): single_mode_radio.config(state=radio_state)
    if 'dual_mode_radio' in globals() and dual_mode_radio.winfo_exists(): dual_mode_radio.config(state=radio_state)

    # --- Show/Hide Color 2 related UI ---
    # Check if detection_mode_var is not None before calling get()
    if detection_mode_var and detection_mode_var.get() == 'dual':
        if 'color_frame_2' in globals() and color_frame_2.winfo_exists():
            color_frame_2.pack(pady=5, fill=tk.X, before=click_settings_frame) # Place before click_settings_frame
        if 'color_button_2' in globals() and color_button_2.winfo_exists():
             # Use pack_info to get original position info and redisplay
            if not color_button_2.winfo_ismapped():
                color_button_2.pack(side=tk.LEFT, padx=(5, 0)) # Redisplay at original position in settings_frame
    else:
        if 'color_frame_2' in globals() and color_frame_2.winfo_exists():
            color_frame_2.pack_forget() # Hide
        if 'color_button_2' in globals() and color_button_2.winfo_exists():
            color_button_2.pack_forget() # Hide

    if root.winfo_exists():
        root.after(0, update_settings_indicator)
        root.after(0, update_remaining_clicks_display)

# --- Monitoring Thread Function (Dual Color Version) ---
def monitor_task():
    global stop_event, click_count, click_limit, target_colors, target_color_tolerance, click_delay, consecutive_detections, detection_mode_var, color_set_status
    click_count = 0
    consecutive_detections = [0] * MAX_COLORS # Reset on monitor start

    # --- Get and validate settings ---
    mode = detection_mode_var.get() # Get current mode
    print(f"Monitoring mode: {mode}")

    current_limit_str = ""
    if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists():
        current_limit_str = click_limit_entry.get()
    if current_limit_str.isdigit() and int(current_limit_str) > 0:
        click_limit = int(current_limit_str)
        print(f"Click limit set: {click_limit} times")
    else:
        click_limit = None
        print("Click limit: Unlimited")

    current_delay_str = ""
    if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists():
        current_delay_str = click_delay_entry.get()
    try:
        delay_value = float(current_delay_str)
        if delay_value >= 0: click_delay = delay_value
        else: raise ValueError("Delay must be non-negative")
        print(f"Detection interval set: {click_delay} seconds") # Text changed
    except ValueError:
        print("Invalid detection interval value. Using default (1.0 second).") # Text changed
        click_delay = 1.0
        if root.winfo_exists():
            root.after(0, lambda: click_delay_entry.delete(0, tk.END))
            root.after(0, lambda: click_delay_entry.insert(0, "1.0"))

    if root.winfo_exists(): root.after(0, update_remaining_clicks_display)
    print("Monitoring thread started")
    # --- Monitoring Loop ---
    try:
        with mss.mss() as sct:
            # --- Pre-monitoring checks (done in start_monitoring but double-check) ---
            if None in monitoring_rect.values() or None in click_point.values():
                print("Error: Monitoring range or click point not set.")
                if root.winfo_exists(): root.after(0, lambda: set_state("Stopped"))
                return
            if mode == 'single' and not color_set_status[0]:
                print("Error: Single color mode but Color 1 is not set.")
                if root.winfo_exists(): root.after(0, lambda: set_state("Stopped"))
                return
            if mode == 'dual' and not (color_set_status[0] and color_set_status[1]):
                print("Error: Dual color mode but both colors are not set.")
                if root.winfo_exists(): root.after(0, lambda: set_state("Stopped"))
                return

            monitor = {"top": monitoring_rect['y1'], "left": monitoring_rect['x1'], "width": monitoring_rect['x2'] - monitoring_rect['x1'], "height": monitoring_rect['y2'] - monitoring_rect['y1']}
            if monitor["width"] <= 0 or monitor["height"] <= 0:
                print(f"Error: Invalid monitoring range {monitor}")
                if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("Error", f"Invalid monitoring range: Width={monitor['width']}, Height={monitor['height']}"))
                if root.winfo_exists(): root.after(0, lambda: set_state("Stopped"))
                return

            # Main monitoring loop
            print("Monitoring started.")
            while not stop_event.is_set():
                try: # For screenshot capture and pixel processing
                    img_bytes = sct.grab(monitor)
                    img = Image.frombytes("RGB", (img_bytes.width, img_bytes.height), img_bytes.rgb)
                    step = 5 # Pixel check interval

                    # Pixel check
                    detected_color_index = -1 # Index of the color detected in this loop
                    for x in range(0, img.width, step):
                        for y in range(0, img.height, step):
                            try: # For getpixel
                                r, g, b = img.getpixel((x, y))
                                # --- Color Detection Logic (Single/Dual Color) ---
                                for i in range(MAX_COLORS):
                                    # Determine check target based on mode and set status
                                    if (mode == 'single' and i > 0) or not color_set_status[i]:
                                        continue
                                    tc = target_colors[i]
                                    if tc and \
                                       abs(r - tc['R']) <= target_color_tolerance and \
                                       abs(g - tc['G']) <= target_color_tolerance and \
                                       abs(b - tc['B']) <= target_color_tolerance:
                                        detected_color_index = i
                                        break # Use the first matched color
                                if detected_color_index != -1:
                                    break # Exit inner pixel check loop
                            except IndexError:
                                continue # Ignore out-of-bounds pixels
                        if detected_color_index != -1:
                            break # Exit outer pixel check loop too

                    # --- Detection Delay and Click Execution Logic (Dual Color) ---
                    if detected_color_index != -1:
                        # Increment consecutive count for the detected color
                        consecutive_detections[detected_color_index] += 1
                        print(f"Color {detected_color_index + 1} detected ({consecutive_detections[detected_color_index]} time(s)).")

                        # Reset consecutive counts for other colors
                        for i in range(MAX_COLORS):
                            if i != detected_color_index:
                                if consecutive_detections[i] > 0:
                                    print(f"Consecutive detection for Color {i + 1} broken.")
                                consecutive_detections[i] = 0

                        # Check if consecutive detection count reached 2
                        if consecutive_detections[detected_color_index] == 1:
                            # 1st detection -> Start delay
                            print(f"Starting detection delay ({click_delay} seconds)...")
                            delay_start_time = time.monotonic()
                            while time.monotonic() - delay_start_time < click_delay:
                                if stop_event.is_set():
                                    print("Stop signal received during detection delay.")
                                    break
                                time.sleep(0.05) # Reduce CPU load
                            if stop_event.is_set(): break # Exit while loop
                            # After delay, the next loop iteration will perform the 2nd check

                        elif consecutive_detections[detected_color_index] >= 2:
                            # 2nd (or more) detection -> Click execution condition met
                            print(f"Color {detected_color_index + 1} consecutive detection successful!")
                            if root.winfo_exists(): root.after(0, lambda: set_state("Clicking"))
                            print("Waiting 1 second after status change before clicking...")
                            time.sleep(1.0) # Wait before click
                            if stop_event.is_set(): break

                            # Execute click
                            send_click(click_point['x'], click_point['y'])
                            click_count += 1
                            if root.winfo_exists(): root.after(0, update_remaining_clicks_display)

                            # Wait 1 second after click
                            print("Waiting 1 second after click...")
                            time.sleep(1.0) # Wait after click
                            if stop_event.is_set(): break

                            # Check click limit
                            if click_limit is not None and click_count >= click_limit:
                                print(f"Click limit ({click_limit}) reached. Stopping monitoring.")
                                stop_event.set()
                                if root.winfo_exists():
                                    root.after(0, lambda: messagebox.showinfo("Completed", f"Completed {click_limit} clicks."))
                                    root.after(100, lambda: winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC))
                                    root.after(200, lambda: set_state("Stopped"))
                                break # Exit while loop

                            # Reset consecutive detection count and return state to Monitoring
                            consecutive_detections = [0] * MAX_COLORS # Reset all
                            if not stop_event.is_set() and root.winfo_exists():
                                root.after(0, lambda: set_state("Monitoring"))

                    else:
                        # If no color was detected, reset all consecutive detection counts
                        if any(count > 0 for count in consecutive_detections):
                             print("Target color(s) not found. Resetting consecutive detections.")
                        consecutive_detections = [0] * MAX_COLORS

                    # --- Wait for the next monitoring cycle ---
                    # Separate from the delay after the 1st consecutive detection
                    # Fixed at 1.5 seconds here (adjust if needed)
                    if not stop_event.is_set():
                        time.sleep(1.5)

                except mss.ScreenShotError as ex: # Screenshot related errors
                    print(f"Screenshot capture error: {ex}")
                    if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("Error", f"Failed to capture screenshot.\n{ex}"))
                    stop_event.set()
                    break # Exit while loop
                except Exception as e: # Other errors within the loop
                    print(f"Unexpected error during monitoring loop: {e}")
                    import traceback; traceback.print_exc()
                    if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("Error", f"Unexpected error during monitoring loop:\n{e}"))
                    stop_event.set()
                    break # Exit while loop

    except Exception as e: # Thread initialization or mss related errors
        print(f"Error during monitoring thread initialization: {e}")
        import traceback; traceback.print_exc()
        if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("Error", f"Failed to start monitoring thread:\n{e}"))
    finally:
        # Cleanup when thread ends
        print("Monitoring thread finished")
        # If state is abnormal, reset to Stopped
        if root.winfo_exists() and current_state not in ["Stopped", "Setting Range", "Setting Click", "Setting Color"]:
             root.after(0, lambda: set_state("Stopped"))

# --- SendInput Click Function (Unchanged) ---
def send_click(x, y):
    """Moves the mouse cursor to the specified coordinates and sends a click event"""
    try:
        # Click directly using SendInput with coordinates (cursor move included)
        # Need to normalize coordinates when using MOUSEEVENTF_ABSOLUTE
        screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        nx = int(x * 65535 / screen_width)
        ny = int(y * 65535 / screen_height)

        # Mouse down event (MOUSEEVENTF_MOVE added back)
        mi_down = MouseInput(dx=nx, dy=ny, mouseData=0, dwFlags=win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None)
        inp_down = Input(type=win32con.INPUT_MOUSE, ii=Input_I(mi=mi_down))

        # Mouse up event (MOUSEEVENTF_MOVE added back)
        mi_up = MouseInput(dx=nx, dy=ny, mouseData=0, dwFlags=win32con.MOUSEEVENTF_LEFTUP | win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None)
        inp_up = Input(type=win32con.INPUT_MOUSE, ii=Input_I(mi=mi_up))

        # Send events
        inputs = (Input * 2)(inp_down, inp_up)
        ctypes.windll.user32.SendInput(2, ctypes.pointer(inputs), ctypes.sizeof(Input))
        print(f"SendInput (Move): Click event sent ({x}, {y})") # Log message changed

    except Exception as e:
        print(f"send_click error: {e}")
        import traceback; traceback.print_exc()
        # Optional: Fallback to pyautogui on error
        # try:
        #     print("SendInput error, falling back to pyautogui click.")
        #     pyautogui.click(x, y)
        # except Exception as pe:
        #     print(f"pyautogui fallback also failed: {pe}")

# --- Keyboard Listener ---
def on_press_key(key):
    global HOTKEY
    if key == HOTKEY:
        print(f"Hotkey ({HOTKEY}) detected!")
        if root.winfo_exists(): root.after(0, on_toggle_button_click)

def start_keyboard_listener():
    global keyboard_listener
    if keyboard_listener is None or not keyboard_listener.is_alive():
        print("Starting keyboard listener.")
        keyboard_listener = keyboard.Listener(on_press=on_press_key)
        keyboard_listener.start()
    else: print("Keyboard listener is already running.")

def stop_keyboard_listener():
    global keyboard_listener
    if keyboard_listener is not None and keyboard_listener.is_alive():
        print("Stopping keyboard listener.")
        keyboard_listener.stop()
        keyboard_listener = None

# --- Monitoring Control Functions ---
def start_monitoring():
    global monitoring_thread, stop_event, detection_mode_var, color_set_status
    # --- Enhanced pre-start checks ---
    if monitoring_rect['x1'] is None:
        messagebox.showerror("Error", "Monitoring range is not set.")
        set_state("Stopped"); return
    if click_point['x'] is None:
        messagebox.showerror("Error", "Click point is not set.")
        set_state("Stopped"); return

    mode = detection_mode_var.get()
    if mode == 'single' and not color_set_status[0]:
        messagebox.showerror("Error", "Single color mode, but Color 1 is not set.")
        set_state("Stopped"); return
    if mode == 'dual' and not (color_set_status[0] and color_set_status[1]):
        messagebox.showerror("Error", "Dual color mode, but both colors are not set.")
        set_state("Stopped"); return

    if monitoring_thread is None or not monitoring_thread.is_alive():
        print("Preparing to start monitoring thread.")
        stop_event.clear()
        monitoring_thread = threading.Thread(target=monitor_task, daemon=True)
        monitoring_thread.start()
        set_state("Monitoring")
    else: print("Monitoring thread is already running.")

def stop_monitoring():
    global monitoring_thread, stop_event
    if monitoring_thread is not None and monitoring_thread.is_alive():
        print("Sending stop signal to monitoring thread.")
        stop_event.set()
        monitoring_thread.join(timeout=0.5)
        if monitoring_thread.is_alive(): print("Warning: Monitoring thread did not terminate in time.")
        monitoring_thread = None
    if current_state not in ["Stopped", "Setting Range", "Setting Click", "Setting Color"]:
        set_state("Stopped")

# --- GUI Event Handlers ---
def on_range_button_click():
    global overlay_window
    if current_state == "Stopped":
        set_state("Setting Range")
        if overlay_window is None: overlay_window = OverlayWindow(root)
        overlay_window.activate('range')
    elif current_state == "Setting Range":
         if overlay_window: overlay_window.close_overlay()
         set_state("Stopped")

def on_click_button_click():
    global overlay_window
    if current_state == "Stopped":
        set_state("Setting Click")
        if overlay_window is None: overlay_window = OverlayWindow(root)
        overlay_window.activate('click')
    elif current_state == "Setting Click":
         if overlay_window: overlay_window.close_overlay()
         set_state("Stopped")

# --- Color Setting Event Handlers (Dual Color) ---
def on_color_swatch_click(event=None, color_index=0):
    """Open color picker on color swatch click (specify index)"""
    global target_colors, color_set_status
    if current_state == "Stopped":
        # If not in dual mode, changing Color 2 is not allowed
        if detection_mode_var.get() == 'single' and color_index == 1:
             messagebox.showwarning("Warning", "Color 2 cannot be used in single color mode.", parent=root)
             return

        current_color = target_colors[color_index]
        initial_color_hex = "white" # Default
        if current_color:
            try: initial_color_hex = f"#{current_color['R']:02x}{current_color['G']:02x}{current_color['B']:02x}"
            except KeyError: pass # In case of incomplete dict

        color_code = colorchooser.askcolor(title=f"Select Detection Color {color_index + 1}", initialcolor=initial_color_hex, parent=root)
        if color_code and color_code[0]:
            rgb = color_code[0]
            if target_colors[color_index] is None: target_colors[color_index] = {}
            target_colors[color_index]['R'], target_colors[color_index]['G'], target_colors[color_index]['B'] = int(rgb[0]), int(rgb[1]), int(rgb[2])
            color_set_status[color_index] = True
            print(f"Color {color_index + 1} set via color picker: RGB({rgb[0]}, {rgb[1]}, {rgb[2]})")
            update_color_display()
            set_state("Stopped") # Update state (for button enable/disable)
    else:
        messagebox.showwarning("Warning", "Color can only be changed when stopped.", parent=root)

def on_color_button_click(color_index=0): # Color extraction button (specify index)
    """Extract the color for the specified index"""
    global overlay_window
    if current_state == "Stopped":
        # If not in dual mode, extracting Color 2 is not allowed
        if detection_mode_var.get() == 'single' and color_index == 1:
             messagebox.showwarning("Warning", "Color 2 cannot be used in single color mode.", parent=root)
             return
        set_state("Setting Color")
        if overlay_window is None: overlay_window = OverlayWindow(root)
        overlay_window.activate('color', color_index=color_index) # Pass the index
    elif current_state == "Setting Color":
         if overlay_window: overlay_window.close_overlay()
         set_state("Stopped")

# --- Detection Mode Change Callback ---
def on_detection_mode_change():
    global detection_mode_var
    mode = detection_mode_var.get()
    print(f"Detection mode changed: {mode}")
    # Update state to refresh UI (especially show/hide and enable/disable Color 2 elements)
    set_state(current_state) # Reapply current state to update UI
    update_settings_indicator() # Update color setting indicators too

def on_toggle_button_click():
    if current_state == "Monitoring": stop_monitoring()
    elif current_state == "Stopped":
        start_monitoring() # Pre-start checks are done within start_monitoring

def check_thread_and_destroy():
    """Check if the monitoring thread has stopped, then destroy the window"""
    global monitoring_thread
    if monitoring_thread is not None and monitoring_thread.is_alive():
        print("Waiting for monitoring thread to stop...")
        root.after(100, check_thread_and_destroy) # Check again after 100ms
    else:
        print("Monitoring thread stopped. Destroying window.")
        if root.winfo_exists():
            root.destroy()

def on_closing():
    """Handle window closing event"""
    print("Window is closing.")
    print("Saving settings...")
    save_settings() # Save settings
    print("Stopping monitoring thread and listener...")
    stop_monitoring() # Send stop signal to thread (don't wait with join here)
    stop_keyboard_listener()
    print("Starting thread wait and window destroy process.")
    # Wait for the thread to stop before destroying the window
    check_thread_and_destroy()

# --- GUI Update Functions ---
def update_settings_indicator():
    global range_indicator_label, click_indicator_label, color_indicator_label_1, color_indicator_label_2, color_set_status, detection_mode_var
    range_set = monitoring_rect['x1'] is not None
    click_set = click_point['x'] is not None
    mode = detection_mode_var.get() if detection_mode_var else 'single'

    # Range and Click
    if 'range_indicator_label' in globals() and range_indicator_label.winfo_exists():
        range_indicator_label.config(text="Range: OK" if range_set else "Range: Not Set", fg="green" if range_set else "red")
    if 'click_indicator_label' in globals() and click_indicator_label.winfo_exists():
        click_indicator_label.config(text="Click: OK" if click_set else "Click: Not Set", fg="green" if click_set else "red")

    # Color 1
    color1_set = color_set_status[0]
    if 'color_indicator_label_1' in globals() and color_indicator_label_1.winfo_exists():
        color_indicator_label_1.config(text="Color1: OK" if color1_set else "Color1: Not Set", fg="green" if color1_set else "red")

    # Color 2 (Show/Update only in dual mode)
    if 'color_indicator_label_2' in globals() and color_indicator_label_2.winfo_exists():
        if mode == 'dual':
            color2_set = color_set_status[1]
            color_indicator_label_2.config(text="Color2: OK" if color2_set else "Color2: Not Set", fg="green" if color2_set else "red")
            # Show label if it's not already visible
            if not color_indicator_label_2.winfo_ismapped():
                 color_indicator_label_2.pack(side=tk.LEFT, padx=(10, 0)) # Display on the right within indicator_frame
        else:
            # Hide in single color mode
            color_indicator_label_2.pack_forget()


def update_color_display():
    global target_colors, target_color_label_1, target_color_swatch_1, target_color_label_2, target_color_swatch_2
    # Update Color 1 display
    if 'target_color_label_1' in globals() and target_color_label_1.winfo_exists():
        color1 = target_colors[0]
        if color1 and color_set_status[0]:
            rgb_str = f"RGB({color1.get('R', '?')}, {color1.get('G', '?')}, {color1.get('B', '?')})"
            target_color_label_1.config(text=f"Target Color 1: {rgb_str}")
            try:
                hex_color = f"#{color1['R']:02x}{color1['G']:02x}{color1['B']:02x}"
                target_color_swatch_1.config(bg=hex_color)
            except (KeyError, TypeError, ValueError) as e:
                print(f"Error updating Color 1 display: {e}")
                target_color_swatch_1.config(bg="white")
        else:
            target_color_label_1.config(text="Target Color 1: Not Set")
            target_color_swatch_1.config(bg="white")

    # Update Color 2 display
    if 'target_color_label_2' in globals() and target_color_label_2.winfo_exists():
        color2 = target_colors[1]
        if color2 and color_set_status[1]:
            rgb_str = f"RGB({color2.get('R', '?')}, {color2.get('G', '?')}, {color2.get('B', '?')})"
            target_color_label_2.config(text=f"Target Color 2: {rgb_str}")
            try:
                hex_color = f"#{color2['R']:02x}{color2['G']:02x}{color2['B']:02x}"
                target_color_swatch_2.config(bg=hex_color)
            except (KeyError, TypeError, ValueError) as e:
                print(f"Error updating Color 2 display: {e}")
                target_color_swatch_2.config(bg="white")
        else:
            target_color_label_2.config(text="Target Color 2: Not Set")
            target_color_swatch_2.config(bg="white")

def update_remaining_clicks_display():
    global remaining_clicks_label, click_limit, click_count
    if 'remaining_clicks_label' in globals() and remaining_clicks_label.winfo_exists():
        if current_state == "Monitoring" and click_limit is not None:
            remaining = click_limit - click_count
            remaining_clicks_label.config(text=f"Remaining: {remaining}")
        else:
            remaining_clicks_label.config(text="Remaining: ---")

# --- Input Validation Functions ---
def validate_click_limit(P):
    if P == "" or P.isdigit(): return True
    else: return False

def validate_click_delay(P):
    if P == "": return True
    try:
        val = float(P)
        return val >= 0
    except ValueError:
        if P == '.' or (P.count('.') == 1 and P.replace('.', '', 1).isdigit()): return True
        return False

# --- Sensitivity Change Callback ---
def on_sensitivity_change(event=None):
    global target_color_tolerance, sensitivity_var
    selected_text = sensitivity_var.get()
    if selected_text in SENSITIVITY_MAP:
        target_color_tolerance = SENSITIVITY_MAP[selected_text]
        print(f"Detection range changed: {selected_text} (Tolerance = {target_color_tolerance})")
    else:
        print(f"Error: Unknown sensitivity text '{selected_text}'")
        # Revert to default if unexpected value
        sensitivity_var.set(DEFAULT_SENSITIVITY_TEXT)
        target_color_tolerance = SENSITIVITY_MAP[DEFAULT_SENSITIVITY_TEXT]

# --- GUI Setup ---
from tkinter import ttk

root = tk.Tk()
root.title("Cline Retry Auto Clicker") # Title
root.attributes("-topmost", True)
root.resizable(False, False)
try:
    # Set window icon (if aikon.ico exists)
    root.iconbitmap('aikon.ico')
except tk.TclError:
    print("Warning: aikon.ico not found or invalid icon file. Using default icon.")

# --- Style Settings ---
default_font = tkFont.nametofont("TkDefaultFont")
default_font.configure(size=9)
root.option_add("*Font", default_font)

# --- Widget Placement ---
main_frame = tk.Frame(root, padx=10, pady=10)
main_frame.pack(fill=tk.BOTH, expand=True)

# Status
status_label = tk.Label(main_frame, text=f"Status: {current_state}", font=("Arial", 11, "bold"), wraplength=380)
status_label.pack(pady=(0, 10), fill=tk.X)

# --- Detection Mode Selection ---
mode_frame = tk.Frame(main_frame)
mode_frame.pack(pady=2, fill=tk.X)
detection_mode_var = tk.StringVar(root, value='single') # Default to single color mode
single_mode_radio = tk.Radiobutton(mode_frame, text="Single Color", variable=detection_mode_var, value='single', command=on_detection_mode_change)
single_mode_radio.pack(side=tk.LEFT, padx=(0, 10))
dual_mode_radio = tk.Radiobutton(mode_frame, text="Dual Color", variable=detection_mode_var, value='dual', command=on_detection_mode_change)
dual_mode_radio.pack(side=tk.LEFT)

# --- Settings Status Indicators ---
indicator_frame = tk.Frame(main_frame)
indicator_frame.pack(pady=2, fill=tk.X)
range_indicator_label = tk.Label(indicator_frame, text="Range: Not Set", fg="red")
range_indicator_label.pack(side=tk.LEFT, padx=(0, 10))
click_indicator_label = tk.Label(indicator_frame, text="Click: Not Set", fg="red")
click_indicator_label.pack(side=tk.LEFT, padx=(0, 10))
color_indicator_label_1 = tk.Label(indicator_frame, text="Color1: Not Set", fg="red")
color_indicator_label_1.pack(side=tk.LEFT)
color_indicator_label_2 = tk.Label(indicator_frame, text="Color2: Not Set", fg="red")
# Color 2 indicator is shown/hidden by set_state, not packed here initially

# --- Settings Buttons ---
settings_frame = tk.Frame(main_frame)
settings_frame.pack(pady=5, fill=tk.X)
range_button = tk.Button(settings_frame, text="Set Range", command=on_range_button_click, width=11) # Adjusted width
range_button.pack(side=tk.LEFT, padx=(0, 5))
click_button = tk.Button(settings_frame, text="Set Click", command=on_click_button_click, width=11) # Adjusted width
click_button.pack(side=tk.LEFT, padx=5)
# Color extraction button (for Color 1) - Use functools.partial to pass index
color_button_1 = tk.Button(settings_frame, text="Extract C1", command=functools.partial(on_color_button_click, color_index=0), width=11) # Adjusted width
color_button_1.pack(side=tk.LEFT, padx=5)
# Color extraction button (for Color 2) - Initially hidden. Display controlled by set_state
color_button_2 = tk.Button(settings_frame, text="Extract C2", command=functools.partial(on_color_button_click, color_index=1), width=11) # Adjusted width
# color_button_2.pack(side=tk.LEFT, padx=(5, 0)) # Initially hidden

# --- Color Display (Color 1) ---
color_frame_1 = tk.Frame(main_frame)
color_frame_1.pack(pady=5, fill=tk.X)
target_color_label_1 = tk.Label(color_frame_1, text="Target Color 1: Not Set")
target_color_label_1.pack(side=tk.LEFT)
target_color_swatch_1 = tk.Canvas(color_frame_1, width=18, height=18, bg="white", relief="sunken", borderwidth=1)
target_color_swatch_1.pack(side=tk.LEFT, padx=5)
# Use functools.partial to pass index on click
target_color_swatch_1.bind("<Button-1>", functools.partial(on_color_swatch_click, color_index=0))

# --- Color Display (Color 2) ---
# Initially hidden. Display controlled by set_state
color_frame_2 = tk.Frame(main_frame)
# color_frame_2.pack(pady=5, fill=tk.X) # Initially hidden
target_color_label_2 = tk.Label(color_frame_2, text="Target Color 2: Not Set")
target_color_label_2.pack(side=tk.LEFT)
target_color_swatch_2 = tk.Canvas(color_frame_2, width=18, height=18, bg="white", relief="sunken", borderwidth=1)
target_color_swatch_2.pack(side=tk.LEFT, padx=5)
target_color_swatch_2.bind("<Button-1>", functools.partial(on_color_swatch_click, color_index=1))


# --- Click Settings (Grid layout) ---
click_settings_frame = tk.Frame(main_frame)
click_settings_frame.pack(pady=5, fill=tk.X)
click_settings_frame.columnconfigure(1, weight=0) # Entry/Combobox column
click_settings_frame.columnconfigure(2, weight=1) # Remaining clicks display column (for right alignment)

# Click Limit (row=0)
limit_label = tk.Label(click_settings_frame, text="Click Limit (0/empty=unlimited):")
limit_label.grid(row=0, column=0, sticky='w', padx=(0, 5)) # Adjusted padx
vcmd_limit = (root.register(validate_click_limit), '%P')
click_limit_entry = tk.Entry(click_settings_frame, width=7, validate='key', validatecommand=vcmd_limit)
click_limit_entry.grid(row=0, column=1, sticky='w')
remaining_clicks_label = tk.Label(click_settings_frame, text="Remaining: ---")
remaining_clicks_label.grid(row=0, column=2, sticky='e', padx=(10, 0)) # Right align

# Delay (Detection Interval) (row=1)
delay_label = tk.Label(click_settings_frame, text="Detection Interval (sec):") # Changed label text
delay_label.grid(row=1, column=0, sticky='w', padx=(0, 5), pady=(5,0)) # Adjusted padx
vcmd_delay = (root.register(validate_click_delay), '%P')
click_delay_entry = tk.Entry(click_settings_frame, width=7, validate='key', validatecommand=vcmd_delay)
click_delay_entry.insert(0, str(click_delay))
click_delay_entry.grid(row=1, column=1, sticky='w', pady=(5,0))

# Sensitivity (Detection Range) (row=2)
sensitivity_label = tk.Label(click_settings_frame, text="Detection Range:") # Changed label text
sensitivity_label.grid(row=2, column=0, sticky='w', padx=(0, 5), pady=(5,0)) # Adjusted padx
sensitivity_var = tk.StringVar(root) # Specify root as master
sensitivity_var.set(DEFAULT_SENSITIVITY_TEXT) # Set default text display
sensitivity_combobox = ttk.Combobox(click_settings_frame, textvariable=sensitivity_var, values=list(SENSITIVITY_MAP.keys()), width=15, state="readonly") # Adjusted width, set values to text keys
sensitivity_combobox.grid(row=2, column=1, sticky='w', pady=(5,0))
sensitivity_combobox.bind("<<ComboboxSelected>>", on_sensitivity_change) # Event binding

# Control Buttons
control_frame = tk.Frame(main_frame)
control_frame.pack(pady=10)
toggle_button = tk.Button(control_frame, text="Start Monitoring", command=on_toggle_button_click, width=15, state=tk.DISABLED)
toggle_button.pack()
hotkey_label = tk.Label(control_frame, text=f"Hotkey: {HOTKEY.name.upper()} (Start/Stop)", fg="gray50")
hotkey_label.pack(pady=(5, 0))

root.protocol("WM_DELETE_WINDOW", on_closing)

# --- Main Loop ---
if __name__ == "__main__":
    overlay_window = OverlayWindow(root)
    # detection_mode_var initialization moved to Radiobutton creation
    # sensitivity_var initialization moved to Combobox creation

    # ★★★ Load settings after GUI elements are created ★★★
    load_settings()

    # ★★★ Update UI state after loading settings ★★★
    set_state("Stopped") # Initial state setting (also determines initial state of UI elements)
    update_color_display() # Update color display based on loaded settings
    update_settings_indicator() # Update indicator display based on loaded settings
    on_detection_mode_change() # Reconfigure UI based on loaded mode

    start_keyboard_listener()
    root.mainloop()
