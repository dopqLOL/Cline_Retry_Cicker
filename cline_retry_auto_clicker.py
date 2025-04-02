import tkinter as tk
from tkinter import messagebox, font as tkFont, colorchooser # colorchooserを追加
import threading
import json # 設定保存用にjsonをインポート
import os # 設定ファイルのパス判定用にosをインポート
import time
from pynput import mouse as pynput_mouse, keyboard
import pyautogui
from PIL import Image, ImageGrab
import mss
import mss.tools
import ctypes
import winsound
import win32api, win32con, win32gui # win32gui は念のため残す (他の箇所で使われる可能性)
import functools # partialを使うためにインポート (既に下にあったが、念のため上部に移動)

# --- 設定ファイル ---
SETTINGS_FILE = "settings.json"

# --- ctypes 構造体定義 (SendInput用) ---
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

# --- グローバル変数 ---
monitoring_rect = {'x1': None, 'y1': None, 'x2': None, 'y2': None}
click_point = {'x': None, 'y': None}
# --- 色設定関連 ---
MAX_COLORS = 2
target_colors = [{'R': 196, 'G': 43, 'B': 39}, None] # 色1のデフォルトを赤に, 色2はNone
target_color_tolerance = 30 # デフォルトの許容誤差 (内部値) - 共通
color_set_status = [True, False] # 各色が設定されているか (色1はデフォルトでTrue)
detection_mode_var = None # 'single' or 'dual' を保持するStringVar (後で初期化)
current_setting_color_index = 0 # 現在設定対象の色インデックス (0 or 1)

# --- 感度設定 ---
SENSITIVITY_MAP = {
    "判定: 広い": 50,    # Tolerance 50
    "判定: 広め": 40,   # Tolerance 40
    "判定: 普通": 30,    # Tolerance 30
    "判定: 狭め": 20,   # Tolerance 20
    "判定: 狭い": 10     # Tolerance 10
}
DEFAULT_SENSITIVITY_TEXT = "判定: 普通" # デフォルトの表示テキスト

# --- 状態管理 ---
current_state = "停止中" # ステータス名を変更
monitoring_thread = None
stop_event = threading.Event()
consecutive_detections = [0] * MAX_COLORS # 各色の連続検出回数

# --- その他 ---
overlay_window = None
keyboard_listener = None
HOTKEY = keyboard.Key.f9
DEFAULT_BG_COLOR = None
click_count = 0
click_limit = None
click_delay = 1.0 # デフォルトの判定ディレイを1.0秒に戻す
sensitivity_var = None # Comboboxの値を保持する変数

# --- 設定の保存と読み込み ---
def save_settings():
    """現在の設定をJSONファイルに保存する"""
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
        print(f"設定を {SETTINGS_FILE} に保存しました。")
    except Exception as e:
        print(f"設定の保存中にエラーが発生しました: {e}")
        # 保存エラーは致命的ではないので、メッセージボックスは表示しない

def load_settings():
    """JSONファイルから設定を読み込み、グローバル変数とGUIに反映する"""
    global monitoring_rect, click_point, target_colors, target_color_tolerance, color_set_status, click_delay
    if not os.path.exists(SETTINGS_FILE):
        print(f"{SETTINGS_FILE} が見つかりません。デフォルト設定を使用します。")
        # デフォルト値が既に設定されているので、ここでは何もしない
        # 必要であれば、ここで明示的にデフォルト値を再設定しても良い
        return

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings_data = json.load(f)
        print(f"{SETTINGS_FILE} から設定を読み込みました。")

        # 各設定値をグローバル変数に反映
        monitoring_rect = settings_data.get('monitoring_rect', monitoring_rect)
        click_point = settings_data.get('click_point', click_point)
        target_colors = settings_data.get('target_colors', target_colors)
        # target_colorsがNoneの場合の処理を追加
        if target_colors is None: target_colors = [{'R': 196, 'G': 43, 'B': 39}, None]
        elif len(target_colors) < MAX_COLORS: # 要素数が足りない場合も補完
             target_colors.extend([None] * (MAX_COLORS - len(target_colors)))

        target_color_tolerance = settings_data.get('target_color_tolerance', target_color_tolerance)
        color_set_status = settings_data.get('color_set_status', color_set_status)
        # color_set_statusがNoneの場合や要素数が足りない場合の処理を追加
        if color_set_status is None: color_set_status = [True, False]
        elif len(color_set_status) < MAX_COLORS:
             default_status = [True, False] # デフォルト
             # 既存の設定を維持しつつ足りない分を追加
             color_set_status.extend(default_status[len(color_set_status):])


        # GUIウィジェットに値を設定 (ウィジェットが存在するか確認してから)
        if detection_mode_var:
            detection_mode_var.set(settings_data.get('detection_mode', 'single'))
        if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists():
            click_limit_entry.delete(0, tk.END)
            click_limit_entry.insert(0, settings_data.get('click_limit', ""))
        if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists():
            loaded_delay = settings_data.get('click_delay', str(click_delay))
            click_delay_entry.delete(0, tk.END)
            click_delay_entry.insert(0, loaded_delay)
            # click_delay グローバル変数も更新
            try:
                delay_val = float(loaded_delay)
                if delay_val >= 0: click_delay = delay_val
            except ValueError: pass # 不正な値ならデフォルト維持
        if sensitivity_var:
            sensitivity_var.set(settings_data.get('sensitivity', DEFAULT_SENSITIVITY_TEXT))
            # target_color_tolerance も更新
            on_sensitivity_change() # これでtoleranceも更新される

        print("設定の読み込みと適用が完了しました。")

    except json.JSONDecodeError as e:
        print(f"設定ファイル ({SETTINGS_FILE}) の読み込み中にJSONデコードエラーが発生しました: {e}")
        messagebox.showwarning("設定読み込みエラー", f"設定ファイル ({SETTINGS_FILE}) が破損している可能性があります。\nデフォルト設定で起動します。", parent=root if 'root' in globals() and root.winfo_exists() else None)
    except Exception as e:
        print(f"設定の読み込み中に予期せぬエラーが発生しました: {e}")
        import traceback; traceback.print_exc()
        messagebox.showerror("設定読み込みエラー", f"設定の読み込み中にエラーが発生しました:\n{e}", parent=root if 'root' in globals() and root.winfo_exists() else None)


# --- 画面サイズ取得 ---
def get_screen_size():
    try:
        user32 = ctypes.windll.user32
        screensize = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return screensize
    except Exception as e:
        print(f"画面サイズの取得に失敗しました: {e}")
        try: return pyautogui.size()
        except Exception:
            print("pyautoguiでも画面サイズの取得に失敗。デフォルト値を返します。")
            return (1920, 1080)

SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_size()

# --- オーバーレイウィンドウクラス ---
class OverlayWindow(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.current_setting_color_index = 0 # 追加: 現在設定中の色インデックス
        self.attributes('-alpha', 0.3)
        self.attributes('-topmost', True)
        self.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}+0+0")
        self.overrideredirect(True)
        self.canvas = tk.Canvas(self, bg='gray', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.mode = None # 'range', 'click' のみ
        self.start_x = None; self.start_y = None
        self.current_rect_id = None; self.current_circle_id = None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", self.close_overlay)
        self.withdraw()

    def activate(self, mode, color_index=0): # color_index を追加 (デフォルトは0)
        self.mode = mode
        self.current_setting_color_index = color_index # 設定対象の色インデックスを保持
        print(f"Overlay activate: mode={mode}, color_index={color_index}") # デバッグ用
        self.canvas.delete("all")
        # 既存の範囲とクリック地点を描画
        if monitoring_rect['x1'] is not None: self.draw_monitor_rect(monitoring_rect['x1'], monitoring_rect['y1'], monitoring_rect['x2'], monitoring_rect['y2'])
        if click_point['x'] is not None: self.draw_click_point(click_point['x'], click_point['y'])
        # カーソル設定
        if self.mode == 'range': self.config(cursor="crosshair")
        elif self.mode == 'click': self.config(cursor="fleur")
        elif self.mode == 'color': self.config(cursor="dotbox") # 色選択カーソル復活
        else: self.config(cursor="")
        self.deiconify(); self.lift(); self.focus_force()

    def on_press(self, event):
        # if self.mode == 'color': return # 色選択モードでも押下は不要だが、releaseで処理するのでコメントアウト
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
        # if self.mode == 'color' or self.start_x is None: return # 不要
        if self.start_x is None: return
        cur_x, cur_y = event.x_root, event.y_root
        if self.mode == 'range' and self.current_rect_id: self.canvas.coords(self.current_rect_id, self.start_x, self.start_y, cur_x, cur_y)
        elif self.mode == 'click' and self.current_circle_id:
            radius = 10
            self.canvas.coords(self.current_circle_id, cur_x - radius, cur_y - radius, cur_x + radius, cur_y + radius)

    def on_release(self, event):
        global target_colors, color_set_status # target_color -> target_colors, color_set_status追加
        # 色選択モードの処理
        if self.mode == 'color':
            x, y = event.x_root, event.y_root
            color_index = self.current_setting_color_index # 設定対象のインデックスを取得
            try:
                with mss.mss() as sct:
                    monitor = {"top": y, "left": x, "width": 1, "height": 1}
                    img_bytes = sct.grab(monitor)
                    img = Image.frombytes("RGB", (1, 1), img_bytes.rgb)
                    rgb = img.getpixel((0, 0))
                # target_colors リストの該当インデックスを更新
                if target_colors[color_index] is None: target_colors[color_index] = {} # Noneなら辞書を作成
                target_colors[color_index]['R'], target_colors[color_index]['G'], target_colors[color_index]['B'] = rgb[0], rgb[1], rgb[2]
                color_set_status[color_index] = True # 設定済みフラグを立てる
                print(f"色{color_index + 1} 設定完了: RGB({rgb[0]}, {rgb[1]}, {rgb[2]}) at ({x},{y})")
                self.master.after(0, update_color_display) # GUI更新
                self.master.after(0, lambda: set_state("停止中")) # 状態を戻す
                self.close_overlay() # オーバーレイを閉じる
            except Exception as e:
                print(f"色取得エラー: {e}")
                messagebox.showerror("エラー", f"色の取得に失敗しました:\n{e}", parent=self)
                self.master.after(0, lambda: set_state("停止中"))
                self.close_overlay()
            return

        if self.start_x is None and self.mode == 'range': return
        end_x, end_y = event.x_root, event.y_root

        if self.mode == 'range':
            if self.current_rect_id is None: return
            x1, y1 = min(self.start_x, end_x), min(self.start_y, end_y)
            x2, y2 = max(self.start_x, end_x), max(self.start_y, end_y)
            if x1 == x2 or y1 == y2:
                messagebox.showerror("エラー", "範囲の幅または高さが0です。", parent=self)
                self.canvas.delete(self.current_rect_id); self.current_rect_id = None
                if monitoring_rect['x1'] is not None: self.draw_monitor_rect(monitoring_rect['x1'], monitoring_rect['y1'], monitoring_rect['x2'], monitoring_rect['y2'])
            else:
                monitoring_rect['x1'], monitoring_rect['y1'] = x1, y1
                monitoring_rect['x2'], monitoring_rect['y2'] = x2, y2
                print(f"監視範囲設定完了: ({x1},{y1})-({x2},{y2})")
                self.draw_monitor_rect(x1, y1, x2, y2)
                self.master.after(0, update_settings_indicator)
                self.master.after(0, lambda: set_state("停止中")) # アイドル -> 停止中
                self.close_overlay()
        elif self.mode == 'click':
            # HWND取得ロジックを削除
            click_point['x'] = end_x; click_point['y'] = end_y
            print(f"クリック地点設定完了: ({end_x},{end_y})") # HWND情報を削除
            if self.current_circle_id: self.draw_click_point(end_x, end_y, outline='green')
            else: self.draw_click_point(end_x, end_y, outline='green')
            self.master.after(0, update_settings_indicator)
            self.master.after(0, lambda: set_state("停止中")) # アイドル -> 停止中
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
        # 状態が設定中("範囲設定中", "クリック設定中", "色設定中")なら停止中に戻す
        if current_state in ["範囲設定中", "クリック設定中", "色設定中"]:
             self.master.after(0, lambda: set_state("停止中"))


# --- 状態遷移関数 ---
def set_state(new_state):
    # グローバル変数に新しいUI要素と状態変数を追加
    global current_state, status_label, range_button, click_button, color_button_1, color_button_2, toggle_button, DEFAULT_BG_COLOR, click_limit_entry, click_delay_entry, sensitivity_combobox, detection_mode_var, single_mode_radio, dual_mode_radio, target_color_swatch_1, target_color_swatch_2, color_indicator_label_1, color_indicator_label_2 # 色インジケータラベル追加
    previous_state = current_state
    current_state = new_state
    if 'status_label' in globals() and status_label.winfo_exists():
        status_label.config(text=f"ステータス: {current_state}")
        if DEFAULT_BG_COLOR is None: DEFAULT_BG_COLOR = status_label.cget("background")
        if current_state == "監視中": status_label.config(background="lightgreen")
        elif current_state == "クリック実行": status_label.config(background="lightblue")
        else: status_label.config(background=DEFAULT_BG_COLOR) # 停止中、設定中など
    print(f"ステータス変更: {previous_state} -> {current_state}")

    is_stopped = current_state == "停止中"
    is_monitoring = current_state == "監視中"
    is_setting = current_state in ["範囲設定中", "クリック設定中", "色設定中"]

    # --- 監視開始可能かの判定 ---
    mode = detection_mode_var.get() if detection_mode_var else 'single' # detection_mode_varが初期化されていれば値を取得
    base_conditions_met = monitoring_rect['x1'] is not None and click_point['x'] is not None
    color_conditions_met = False
    if mode == 'single':
        color_conditions_met = color_set_status[0] # 色1が設定されていればOK
    elif mode == 'dual':
        color_conditions_met = color_set_status[0] and color_set_status[1] # 色1と色2が設定されていればOK
    can_start_monitor = base_conditions_met and color_conditions_met

    # --- ボタンの状態制御 ---
    button_state = tk.NORMAL if is_stopped else tk.DISABLED
    if 'range_button' in globals() and range_button.winfo_exists(): range_button.config(state=button_state)
    if 'click_button' in globals() and click_button.winfo_exists(): click_button.config(state=button_state)
    # 色抽出ボタン
    if 'color_button_1' in globals() and color_button_1.winfo_exists(): color_button_1.config(state=button_state)
    if 'color_button_2' in globals() and color_button_2.winfo_exists():
        # 色2抽出ボタンはデュアルモード選択時のみ有効
        color_button_2.config(state=button_state if mode == 'dual' else tk.DISABLED)
    # 色見本
    swatch_cursor = "hand2" if is_stopped else ""
    if 'target_color_swatch_1' in globals() and target_color_swatch_1.winfo_exists():
        target_color_swatch_1.config(cursor=swatch_cursor)
    if 'target_color_swatch_2' in globals() and target_color_swatch_2.winfo_exists():
        # 色2見本はデュアルモード選択時のみクリック可能
        target_color_swatch_2.config(cursor=swatch_cursor if mode == 'dual' else "")

    # 開始/停止ボタン
    if 'toggle_button' in globals() and toggle_button.winfo_exists():
        if is_monitoring: toggle_button.config(text="監視 停止", state=tk.NORMAL)
        elif is_stopped: toggle_button.config(text="監視 開始", state=tk.NORMAL if can_start_monitor else tk.DISABLED)
        else: toggle_button.config(text="監視 開始", state=tk.DISABLED) # 設定中など

    # --- 入力欄とラジオボタンの状態制御 ---
    entry_state = tk.NORMAL if is_stopped else tk.DISABLED
    if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists(): click_limit_entry.config(state=entry_state)
    if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists(): click_delay_entry.config(state=entry_state)
    if 'sensitivity_combobox' in globals() and sensitivity_combobox.winfo_exists(): sensitivity_combobox.config(state=entry_state)
    # ラジオボタン (停止中のみ変更可能)
    radio_state = tk.NORMAL if is_stopped else tk.DISABLED
    if 'single_mode_radio' in globals() and single_mode_radio.winfo_exists(): single_mode_radio.config(state=radio_state)
    if 'dual_mode_radio' in globals() and dual_mode_radio.winfo_exists(): dual_mode_radio.config(state=radio_state)

    # --- 色2関連UIの表示/非表示 ---
    # detection_mode_var が None でないことを確認してから get() を呼び出す
    if detection_mode_var and detection_mode_var.get() == 'dual':
        if 'color_frame_2' in globals() and color_frame_2.winfo_exists():
            color_frame_2.pack(pady=5, fill=tk.X, before=click_settings_frame) # click_settings_frame の前に配置
        if 'color_button_2' in globals() and color_button_2.winfo_exists():
             # pack_info を使って元の位置情報を取得し、再表示
            if not color_button_2.winfo_ismapped():
                color_button_2.pack(side=tk.LEFT, padx=(5, 0)) # settings_frame 内の元の位置に再表示
    else:
        if 'color_frame_2' in globals() and color_frame_2.winfo_exists():
            color_frame_2.pack_forget() # 非表示
        if 'color_button_2' in globals() and color_button_2.winfo_exists():
            color_button_2.pack_forget() # 非表示

    if root.winfo_exists():
        root.after(0, update_settings_indicator)
        root.after(0, update_remaining_clicks_display)

# --- 監視スレッド関数 (2色対応版) ---
def monitor_task():
    global stop_event, click_count, click_limit, target_colors, target_color_tolerance, click_delay, consecutive_detections, detection_mode_var, color_set_status
    click_count = 0
    consecutive_detections = [0] * MAX_COLORS # 監視開始時にリセット

    # --- 設定値の取得と検証 ---
    mode = detection_mode_var.get() # 現在のモードを取得
    print(f"監視モード: {mode}")

    current_limit_str = ""
    if 'click_limit_entry' in globals() and click_limit_entry.winfo_exists():
        current_limit_str = click_limit_entry.get()
    if current_limit_str.isdigit() and int(current_limit_str) > 0:
        click_limit = int(current_limit_str)
        print(f"クリック上限設定: {click_limit} 回")
    else:
        click_limit = None
        print("クリック上限: 無制限")

    current_delay_str = ""
    if 'click_delay_entry' in globals() and click_delay_entry.winfo_exists():
        current_delay_str = click_delay_entry.get()
    try:
        delay_value = float(current_delay_str)
        if delay_value >= 0: click_delay = delay_value
        else: raise ValueError("Delay must be non-negative")
        print(f"判定ディレイ設定: {click_delay} 秒") # テキスト変更
    except ValueError:
        print("判定ディレイが無効な値です。デフォルト値(1.0秒)を使用します。") # テキスト変更
        click_delay = 1.0
        if root.winfo_exists():
            root.after(0, lambda: click_delay_entry.delete(0, tk.END))
            root.after(0, lambda: click_delay_entry.insert(0, "1.0"))

    if root.winfo_exists(): root.after(0, update_remaining_clicks_display)
    print("監視スレッド開始")
    # --- 監視ループ ---
    try:
        with mss.mss() as sct:
            # --- 監視開始前のチェック (start_monitoringで行うが念のため) ---
            if None in monitoring_rect.values() or None in click_point.values():
                print("エラー: 監視範囲またはクリック地点が未設定です。")
                if root.winfo_exists(): root.after(0, lambda: set_state("停止中"))
                return
            if mode == 'single' and not color_set_status[0]:
                print("エラー: 単色モードですが、色1が設定されていません。")
                if root.winfo_exists(): root.after(0, lambda: set_state("停止中"))
                return
            if mode == 'dual' and not (color_set_status[0] and color_set_status[1]):
                print("エラー: 2色モードですが、色が両方設定されていません。")
                if root.winfo_exists(): root.after(0, lambda: set_state("停止中"))
                return

            monitor = {"top": monitoring_rect['y1'], "left": monitoring_rect['x1'], "width": monitoring_rect['x2'] - monitoring_rect['x1'], "height": monitoring_rect['y2'] - monitoring_rect['y1']}
            if monitor["width"] <= 0 or monitor["height"] <= 0:
                print(f"エラー: 無効な監視範囲です {monitor}")
                if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("エラー", f"無効な監視範囲です: 幅={monitor['width']}, 高さ={monitor['height']}"))
                if root.winfo_exists(): root.after(0, lambda: set_state("停止中"))
                return

            # メインの監視ループ
            print("監視開始。")
            while not stop_event.is_set():
                try: # スクリーンショット取得とピクセル処理用
                    img_bytes = sct.grab(monitor)
                    img = Image.frombytes("RGB", (img_bytes.width, img_bytes.height), img_bytes.rgb)
                    step = 5 # ピクセルチェックの間隔

                    # ピクセルチェック
                    detected_color_index = -1 # 今回のループで検出された色のインデックス
                    for x in range(0, img.width, step):
                        for y in range(0, img.height, step):
                            try: # getpixel用
                                r, g, b = img.getpixel((x, y))
                                # --- 色判定ロジック (単色/2色対応) ---
                                for i in range(MAX_COLORS):
                                    # モードと設定状態に応じてチェック対象を決定
                                    if (mode == 'single' and i > 0) or not color_set_status[i]:
                                        continue
                                    tc = target_colors[i]
                                    if tc and \
                                       abs(r - tc['R']) <= target_color_tolerance and \
                                       abs(g - tc['G']) <= target_color_tolerance and \
                                       abs(b - tc['B']) <= target_color_tolerance:
                                        detected_color_index = i
                                        break # 最初に一致した色を採用
                                if detected_color_index != -1:
                                    break # ピクセルチェックの内側ループを抜ける
                            except IndexError:
                                continue # 範囲外ピクセルは無視
                        if detected_color_index != -1:
                            break # ピクセルチェックの外側ループも抜ける

                    # --- 判定ディレイとクリック実行ロジック (2色対応) ---
                    if detected_color_index != -1:
                        # 検出された色の連続カウントをインクリメント
                        consecutive_detections[detected_color_index] += 1
                        print(f"色{detected_color_index + 1} 検出 ({consecutive_detections[detected_color_index]}回目)。")

                        # 他の色の連続カウントはリセット
                        for i in range(MAX_COLORS):
                            if i != detected_color_index:
                                if consecutive_detections[i] > 0:
                                    print(f"色{i + 1} の連続検出が途切れました。")
                                consecutive_detections[i] = 0

                        # 連続検出回数が2回に達したかチェック
                        if consecutive_detections[detected_color_index] == 1:
                            # 1回目の検出 -> ディレイ開始
                            print(f"判定ディレイ ({click_delay}秒) 開始...")
                            delay_start_time = time.monotonic()
                            while time.monotonic() - delay_start_time < click_delay:
                                if stop_event.is_set():
                                    print("判定ディレイ中に停止信号を受信。")
                                    break
                                time.sleep(0.05) # CPU負荷軽減
                            if stop_event.is_set(): break # whileループを抜ける
                            # ディレイ後、次のループで2回目の判定を行う

                        elif consecutive_detections[detected_color_index] >= 2:
                            # 2回目(以上)の検出 -> クリック実行条件成立
                            print(f"色{detected_color_index + 1} 連続検出成功！")
                            if root.winfo_exists(): root.after(0, lambda: set_state("クリック実行"))
                            print("ステータス変更後、1秒待機してからクリックします...")
                            time.sleep(1.0) # クリック前の待機
                            if stop_event.is_set(): break

                            # クリック実行
                            send_click(click_point['x'], click_point['y'])
                            click_count += 1
                            if root.winfo_exists(): root.after(0, update_remaining_clicks_display)

                            # クリック後に1秒待機
                            print("クリック後、1秒待機します...")
                            time.sleep(1.0) # クリック後の待機
                            if stop_event.is_set(): break

                            # クリック上限チェック
                            if click_limit is not None and click_count >= click_limit:
                                print(f"クリック上限 ({click_limit}回) に達しました。監視を停止します。")
                                stop_event.set()
                                if root.winfo_exists():
                                    root.after(0, lambda: messagebox.showinfo("完了", f"指定回数 ({click_limit}回) のクリックが完了しました。"))
                                    root.after(100, lambda: winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC))
                                    root.after(200, lambda: set_state("停止中"))
                                break # whileループを抜ける

                            # 連続検出カウントをリセットし、状態を監視中に戻す
                            consecutive_detections = [0] * MAX_COLORS # 全てリセット
                            if not stop_event.is_set() and root.winfo_exists():
                                root.after(0, lambda: set_state("監視中"))

                    else:
                        # 色が検出されなかった場合、全ての連続検出カウントをリセット
                        if any(count > 0 for count in consecutive_detections):
                             print("ターゲット色が見つからず。連続検出をリセットします。")
                        consecutive_detections = [0] * MAX_COLORS

                    # --- 次の監視サイクルまでの待機 ---
                    # 連続検出1回目の後のディレイとは別に、監視ループ自体の間隔を設定
                    # ここでは1.5秒固定とする (必要なら調整)
                    if not stop_event.is_set():
                        time.sleep(1.5)

                except mss.ScreenShotError as ex: # スクリーンショット関連のエラー
                    print(f"スクリーンショット取得エラー: {ex}")
                    if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("エラー", f"スクリーンショット取得に失敗しました。\n{ex}"))
                    stop_event.set()
                    break # whileループを抜ける
                except Exception as e: # その他のループ内エラー
                    print(f"監視ループ中に予期せぬエラーが発生しました: {e}")
                    import traceback; traceback.print_exc()
                    if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("エラー", f"監視ループ中に予期せぬエラーが発生しました:\n{e}"))
                    stop_event.set()
                    break # whileループを抜ける

    except Exception as e: # スレッド初期化やmss関連のエラー
        print(f"監視スレッドの初期化中にエラー: {e}")
        import traceback; traceback.print_exc()
        if root.winfo_exists(): root.after(0, lambda: messagebox.showerror("エラー", f"監視スレッドの開始に失敗しました:\n{e}"))
    finally:
        # スレッド終了時の処理
        print("監視スレッド終了")
        # 状態が異常なままなら停止中に戻す
        if root.winfo_exists() and current_state not in ["停止中", "範囲設定中", "クリック設定中", "色設定中"]:
             root.after(0, lambda: set_state("停止中"))

# --- SendInputによるクリック関数 (変更なし) ---
def send_click(x, y):
    """指定座標にマウスカーソルを移動させてクリックイベントを送信する"""
    try:
        # SendInputで直接座標を指定してクリック (カーソル移動あり)
        # MOUSEEVENTF_ABSOLUTE を使う場合、座標を正規化する必要がある
        screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        nx = int(x * 65535 / screen_width)
        ny = int(y * 65535 / screen_height)

        # マウスダウンイベント (MOUSEEVENTF_MOVE を再度追加)
        mi_down = MouseInput(dx=nx, dy=ny, mouseData=0, dwFlags=win32con.MOUSEEVENTF_LEFTDOWN | win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None)
        inp_down = Input(type=win32con.INPUT_MOUSE, ii=Input_I(mi=mi_down))

        # マウスアップイベント (MOUSEEVENTF_MOVE を再度追加)
        mi_up = MouseInput(dx=nx, dy=ny, mouseData=0, dwFlags=win32con.MOUSEEVENTF_LEFTUP | win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None)
        inp_up = Input(type=win32con.INPUT_MOUSE, ii=Input_I(mi=mi_up))

        # イベント送信
        inputs = (Input * 2)(inp_down, inp_up)
        ctypes.windll.user32.SendInput(2, ctypes.pointer(inputs), ctypes.sizeof(Input))
        print(f"SendInput (Move): クリックイベント送信 ({x}, {y})") # ログメッセージ変更

    except Exception as e:
        print(f"send_clickエラー: {e}")
        import traceback; traceback.print_exc()
        # エラー発生時は pyautogui にフォールバックする (オプション)
        # try:
        #     print("SendInputエラーのためpyautoguiでクリックします。")
        #     pyautogui.click(x, y)
        # except Exception as pe:
        #     print(f"pyautoguiフォールバックも失敗: {pe}")

# --- キーボードリスナー ---
def on_press_key(key):
    global HOTKEY
    if key == HOTKEY:
        print(f"ホットキー ({HOTKEY}) 検出！")
        if root.winfo_exists(): root.after(0, on_toggle_button_click)

def start_keyboard_listener():
    global keyboard_listener
    if keyboard_listener is None or not keyboard_listener.is_alive():
        print("キーボードリスナーを開始します。")
        keyboard_listener = keyboard.Listener(on_press=on_press_key)
        keyboard_listener.start()
    else: print("キーボードリスナーは既に実行中です。")

def stop_keyboard_listener():
    global keyboard_listener
    if keyboard_listener is not None and keyboard_listener.is_alive():
        print("キーボードリスナーを停止します。")
        keyboard_listener.stop()
        keyboard_listener = None

# --- 監視制御関数 ---
def start_monitoring():
    global monitoring_thread, stop_event, detection_mode_var, color_set_status
    # --- 開始前チェックを強化 ---
    if monitoring_rect['x1'] is None:
        messagebox.showerror("エラー", "監視範囲が設定されていません。")
        set_state("停止中"); return
    if click_point['x'] is None:
        messagebox.showerror("エラー", "クリック地点が設定されていません。")
        set_state("停止中"); return

    mode = detection_mode_var.get()
    if mode == 'single' and not color_set_status[0]:
        messagebox.showerror("エラー", "単色モードですが、色1が設定されていません。")
        set_state("停止中"); return
    if mode == 'dual' and not (color_set_status[0] and color_set_status[1]):
        messagebox.showerror("エラー", "2色モードですが、色が両方設定されていません。")
        set_state("停止中"); return

    if monitoring_thread is None or not monitoring_thread.is_alive():
        print("監視スレッドの開始準備")
        stop_event.clear()
        monitoring_thread = threading.Thread(target=monitor_task, daemon=True)
        monitoring_thread.start()
        set_state("監視中")
    else: print("監視スレッドは既に実行中です。")

def stop_monitoring():
    global monitoring_thread, stop_event
    if monitoring_thread is not None and monitoring_thread.is_alive():
        print("監視スレッドに停止信号を送信します。")
        stop_event.set()
        monitoring_thread.join(timeout=0.5)
        if monitoring_thread.is_alive(): print("警告: 監視スレッドが時間内に終了しませんでした。")
        monitoring_thread = None
    if current_state not in ["停止中", "範囲設定中", "クリック設定中"]: # アイドル -> 停止中
        set_state("停止中") # アイドル -> 停止中

# --- GUIイベントハンドラ ---
def on_range_button_click():
    global overlay_window
    if current_state == "停止中": # アイドル -> 停止中
        set_state("範囲設定中")
        if overlay_window is None: overlay_window = OverlayWindow(root)
        overlay_window.activate('range')
    elif current_state == "範囲設定中":
         if overlay_window: overlay_window.close_overlay()
         set_state("停止中") # アイドル -> 停止中

def on_click_button_click():
    global overlay_window
    if current_state == "停止中": # アイドル -> 停止中
        set_state("クリック設定中")
        if overlay_window is None: overlay_window = OverlayWindow(root)
        overlay_window.activate('click')
    elif current_state == "クリック設定中":
         if overlay_window: overlay_window.close_overlay()
         set_state("停止中")

# --- 色設定関連のイベントハンドラ (2色対応) ---
def on_color_swatch_click(event=None, color_index=0):
    """色見本クリックでカラーピッカーを開く (インデックス指定)"""
    global target_colors, color_set_status
    if current_state == "停止中":
        # デュアルモードでない場合、色2の変更は不可
        if detection_mode_var.get() == 'single' and color_index == 1:
             messagebox.showwarning("注意", "単色モードでは色2は使用できません。", parent=root)
             return

        current_color = target_colors[color_index]
        initial_color_hex = "white" # デフォルト
        if current_color:
            try: initial_color_hex = f"#{current_color['R']:02x}{current_color['G']:02x}{current_color['B']:02x}"
            except KeyError: pass # 不完全な辞書の場合

        color_code = colorchooser.askcolor(title=f"検出する色{color_index + 1}を選択", initialcolor=initial_color_hex, parent=root)
        if color_code and color_code[0]:
            rgb = color_code[0]
            if target_colors[color_index] is None: target_colors[color_index] = {}
            target_colors[color_index]['R'], target_colors[color_index]['G'], target_colors[color_index]['B'] = int(rgb[0]), int(rgb[1]), int(rgb[2])
            color_set_status[color_index] = True
            print(f"カラーピッカーで色{color_index + 1}設定完了: RGB({rgb[0]}, {rgb[1]}, {rgb[2]})")
            update_color_display()
            set_state("停止中") # 状態更新（ボタン有効/無効のため）
    else:
        messagebox.showwarning("注意", "色の変更は停止中に行ってください。", parent=root)

def on_color_button_click(color_index=0): # 色の抽出ボタン (インデックス指定)
    """指定されたインデックスの色を抽出する"""
    global overlay_window
    if current_state == "停止中":
        # デュアルモードでない場合、色2の抽出は不可
        if detection_mode_var.get() == 'single' and color_index == 1:
             messagebox.showwarning("注意", "単色モードでは色2は使用できません。", parent=root)
             return
        set_state("色設定中")
        if overlay_window is None: overlay_window = OverlayWindow(root)
        overlay_window.activate('color', color_index=color_index) # インデックスを渡す
    elif current_state == "色設定中":
         if overlay_window: overlay_window.close_overlay()
         set_state("停止中")

# --- 判定モード変更コールバック ---
def on_detection_mode_change():
    global detection_mode_var
    mode = detection_mode_var.get()
    print(f"判定モード変更: {mode}")
    # 状態を更新してUI（特に色2関連）の表示/非表示と有効/無効を切り替える
    set_state(current_state) # 現在の状態を再適用してUIを更新
    update_settings_indicator() # 色設定インジケータも更新

def on_toggle_button_click():
    if current_state == "監視中": stop_monitoring()
    elif current_state == "停止中":
        start_monitoring() # 開始前チェックは start_monitoring 内で行う

def check_thread_and_destroy():
    """監視スレッドが停止しているか確認し、停止していればウィンドウを破棄する"""
    global monitoring_thread
    if monitoring_thread is not None and monitoring_thread.is_alive():
        print("監視スレッドの停止を待機中...")
        root.after(100, check_thread_and_destroy) # 100ms後にもう一度確認
    else:
        print("監視スレッド停止を確認。ウィンドウを破棄します。")
        if root.winfo_exists():
            root.destroy()

def on_closing():
    """ウィンドウクローズ時の処理"""
    print("ウィンドウが閉じられようとしています。")
    print("設定を保存しています...")
    save_settings() # 設定を保存
    print("監視スレッドとリスナーを停止しています...")
    stop_monitoring() # スレッドに停止信号を送る (joinはここでは待たない)
    stop_keyboard_listener()
    print("スレッド停止待機＆ウィンドウ破棄処理を開始します。")
    # スレッドが停止するのを待ってからウィンドウを破棄する
    check_thread_and_destroy()

# --- GUI更新関数 ---
def update_settings_indicator():
    global range_indicator_label, click_indicator_label, color_indicator_label_1, color_indicator_label_2, color_set_status, detection_mode_var
    range_set = monitoring_rect['x1'] is not None
    click_set = click_point['x'] is not None
    mode = detection_mode_var.get() if detection_mode_var else 'single'

    # 範囲とクリック
    if 'range_indicator_label' in globals() and range_indicator_label.winfo_exists():
        range_indicator_label.config(text="範囲: OK" if range_set else "範囲: 未設定", fg="green" if range_set else "red")
    if 'click_indicator_label' in globals() and click_indicator_label.winfo_exists():
        click_indicator_label.config(text="ｸﾘｯｸ: OK" if click_set else "ｸﾘｯｸ: 未設定", fg="green" if click_set else "red")

    # 色1
    color1_set = color_set_status[0]
    if 'color_indicator_label_1' in globals() and color_indicator_label_1.winfo_exists():
        color_indicator_label_1.config(text="色1: OK" if color1_set else "色1: 未設定", fg="green" if color1_set else "red")

    # 色2 (デュアルモード時のみ表示・更新)
    if 'color_indicator_label_2' in globals() and color_indicator_label_2.winfo_exists():
        if mode == 'dual':
            color2_set = color_set_status[1]
            color_indicator_label_2.config(text="色2: OK" if color2_set else "色2: 未設定", fg="green" if color2_set else "red")
            # ラベルが表示されていなければ表示する
            if not color_indicator_label_2.winfo_ismapped():
                 color_indicator_label_2.pack(side=tk.LEFT, padx=(10, 0)) # indicator_frame 内の右側に表示
        else:
            # 単色モードなら非表示
            color_indicator_label_2.pack_forget()


def update_color_display():
    global target_colors, target_color_label_1, target_color_swatch_1, target_color_label_2, target_color_swatch_2
    # 色1の表示更新
    if 'target_color_label_1' in globals() and target_color_label_1.winfo_exists():
        color1 = target_colors[0]
        if color1 and color_set_status[0]:
            rgb_str = f"RGB({color1.get('R', '?')}, {color1.get('G', '?')}, {color1.get('B', '?')})"
            target_color_label_1.config(text=f"検出色1: {rgb_str}")
            try:
                hex_color = f"#{color1['R']:02x}{color1['G']:02x}{color1['B']:02x}"
                target_color_swatch_1.config(bg=hex_color)
            except (KeyError, TypeError, ValueError) as e:
                print(f"色1表示の更新中にエラー: {e}")
                target_color_swatch_1.config(bg="white")
        else:
            target_color_label_1.config(text="検出色1: 未設定")
            target_color_swatch_1.config(bg="white")

    # 色2の表示更新
    if 'target_color_label_2' in globals() and target_color_label_2.winfo_exists():
        color2 = target_colors[1]
        if color2 and color_set_status[1]:
            rgb_str = f"RGB({color2.get('R', '?')}, {color2.get('G', '?')}, {color2.get('B', '?')})"
            target_color_label_2.config(text=f"検出色2: {rgb_str}")
            try:
                hex_color = f"#{color2['R']:02x}{color2['G']:02x}{color2['B']:02x}"
                target_color_swatch_2.config(bg=hex_color)
            except (KeyError, TypeError, ValueError) as e:
                print(f"色2表示の更新中にエラー: {e}")
                target_color_swatch_2.config(bg="white")
        else:
            target_color_label_2.config(text="検出色2: 未設定")
            target_color_swatch_2.config(bg="white")

def update_remaining_clicks_display():
    global remaining_clicks_label, click_limit, click_count
    if 'remaining_clicks_label' in globals() and remaining_clicks_label.winfo_exists():
        if current_state == "監視中" and click_limit is not None:
            remaining = click_limit - click_count
            remaining_clicks_label.config(text=f"残り: {remaining}")
        else:
            remaining_clicks_label.config(text="残り: ---")

# --- 入力検証関数 ---
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

# --- 感度変更コールバック ---
def on_sensitivity_change(event=None):
    global target_color_tolerance, sensitivity_var
    selected_text = sensitivity_var.get()
    if selected_text in SENSITIVITY_MAP:
        target_color_tolerance = SENSITIVITY_MAP[selected_text]
        print(f"識別感度変更: {selected_text} (許容誤差 = {target_color_tolerance})")
    else:
        print(f"エラー: 不明な感度テキスト '{selected_text}'")
        # 予期しない値の場合はデフォルトに戻す
        sensitivity_var.set(DEFAULT_SENSITIVITY_TEXT)
        target_color_tolerance = SENSITIVITY_MAP[DEFAULT_SENSITIVITY_TEXT]

# --- GUIセットアップ ---
from tkinter import ttk
# import functools # 上部に移動済み

root = tk.Tk()
root.title("Cline Retry Auto Clicker") # タイトル変更
root.attributes("-topmost", True)
root.resizable(False, False)
try:
    # ウィンドウアイコンの設定 (aikon.icoが存在する場合)
    root.iconbitmap('aikon.ico')
except tk.TclError:
    print("警告: aikon.icoが見つからないか、無効なアイコンファイルです。デフォルトアイコンを使用します。")

# --- スタイル設定 ---
default_font = tkFont.nametofont("TkDefaultFont")
default_font.configure(size=9)
root.option_add("*Font", default_font)

# --- ウィジェット配置 ---
main_frame = tk.Frame(root, padx=10, pady=10)
main_frame.pack(fill=tk.BOTH, expand=True)

# ステータス
status_label = tk.Label(main_frame, text=f"ステータス: {current_state}", font=("Arial", 11, "bold"), wraplength=380)
status_label.pack(pady=(0, 10), fill=tk.X)

# --- 判定モード選択 ---
mode_frame = tk.Frame(main_frame)
mode_frame.pack(pady=2, fill=tk.X)
detection_mode_var = tk.StringVar(root, value='single') # デフォルトは単色モード
single_mode_radio = tk.Radiobutton(mode_frame, text="単色判定", variable=detection_mode_var, value='single', command=on_detection_mode_change)
single_mode_radio.pack(side=tk.LEFT, padx=(0, 10))
dual_mode_radio = tk.Radiobutton(mode_frame, text="2色判定", variable=detection_mode_var, value='dual', command=on_detection_mode_change)
dual_mode_radio.pack(side=tk.LEFT)

# --- 設定状態インジケータ ---
indicator_frame = tk.Frame(main_frame)
indicator_frame.pack(pady=2, fill=tk.X)
range_indicator_label = tk.Label(indicator_frame, text="範囲: 未設定", fg="red")
range_indicator_label.pack(side=tk.LEFT, padx=(0, 10))
click_indicator_label = tk.Label(indicator_frame, text="ｸﾘｯｸ: 未設定", fg="red")
click_indicator_label.pack(side=tk.LEFT, padx=(0, 10))
color_indicator_label_1 = tk.Label(indicator_frame, text="色1: 未設定", fg="red")
color_indicator_label_1.pack(side=tk.LEFT)
color_indicator_label_2 = tk.Label(indicator_frame, text="色2: 未設定", fg="red")
# 色2インジケータは set_state で表示/非表示を制御するため、ここでは pack しない

# --- 設定ボタン ---
settings_frame = tk.Frame(main_frame)
settings_frame.pack(pady=5, fill=tk.X)
range_button = tk.Button(settings_frame, text="範囲設定", command=on_range_button_click, width=9) # 幅調整
range_button.pack(side=tk.LEFT, padx=(0, 5))
click_button = tk.Button(settings_frame, text="クリック設定", command=on_click_button_click, width=9) # 幅調整
click_button.pack(side=tk.LEFT, padx=5)
# 色抽出ボタン (色1用) - functools.partial を使用してインデックスを渡す
color_button_1 = tk.Button(settings_frame, text="色1 抽出", command=functools.partial(on_color_button_click, color_index=0), width=9) # 幅調整
color_button_1.pack(side=tk.LEFT, padx=5)
# 色抽出ボタン (色2用) - 初期状態では非表示。set_stateで表示制御
color_button_2 = tk.Button(settings_frame, text="色2 抽出", command=functools.partial(on_color_button_click, color_index=1), width=9) # 幅調整
# color_button_2.pack(side=tk.LEFT, padx=(5, 0)) # 初期は非表示

# --- 色表示 (色1) ---
color_frame_1 = tk.Frame(main_frame)
color_frame_1.pack(pady=5, fill=tk.X)
target_color_label_1 = tk.Label(color_frame_1, text="検出色1: 未設定")
target_color_label_1.pack(side=tk.LEFT)
target_color_swatch_1 = tk.Canvas(color_frame_1, width=18, height=18, bg="white", relief="sunken", borderwidth=1)
target_color_swatch_1.pack(side=tk.LEFT, padx=5)
# functools.partial を使用してクリック時のインデックスを渡す
target_color_swatch_1.bind("<Button-1>", functools.partial(on_color_swatch_click, color_index=0))

# --- 色表示 (色2) ---
# 初期状態では非表示。set_stateで表示制御
color_frame_2 = tk.Frame(main_frame)
# color_frame_2.pack(pady=5, fill=tk.X) # 初期は非表示
target_color_label_2 = tk.Label(color_frame_2, text="検出色2: 未設定")
target_color_label_2.pack(side=tk.LEFT)
target_color_swatch_2 = tk.Canvas(color_frame_2, width=18, height=18, bg="white", relief="sunken", borderwidth=1)
target_color_swatch_2.pack(side=tk.LEFT, padx=5)
target_color_swatch_2.bind("<Button-1>", functools.partial(on_color_swatch_click, color_index=1))


# --- クリック設定 (Gridで配置調整) ---
click_settings_frame = tk.Frame(main_frame)
click_settings_frame.pack(pady=5, fill=tk.X)
click_settings_frame.columnconfigure(1, weight=0) # Entry/Combobox列
click_settings_frame.columnconfigure(2, weight=1) # 残り回数表示列 (右寄せ用)

# 上限回数 (row=0)
limit_label = tk.Label(click_settings_frame, text="上限回数 (0/空=無制限):")
limit_label.grid(row=0, column=0, sticky='w', padx=(0, 5)) # padx調整
vcmd_limit = (root.register(validate_click_limit), '%P')
click_limit_entry = tk.Entry(click_settings_frame, width=7, validate='key', validatecommand=vcmd_limit)
click_limit_entry.grid(row=0, column=1, sticky='w')
remaining_clicks_label = tk.Label(click_settings_frame, text="残り: ---")
remaining_clicks_label.grid(row=0, column=2, sticky='e', padx=(10, 0)) # 右寄せ

# ディレイ (判定間隔) (row=1)
delay_label = tk.Label(click_settings_frame, text="判定間隔 (秒):") # ラベルテキスト変更
delay_label.grid(row=1, column=0, sticky='w', padx=(0, 5), pady=(5,0)) # padx調整
vcmd_delay = (root.register(validate_click_delay), '%P')
click_delay_entry = tk.Entry(click_settings_frame, width=7, validate='key', validatecommand=vcmd_delay)
click_delay_entry.insert(0, str(click_delay))
click_delay_entry.grid(row=1, column=1, sticky='w', pady=(5,0))

# 識別感度 (判定範囲) (row=2)
sensitivity_label = tk.Label(click_settings_frame, text="判定範囲:") # ラベルテキスト変更
sensitivity_label.grid(row=2, column=0, sticky='w', padx=(0, 5), pady=(5,0)) # padx調整
sensitivity_var = tk.StringVar(root) # rootをmasterに指定
sensitivity_var.set(DEFAULT_SENSITIVITY_TEXT) # デフォルトのテキスト表示を設定
sensitivity_combobox = ttk.Combobox(click_settings_frame, textvariable=sensitivity_var, values=list(SENSITIVITY_MAP.keys()), width=10, state="readonly") # width調整, valuesに新しいテキストキーを設定
sensitivity_combobox.grid(row=2, column=1, sticky='w', pady=(5,0))
sensitivity_combobox.bind("<<ComboboxSelected>>", on_sensitivity_change) # イベントバインド

# 制御ボタン
control_frame = tk.Frame(main_frame)
control_frame.pack(pady=10)
toggle_button = tk.Button(control_frame, text="監視 開始", command=on_toggle_button_click, width=15, state=tk.DISABLED)
toggle_button.pack()
hotkey_label = tk.Label(control_frame, text=f"ホットキー: {HOTKEY.name.upper()} (開始/停止)", fg="gray50")
hotkey_label.pack(pady=(5, 0))

root.protocol("WM_DELETE_WINDOW", on_closing)

# --- メインループ ---
if __name__ == "__main__":
    overlay_window = OverlayWindow(root)
    # ★★★ 設定読み込み処理を追加 ★★★
    load_settings() # GUI要素が作成された後に設定を読み込む

    # detection_mode_var の初期化は Radiobutton 作成時に移動
    # sensitivity_var の初期化は Combobox 作成時に移動

    # ★★★ load_settings後にUI状態を更新 ★★★
    set_state("停止中") # 初期状態設定 (UI要素の初期状態もここで決まる)
    update_color_display() # 読み込んだ設定に基づいて色表示を更新
    update_settings_indicator() # 読み込んだ設定に基づいてインジケータ表示を更新
    on_detection_mode_change() # 読み込んだモードに基づいてUIを再構成

    start_keyboard_listener()
    root.mainloop()
