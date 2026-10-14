# -*- coding: utf-8 -*-
"""
模块名称: 3.新电阻阻值校准 - 显示
版本号: V26.10.13
"""
__version__ = "V26.10.13"

import serial
import serial.tools.list_ports
import struct
import time
import numpy as np
import csv
import os
import re
import cv2
import pytesseract
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import simpledialog

# --- Tesseract 路径配置 ---
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# --- 硬件与串口配置 ---
DEFAULT_PORT = "COM5"
DEFAULT_BAUD = 2000000
TAIL = b'\x00\x00\x80\x7F'


def get_available_ports():
    """获取系统当前所有可用串口及设备描述"""
    port_list = []
    try:
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = f" ({p.description})" if p.description else ""
            port_list.append(f"{p.device}{desc}")
    except Exception:
        pass
    if not port_list:
        port_list = ["无可用串口 (请检查连接)"]
    return port_list



def parse_input(s):
    s = s.upper().strip()
    try:
        if s.endswith('KR'): return float(s[:-2]) * 1000, "RES"
        if s.endswith('MR'): return float(s[:-2]) * 1000000, "RES"
        if s.endswith('R'):  return float(s[:-1]), "RES"
        if s.endswith('UA'): return float(s[:-2]) / 1e6, "CUR"
        if s.endswith('MA'): return float(s[:-2]) / 1e3, "CUR"
        if s.endswith('A'):  return float(s[:-1]), "CUR"
        return float(s), "CUR"
    except: return None, None


def deskew_image(img, angle_deg):
    if angle_deg == 0:
        return img
    h, w = img.shape[:2]
    tan_angle = np.tan(np.radians(angle_deg))
    M = np.float32([[1, tan_angle, -tan_angle * h / 2],
                    [0,  1,          0]])
    deskewed = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, 
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(200, 200, 200))
    return deskewed


try:
    import msvcrt
    def flush_input_buffer():
        while msvcrt.kbhit():
            msvcrt.getch()
except ImportError:
    def flush_input_buffer():
        pass


def get_available_cameras():
    camera_list = []
    try:
        from pygrabber.dshow_graph import FilterGraph
        graph = FilterGraph()
        devices = graph.get_input_devices()
        for i, name in enumerate(devices):
            camera_list.append(f"{i}: {name}")
    except ImportError:
        for i in range(10):  
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                camera_list.append(f"{i}: 摄像头 {i}")
                cap.release()
    if not camera_list:
        camera_list = ["0: 默认摄像头 0"]
    return camera_list


def parse_cal_points(text):
    """
    正则解析 C 语言结构体数组中的 {电压, 偏置}
    """
    pattern = r"\{\s*(\d+)\s*,\s*(-?\d+)\s*\}"
    matches = re.findall(pattern, text)
    points = []
    for v, o in matches:
        points.append((int(v), int(o)))
    points.sort(key=lambda x: x[0])
    return points


def interpolate_offset(target_v_mv, table):
    """
    多段线性插值计算
    """
    if not table:
        return 0
    if target_v_mv <= table[0][0]:
        return table[0][1]
    if target_v_mv >= table[-1][0]:
        return table[-1][1]
        
    for i in range(len(table) - 1):
        x0, y0 = table[i]
        x1, y1 = table[i+1]
        if x0 <= target_v_mv <= x1:
            return int(round(y0 + (target_v_mv - x0) * (y1 - y0) / (x1 - x0)))
    return table[0][1]


def distance_point_to_line(point, start, end):
    x, y = point
    x1, y1 = start
    x2, y2 = end
    if x1 == x2 and y1 == y2:
        return np.sqrt((x - x1)**2 + (y - y1)**2)
    a = y2 - y1
    b = -(x2 - x1)
    c = x2 * y1 - y2 * x1
    return abs(a * x + b * y + c) / np.sqrt(a**2 + b**2)


def rdp_simplify(points, epsilon):
    if epsilon < 0 or len(points) < 3:
        return points
        
    dmax = 0
    index = 0
    end = len(points) - 1
    for i in range(1, end):
        d = distance_point_to_line(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d
            
    if dmax > epsilon:
        results1 = rdp_simplify(points[:index+1], epsilon)
        results2 = rdp_simplify(points[index:], epsilon)
        return results1[:-1] + results2
    else:
        return [points[0], points[end]]


class CameraConfigGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("校准配置与数码管相机设置")
        self.root.geometry("520x430") 
        self.root.resizable(False, False)
        
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(1000, lambda: self.root.attributes("-topmost", False))
        
        self.selected_port = DEFAULT_PORT
        self.selected_baud = DEFAULT_BAUD
        self.use_ocr = False
        self.selected_camera_idx = 0
        self.selected_rotation = 0  
        self.selected_deskew = 12  
        self.roi = None
        self.is_confirmed = False

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 0. 串口选择
        ttk.Label(main_frame, text="分析仪串口:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=4)
        port_frame = ttk.Frame(main_frame)
        port_frame.grid(row=0, column=1, sticky=tk.EW, pady=4)
        
        self.port_list = get_available_ports()
        self.port_combo = ttk.Combobox(port_frame, values=self.port_list, width=28)
        self.port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        else:
            self.port_combo.set(DEFAULT_PORT)
            
        self.btn_refresh = ttk.Button(port_frame, text="刷新", width=5, command=self.refresh_ports)
        self.btn_refresh.pack(side=tk.RIGHT, padx=(5, 0))

        # 1. 波特率
        ttk.Label(main_frame, text="串口波特率:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=4)
        self.baud_combo = ttk.Combobox(main_frame, values=["2000000", "1000000", "921600", "460800", "115200"], width=35)
        self.baud_combo.set(str(DEFAULT_BAUD))
        self.baud_combo.grid(row=1, column=1, sticky=tk.W, pady=4)

        # 2. 摄像头选择
        ttk.Label(main_frame, text="选择摄像头:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=4)
        cameras = get_available_cameras()
        self.camera_combo = ttk.Combobox(main_frame, values=cameras, width=35, state="readonly")
        if cameras:
            self.camera_combo.current(0)
        self.camera_combo.grid(row=2, column=1, sticky=tk.W, pady=4)

        # 3. 画面旋转角度
        ttk.Label(main_frame, text="画面旋转角度:", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=4)
        self.rotation_combo = ttk.Combobox(main_frame, values=["0°", "90° 顺时针", "180°", "270° 顺时针"], width=20, state="readonly")
        self.rotation_combo.current(0)
        self.rotation_combo.grid(row=3, column=1, sticky=tk.W, pady=4)

        # 4. 数码管倾斜校正
        ttk.Label(main_frame, text="数码管倾斜校正:", font=("Arial", 10)).grid(row=4, column=0, sticky=tk.W, pady=4)
        self.deskew_combo = ttk.Combobox(main_frame, values=["0° (垂直屏)", "5°", "10°", "12° (推荐)", "15°", "-5°", "-10°"], width=20, state="readonly")
        self.deskew_combo.current(3) 
        self.deskew_combo.grid(row=4, column=1, sticky=tk.W, pady=4)

        ttk.Separator(main_frame, orient='horizontal').grid(row=5, column=0, columnspan=2, sticky='ew', pady=8)

        self.btn_preview = ttk.Button(main_frame, text="打开预览 并 框选数码管屏幕", command=self.preview_and_crop)
        self.btn_preview.grid(row=6, column=0, columnspan=2, sticky='ew', pady=4)

        self.btn_confirm = ttk.Button(main_frame, text="确认配置并开始校准 (带 OCR 自动识别)", command=self.confirm_settings)
        self.btn_confirm.grid(row=7, column=0, columnspan=2, sticky='ew', pady=4)

        self.btn_no_ocr = ttk.Button(main_frame, text="不启动 OCR (手动输入实际电流模式)", command=self.confirm_no_ocr)
        self.btn_no_ocr.grid(row=8, column=0, columnspan=2, sticky='ew', pady=4)

    def refresh_ports(self):
        self.port_list = get_available_ports()
        self.port_combo['values'] = self.port_list
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        messagebox.showinfo("刷新成功", f"扫描到 {len(self.port_list)} 个串口设备！")

    def validate_and_test_serial(self):
        raw_port = self.port_combo.get().strip()
        if not raw_port or "无可用串口" in raw_port:
            messagebox.showerror("串口错误", "请先选择或输入有效的串口号（例如 COM3, COM16）！")
            return None, None
            
        match = re.search(r"(COM\d+)", raw_port, re.IGNORECASE)
        port = match.group(1).upper() if match else raw_port.split(":")[0].strip()
        
        raw_baud = self.baud_combo.get().strip()
        try:
            baud = int(raw_baud)
        except ValueError:
            baud = DEFAULT_BAUD
            
        # 预测试串口连通性，防止打不开时程序崩溃退出
        try:
            test_ser = serial.Serial(port, baud, timeout=0.5)
            test_ser.close()
        except Exception as e:
            messagebox.showerror(
                "串口连接失败",
                f"无法打开串口 {port}：\n{e}\n\n"
                f"排查建议：\n"
                f"1. 确认该串口未被上位机或其他软件占用\n"
                f"2. 确认分析仪 USB 线已插紧并被系统识别\n"
                f"3. 点击【刷新】重新获取最新端口列表"
            )
            return None, None
            
        return port, baud

    def get_rotation_flag(self):
        idx = self.rotation_combo.current()
        if idx == 0: return None
        elif idx == 1: return cv2.ROTATE_90_CLOCKWISE
        elif idx == 2: return cv2.ROTATE_180
        elif idx == 3: return cv2.ROTATE_90_COUNTERCLOCKWISE
        return None

    def get_deskew_angle(self):
        txt = self.deskew_combo.get()
        match = re.search(r"[-+]?\d+", txt)
        return int(match.group()) if match else 0

    def preview_and_crop(self):
        selected_text = self.camera_combo.get()
        camera_idx = int(selected_text.split(":")[0])
        
        cap = cv2.VideoCapture(camera_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            messagebox.showerror("错误", f"无法打开摄像头 {selected_text}。")
            return

        rotation_flag = self.get_rotation_flag()
        messagebox.showinfo("预览提示", "1. 请确认数字在预览中是否被“完全拉直”。\n2. 确认无误后，按【ENTER】开始框选。")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if rotation_flag is not None:
                frame = cv2.rotate(frame, rotation_flag)
                
            angle = self.get_deskew_angle()
            frame = deskew_image(frame, angle)
                
            cv2.putText(frame, f"Preview - Deskew: {angle} deg (Enter to Crop)", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.imshow("Preview", frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == 13 or key == 32:  
                break
        
        cv2.destroyWindow("Preview")

        ret, frame = cap.read()
        if ret:
            if rotation_flag is not None:
                frame = cv2.rotate(frame, rotation_flag)
            angle = self.get_deskew_angle()
            frame = deskew_image(frame, angle)
            
            roi = cv2.selectROI("Drag mouse to select ROI, then press Enter", frame, False, True)
            cv2.destroyWindow("Drag mouse to select ROI, then press Enter")
            
            if roi[2] > 0 and roi[3] > 0:
                self.roi = roi
                self.selected_camera_idx = camera_idx
                self.selected_rotation = rotation_flag
                self.selected_deskew = angle
                messagebox.showinfo("成功", f"区域框选成功！\n大小: {roi[2]}x{roi[3]}")
            else:
                self.roi = None
        cap.release()

    def confirm_settings(self):
        port, baud = self.validate_and_test_serial()
        if not port:
            return
        self.selected_port = port
        self.selected_baud = baud
        
        selected_text = self.camera_combo.get()
        self.selected_camera_idx = int(selected_text.split(":")[0])
        self.selected_rotation = self.get_rotation_flag()
        self.selected_deskew = self.get_deskew_angle()
        self.use_ocr = True
        self.is_confirmed = True
        self.root.destroy()

    def confirm_no_ocr(self):
        port, baud = self.validate_and_test_serial()
        if not port:
            return
        self.selected_port = port
        self.selected_baud = baud
        self.use_ocr = False
        self.is_confirmed = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return (
            self.is_confirmed,
            self.use_ocr,
            self.selected_port,
            self.selected_baud,
            self.selected_camera_idx,
            self.selected_rotation,
            self.selected_deskew,
            self.roi
        )


class OCRConfirmationDialog:
    def __init__(self, parent, detected_val_str, default_unit="mA"):
        self.top = tk.Toplevel(parent)
        self.top.title("数码管读数确认")
        self.top.geometry("380x180")
        self.top.resizable(False, False)
        self.top.grab_set()  
        
        self.result_val = None  
        self.result_str_label = ""
        
        raw_text = detected_val_str.strip()
        if raw_text.startswith('.'):
            raw_text = '0' + raw_text
            
        ttk.Label(self.top, text=f"OCR 识别到数字: {raw_text}", font=("Arial", 11, "bold"), foreground="blue").pack(pady=8)
        
        entry_frame = ttk.Frame(self.top)
        entry_frame.pack(pady=2)
        ttk.Label(entry_frame, text="数值微调: ").pack(side=tk.LEFT)
        self.entry = ttk.Entry(entry_frame, font=("Arial", 11), width=15, justify="center")
        self.entry.insert(0, raw_text)
        self.entry.pack(side=tk.LEFT)
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)  
        
        self.unit_var = tk.StringVar(value=default_unit)
        
        r_frame = ttk.LabelFrame(self.top, text=" 选择实际单位 ")
        r_frame.pack(pady=8, fill=tk.X, padx=20)
        
        ttk.Radiobutton(r_frame, text="A (安培)", variable=self.unit_var, value="A").pack(side=tk.LEFT, expand=True)
        ttk.Radiobutton(r_frame, text="mA (毫安)", variable=self.unit_var, value="mA").pack(side=tk.LEFT, expand=True)
        ttk.Radiobutton(r_frame, text="uA (微安)", variable=self.unit_var, value="uA").pack(side=tk.LEFT, expand=True)

        self.entry.bind("<Return>", lambda event: self.on_confirm())
        
        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="确认 (Enter)", command=self.on_confirm, width=12).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="放弃此点", command=self.on_cancel, width=12).pack(side=tk.LEFT, padx=10)
        
        self.top.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.keep_opencv_alive()

    def keep_opencv_alive(self):
        if self.top.winfo_exists():
            cv2.waitKey(1)  
            self.top.after(50, self.keep_opencv_alive)  

    def on_confirm(self):
        raw_val_str = self.entry.get().strip()
        try:
            val = float(raw_val_str)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字！")
            return
            
        unit = self.unit_var.get()
        if unit == "A":
            self.result_val = val
        elif unit == "mA":
            self.result_val = val / 1e3
        elif unit == "uA":
            self.result_val = val / 1e6
            
        self.result_str_label = f"{raw_val_str}{unit}"
        self.top.destroy()

    def on_cancel(self):
        self.result_val = None
        self.top.destroy()


class LiveSensorMonitorGUI:
    """
    【新增】：终端模式下的 INA226 实时传感器数据监视悬浮窗 (0.1s 刷新)
    """
    def __init__(self, parent, calibrator):
        self.top = tk.Toplevel(parent)
        self.top.title("INA226 传感器实时监控 (0.1s 刷新)")
        self.top.geometry("480x200")
        self.top.resizable(False, False)
        self.top.attributes("-topmost", True)  # 置顶显示，方便边看终端边调电源
        
        self.calibrator = calibrator
        
        frame = ttk.LabelFrame(self.top, text=" INA226 实时传感器状态 ", padding="12")
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 1. 换算电压与电压 Raw
        ttk.Label(frame, text="换算电压:").grid(row=0, column=0, sticky=tk.E, pady=4, padx=5)
        self.lbl_v_val = ttk.Label(frame, text="0.000 V (0 mV)", font=("Consolas", 10, "bold"), foreground="#2B6CB0")
        self.lbl_v_val.grid(row=0, column=1, sticky=tk.W, padx=(0, 15), pady=4)

        ttk.Label(frame, text="电压 Raw 值:").grid(row=0, column=2, sticky=tk.E, pady=4, padx=5)
        self.lbl_v_raw = ttk.Label(frame, text="0.0", font=("Consolas", 10, "bold"), foreground="#2B6CB0")
        self.lbl_v_raw.grid(row=0, column=3, sticky=tk.W, pady=4)
        
        # 2. 电流 Raw 与 16bit 量程占比
        ttk.Label(frame, text="电流 Raw 值:").grid(row=1, column=0, sticky=tk.E, pady=4, padx=5)
        self.lbl_s_raw = ttk.Label(frame, text="0.00", font=("Consolas", 10, "bold"), foreground="#2C5282")
        self.lbl_s_raw.grid(row=1, column=1, sticky=tk.W, padx=(0, 15), pady=4)
        
        ttk.Label(frame, text="量程占比(16bit):").grid(row=1, column=2, sticky=tk.E, pady=4, padx=5)
        self.lbl_pct_val = ttk.Label(frame, text="0.00 %", font=("Consolas", 10, "bold"), foreground="#805AD5")
        self.lbl_pct_val.grid(row=1, column=3, sticky=tk.W, pady=4)
        
        # 3. 当前档位
        ttk.Label(frame, text="当前档位:").grid(row=2, column=0, sticky=tk.E, pady=4, padx=5)
        self.lbl_gear_val = ttk.Label(frame, text="待机中", font=("Consolas", 10, "bold"), foreground="#C53030")
        self.lbl_gear_val.grid(row=2, column=1, columnspan=3, sticky=tk.W, pady=4)
        
        self.update_loop()

    def update_loop(self):
        if self.top.winfo_exists():
            v_raw = self.calibrator.latest_v_raw
            s_raw = self.calibrator.latest_s_raw
            mode = self.calibrator.latest_mode
            v_lsb = self.calibrator.v_lsb
            
            # 1. 换算电压计算
            v_real = (v_raw * v_lsb) / 1e9
            v_mv = v_real * 1000.0
            self.lbl_v_val.config(text=f"{v_real:.3f} V ({v_mv:.0f} mV)")
            self.lbl_v_raw.config(text=f"{v_raw:.1f}")
            
            # 2. 原始电流 RAW 值
            self.lbl_s_raw.config(text=f"{s_raw:.2f}")
            
            # 3. 电流量程占用百分比 (INA226 满量程 16bit 有符号 ±32768)
            pct = (abs(s_raw) / 32768.0) * 100.0
            self.lbl_pct_val.config(text=f"{pct:.2f} %")
            
            # 4. 当前档位
            gear_map = {0: "10mR 档 (0)", 1: "LowR / 100R 档 (1)"}
            gear_str = gear_map.get(mode, f"档位 {mode}")
            self.lbl_gear_val.config(text=gear_str, foreground="#2B6CB0")
            
            # 0.1 秒 (100ms) 定时刷新
            self.top.after(100, self.update_loop)


class MasterCalibResultGUI:
    """
    终极一站式计算 GUI (完美契合 Q8 定点零点插值表)
    """
    def __init__(self, parent, calibrator):
        self.top = tk.Toplevel(parent)
        self.top.title("终极动态零点后校准与增益压缩工具 V5.4")
        self.top.geometry("820x680")
        self.top.grab_set()
        
        self.calibrator = calibrator
        self.is_confirmed = False
        
        self.v_lsb_entry = None
        self.txt_10mr = None
        self.txt_100r = None
        self.slider_10mr = None
        self.slider_10r = None
        self.txt_code = None

        self.create_widgets()
        self.trigger_recalc()

    def create_widgets(self):
        left_pane = ttk.Frame(self.top, padding="15", width=380)
        left_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        left_pane.pack_propagate(False)
        
        right_pane = ttk.Frame(self.top, padding="15")
        right_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # ---------------- 左侧参数与零点输入 ----------------
        ttk.Label(left_pane, text="1. 物理电压 cal_v_lsb_nv (nV):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=2)
        self.v_lsb_entry = ttk.Entry(left_pane, font=("Consolas", 11), justify="center")
        self.v_lsb_entry.insert(0, str(self.calibrator.v_lsb)) 
        self.v_lsb_entry.pack(fill=tk.X, pady=4)
        self.v_lsb_entry.bind("<KeyRelease>", lambda e: self.trigger_recalc())

        ttk.Label(left_pane, text="2. 大电流档 table_10mr 零点表 (Q8 格式):", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(8, 2))
        self.txt_10mr = tk.Text(left_pane, height=6, font=("Consolas", 9))
        self.txt_10mr.pack(fill=tk.X, pady=2)
        self.txt_10mr.insert(tk.END, "const CalPoint_t table_10mr[] = {\n    { 3200,   4608},\n    { 4500,   3328},\n    { 5600,   3072},\n    {10400,   2560},\n    {22900,   2560},\n    {36000,   3072}\n};")
        self.txt_10mr.bind("<KeyRelease>", lambda e: self.trigger_recalc())

        ttk.Label(left_pane, text="3. 小电流档 table_100r 零点表 (Q8 格式):", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(8, 2))
        self.txt_100r = tk.Text(left_pane, height=6, font=("Consolas", 9))
        self.txt_100r.pack(fill=tk.X, pady=2)
        self.txt_100r.insert(tk.END, "const CalPoint_t table_100r[] = {\n    { 3300,   10240},\n    { 6000,   11008},\n    {10500,   13312},\n    {36000,   29184}\n};")
        self.txt_100r.bind("<KeyRelease>", lambda e: self.trigger_recalc())

        # 4. 10mR 压缩滑块
        ttk.Label(left_pane, text="4. 大电流档 (10mR) 压缩等级:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(10, 2))
        self.label_cnt_10mr = ttk.Label(left_pane, text="保留点数: 0 点", font=("Arial", 9), foreground="blue")
        self.label_cnt_10mr.pack(anchor=tk.W)
        self.slider_10mr = ttk.Scale(left_pane, from_=0, to=100, orient=tk.HORIZONTAL, command=lambda v: self.trigger_recalc())
        self.slider_10mr.set(0) 
        self.slider_10mr.pack(fill=tk.X, pady=4)

        # 5. 10R 压缩滑块
        ttk.Label(left_pane, text="5. 小电流档 (10R) 压缩等级:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(10, 2))
        self.label_cnt_10r = ttk.Label(left_pane, text="保留点数: 0 点", font=("Arial", 9), foreground="blue")
        self.label_cnt_10r.pack(anchor=tk.W)
        self.slider_10r = ttk.Scale(left_pane, from_=0, to=100, orient=tk.HORIZONTAL, command=lambda v: self.trigger_recalc())
        self.slider_10r.set(0)
        self.slider_10r.pack(fill=tk.X, pady=4)

        # ---------------- 右侧 C 代码输出区 ----------------
        ttk.Label(right_pane, text="最终生成的 C 语言结构体代码 (支持动态 LSB 刷新与滑块实时无损压缩):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=2)
        self.txt_code = tk.Text(right_pane, font=("Consolas", 10), bg="#2d3748", fg="#f7fafc", bd=0, wrap=tk.NONE)
        self.txt_code.pack(fill=tk.BOTH, expand=True, pady=5)
        
        btn_frame = ttk.Frame(right_pane)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_frame, text="保存并导出 CSV 报表", command=self.on_confirm, width=25).pack(side=tk.RIGHT)

    def trigger_recalc(self):
        if (self.v_lsb_entry is None or self.txt_10mr is None or self.txt_100r is None or 
            self.slider_10mr is None or self.slider_10r is None or self.txt_code is None):
            return

        try:
            v_lsb = int(self.v_lsb_entry.get().strip())
            self.calibrator.v_lsb = v_lsb
        except ValueError:
            self.txt_code.delete("1.0", tk.END)
            self.txt_code.insert(tk.END, "/* [错误]：电压 LSB 必须输入合法的整数！ */")
            return

        table_mr_q8 = parse_cal_points(self.txt_10mr.get("1.0", tk.END))
        table_r_q8 = parse_cal_points(self.txt_100r.get("1.0", tk.END))
        if not table_mr_q8 or not table_r_q8:
            self.txt_code.delete("1.0", tk.END)
            self.txt_code.insert(tk.END, "/* [错误]：零点校准表格式错误或为空，解析失败！ */")
            return

        self.calibrator.results = {0: [], 1: []}
        
        for r in self.calibrator.raw_cal_data:
            mode = r["Mode_Val"]
            v_raw = r["V_RAW"]  
            
            v_real = (v_raw * self.calibrator.v_lsb) / 1e9
            v_mv = int(round(v_real * 1000))
            s_raw = r["S_RAW"]
            
            if mode == 0:
                s_zero_q8 = interpolate_offset(v_mv, table_mr_q8)
            else:
                s_zero_q8 = interpolate_offset(v_mv, table_r_q8)
                
            s_zero = s_zero_q8 / 256.0 # Q8 转换回高精度 float LSB 零点！
            
            s_net = s_raw - s_zero
            if s_net < 0.1: s_net = 0.1 # 防御保护
            
            label = r["Input_Label"]
            i_real_phys = r["I_Real_Phys_Raw"]
            if i_real_phys < 0: # 电阻任务
                val, _ = parse_input(label)
                i_real_phys = v_real / val if val > 0 else 0.0
                
            i_target_nominal = (3.3 / val) if (parse_input(label)[1] == "RES") else i_real_phys
            error_val = ((i_real_phys - i_target_nominal) / i_target_nominal * 100) if i_target_nominal > 0 else 0
            
            i_real_01ua = i_real_phys * 1e7
            ratio = i_real_01ua / s_net if mode == 0 else (i_real_01ua * 65536.0) / s_net
            ratio_int = int(round(ratio))
            
            eq_res = (s_net * 2.5e-6 / i_real_phys) * 1000 if i_real_phys > 0 else 0
            
            self.calibrator.results[mode].append({
                "Mode": r["Mode_Str"],
                "Input_Label": label,
                "V_Real_V": v_real,
                "Target_Ref_I_A": i_target_nominal,
                "Real_Phys_I_A": i_real_phys,
                "Error_Pct": f"{error_val:+.4f}%",
                "S_RAW": s_raw,
                "S_Zero": s_zero,
                "S_Net": s_net,
                "S_Net_Int": int(round(s_net)),
                "Ratio_Factor": ratio_int,
                "Eq_Res_mOhm": eq_res
            })

        def get_compressed_list(data_list, slider_val):
            if not data_list: return []
            if len(data_list) < 3 or slider_val == 0:
                return data_list
                
            coords = [[r["S_Net_Int"], r["Ratio_Factor"]] for r in data_list]
            ys = [c[1] for c in coords]
            y_span = max(ys) - min(ys)
            
            epsilon = (slider_val / 100.0) * (y_span if y_span > 0 else 1) * 0.25
            simplified_coords = rdp_simplify(coords, epsilon)
            
            simplified_list = []
            for x, y in simplified_coords:
                for r in data_list:
                    if r["S_Net_Int"] == x:
                        simplified_list.append(r)
                        break
            return simplified_list

        self.compressed_10mr = get_compressed_list(self.calibrator.results[0], self.slider_10mr.get())
        self.compressed_10r = get_compressed_list(self.calibrator.results[1], self.slider_10r.get())

        self.label_cnt_10mr.config(text=f"保留点数: {len(self.compressed_10mr)} / {len(self.calibrator.results[0])} 点")
        self.label_cnt_10r.config(text=f"保留点数: {len(self.compressed_10r)} / {len(self.calibrator.results[1])} 点")

        c_code = self.generate_c_code_custom(self.compressed_10mr, self.compressed_10r)
        self.txt_code.delete("1.0", tk.END)
        self.txt_code.insert(tk.END, c_code)

    def generate_c_code_custom(self, data_10mr, data_10r):
        block = "/* ==================================================================\n"
        block += f" *   自动生成固件增益校准表 - 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        block += " * ================================================================== */\n\n"
        
        if data_10mr:
            block += f"const GainPoint_t gain_table_10mr[] = {{\n"
            for r in data_10mr:
                block += f"    {{{r['S_Net_Int']:5d}, {r['Ratio_Factor']:9d}}}, // {r['Input_Label']}\n"
            block += f"}};\n#define GAIN_TABLE_10MR_SIZE {len(data_10mr)}\n\n"
            
        if data_10r:
            block += f"const GainPoint_t gain_table_10r[] = {{\n"
            for r in data_10r:
                block += f"    {{{r['S_Net_Int']:5d}, {r['Ratio_Factor']:9d}}}, // {r['Input_Label']}\n"
            block += f"}};\n#define GAIN_TABLE_10R_SIZE {len(data_10r)}\n\n"
            
        return block

    def on_confirm(self):
        self.is_confirmed = True
        self.top.destroy()


class ProductionCalibrator:
    def __init__(self, port, baud, v_lsb, use_ocr=False, cam_idx=0, rotation_flag=None, deskew_angle=0, roi=None):
        self.dialog_root = tk.Tk()
        self.dialog_root.withdraw()
        
        self.port = port
        self.baud = baud
        self.v_lsb = v_lsb
        
        self.use_ocr = use_ocr
        if self.use_ocr:
            self.cam_idx = cam_idx
            self.rotation_flag = rotation_flag
            self.deskew_angle = deskew_angle
            self.roi = roi
            self.cap = cv2.VideoCapture(self.cam_idx, cv2.CAP_DSHOW)
        else:
            self.cap = None
            
        self.ser = None
        
        # ---------------- 实时数据与后台解包控制 ----------------
        self.latest_v_raw = 0.0
        self.latest_s_raw = 0.0
        self.latest_mode = 0
        
        self.is_sampling = False
        self.sample_buffer = []
        self.is_running = True
        
        self.connect_serial()
        
        # 启动后台串口接收线程
        self.bg_thread = threading.Thread(target=self._bg_serial_reader, daemon=True)
        self.bg_thread.start()
        
        self.results = {0: [], 1: []} 
        self.raw_cal_data = [] 

    def connect_serial(self):
        try:
            if self.ser is not None and self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(self.port, self.baud, timeout=0.5)
            print(f"系统就绪：已连接 {self.port} @ {self.baud}bps")
            return True
        except Exception as e:
            print(f"\n[串口错误] 无法打开串口 {self.port}: {e}")
            return False

    def _bg_serial_reader(self):
        """后台线程：持续解包串口数据，保证实时监控 0.1s 刷新，兼顾精准超滤采样"""
        while self.is_running:
            if self.ser is None or not self.ser.is_open:
                time.sleep(0.1)
                continue
            try:
                if self.ser.in_waiting >= 16:
                    chunk = self.ser.read_until(TAIL)
                    if len(chunk) == 16:
                        v, s, m = struct.unpack('<fff', chunk[:12])
                        self.latest_v_raw = v
                        self.latest_s_raw = s
                        self.latest_mode = int(m)
                        
                        if self.is_sampling:
                            self.sample_buffer.append((v, s, int(m)))
                else:
                    time.sleep(0.002)
            except Exception:
                time.sleep(0.05)

    def decode_7segment(self, digit_roi, debug_draw_img, offset_x, offset_y):
        h, w = digit_roi.shape
        aspect_ratio = h / w
        if aspect_ratio > 3.0:
            return '1'
        if aspect_ratio < 0.7:
            return '-'

        dw = int(w * 0.25)
        dh = int(h * 0.14)
        
        segments = {
            'A': (int(w*0.2), 0, int(w*0.6), dh),                       
            'F': (0, int(h*0.08), dw, int(h*0.38)),                    
            'B': (w - dw, int(h*0.08), dw, int(h*0.38)),                
            'G': (int(w*0.2), int(h*0.43), int(w*0.6), int(h*0.14)),    
            'E': (0, int(h*0.54), dw, int(h*0.38)),                    
            'C': (w - dw, int(h*0.54), dw, int(h*0.38)),               
            'D': (int(w*0.2), h - dh, int(w*0.6), dh)                   
        }
        
        states = {}
        for seg_name, (sx, sy, sw, sh) in segments.items():
            seg_roi = digit_roi[sy:sy+sh, sx:sx+sw]
            if seg_roi.size == 0:
                states[seg_name] = 0
                continue
            
            active_ratio = np.sum(seg_roi == 255) / seg_roi.size
            is_active = 1 if active_ratio > 0.22 else 0
            states[seg_name] = is_active
            
            color = (0, 255, 0) if is_active else (0, 0, 255)
            cv2.rectangle(debug_draw_img, (offset_x + sx, offset_y + sy), 
                          (offset_x + sx + sw, offset_y + sy + sh), color, 1)

        pattern = (states['A'], states['B'], states['C'], states['D'], states['E'], states['F'], states['G'])
        
        mapping = {
            (1, 1, 1, 1, 1, 1, 0): '0',
            (0, 1, 1, 0, 0, 0, 0): '1',
            (1, 1, 0, 1, 1, 0, 1): '2',
            (1, 1, 1, 1, 0, 0, 1): '3',
            (0, 1, 1, 0, 0, 1, 1): '4',
            (1, 0, 1, 1, 0, 1, 1): '5',
            (1, 0, 1, 1, 1, 1, 1): '6',  
            (0, 0, 1, 1, 1, 1, 1): '6',  
            (1, 1, 1, 0, 0, 0, 0): '7',  
            (1, 1, 1, 0, 0, 1, 0): '7',  
            (1, 1, 1, 1, 1, 1, 1): '8',
            (1, 1, 1, 1, 0, 1, 1): '9',  
            (1, 1, 1, 0, 0, 1, 1): '9'   
        }
        
        return mapping.get(pattern, '?')

    def parse_multimeter_screen(self, cropped):
        straightened = deskew_image(cropped, angle_deg=self.deskew_angle)
        gray = cv2.cvtColor(straightened, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (0, 0), fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        
        _, thresh = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 5))
        dilated = cv2.dilate(thresh, kernel, iterations=2)
        
        debug_img = cv2.cvtColor(dilated, cv2.COLOR_GRAY2BGR)
        contours, hierarchy = cv2.findContours(dilated, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        
        digit_boxes = []
        dot_boxes = []
        img_h, img_w = dilated.shape
        
        if hierarchy is not None:
            hierarchy = hierarchy[0]  
            for i, ctr in enumerate(contours):
                if hierarchy[i][3] != -1:
                    continue
                    
                x, y, w, h = cv2.boundingRect(ctr)
                if w < 5 or h < 5:
                    continue
                    
                if h > img_h * 0.45 and w < img_w * 0.22:
                    if 0.4 < (h / w) < 30.0:
                        digit_boxes.append((x, y, w, h, 'digit'))
                elif h < img_h * 0.25 and w < img_h * 0.25 and w < img_w * 0.08:
                    if y > img_h * 0.5:
                        dot_boxes.append((x, y, w, h, 'dot'))
                    
        all_boxes = sorted(digit_boxes + dot_boxes, key=lambda b: b[0])
        
        decoded_chars = []
        for x, y, w, h, b_type in all_boxes:
            if b_type == 'digit':
                digit_roi = dilated[y:y+h, x:x+w]
                char = self.decode_7segment(digit_roi, debug_img, x, y)
                decoded_chars.append(char)
                
                cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 1)
                cv2.putText(debug_img, char, (x + 2, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            elif b_type == 'dot':
                decoded_chars.append('.')
                cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 255), 1)
                
        result_str = "".join(decoded_chars)
        
        straightened_resized = cv2.resize(straightened, (debug_img.shape[1], debug_img.shape[0]))
        hud_view = np.hstack((straightened_resized, debug_img))
        cv2.line(hud_view, (straightened_resized.shape[1], 0), (straightened_resized.shape[1], hud_view.shape[0]), (0, 0, 255), 2)
        cv2.putText(hud_view, "1. Straightened", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(hud_view, f"2. HUD Debug [Result: {result_str}]", (straightened_resized.shape[1] + 10, 25), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        cv2.imshow("Industrial 7-Segment HUD", hud_view)
        cv2.waitKey(1)
        
        return result_str

    def get_multimeter_ocr_string(self):
        if self.cap is None or not self.cap.isOpened():
            return ""
        for _ in range(5):
            ret, frame = self.cap.read()
        if not ret:
            return ""
            
        if self.rotation_flag is not None:
            frame = cv2.rotate(frame, self.rotation_flag)
        if self.roi:
            x, y, w, h = self.roi
            cropped = frame[y:y+h, x:x+w]
        else:
            cropped = frame
            
        try:
            raw_text = self.parse_multimeter_screen(cropped)
            return raw_text
        except Exception as e:
            print(f"解析出错: {e}")
            return ""

    def get_data(self, count=4096):
        """【底层逻辑保持不变】：收集 4096 次采样，计算精确平均值"""
        self.sample_buffer = []
        self.is_sampling = True
        
        start_t = time.time()
        while len(self.sample_buffer) < count:
            if time.time() - start_t > 5.0:
                break
            time.sleep(0.002)
            
        self.is_sampling = False
        
        if not self.sample_buffer:
            return 0.0, 0.0, 0
            
        v_l = [p[0] for p in self.sample_buffer]
        s_l = [p[1] for p in self.sample_buffer]
        m_l = [p[2] for p in self.sample_buffer]
        
        return np.mean(v_l), np.mean(s_l), int(m_l[0])

    def open_ocr_dialog(self, ocr_text, default_unit):
        """线程安全地在主 GUI 线程中弹框确认 OCR 结果"""
        res = {'val': None, 'label': ''}
        event = threading.Event()
        
        def _gui():
            dialog = OCRConfirmationDialog(self.dialog_root, ocr_text, default_unit=default_unit)
            self.dialog_root.wait_window(dialog.top)
            res['val'] = dialog.result_val
            res['label'] = dialog.result_str_label
            event.set()
            
        self.dialog_root.after(0, _gui)
        event.wait()
        return res['val'], res['label']

    def open_master_gui(self):
        """线程安全地在主 GUI 线程中打开终极计算面板"""
        res = {'confirmed': False}
        event = threading.Event()
        
        def _gui():
            result_gui = MasterCalibResultGUI(self.dialog_root, self)
            self.dialog_root.wait_window(result_gui.top)
            res['confirmed'] = result_gui.is_confirmed
            if result_gui.is_confirmed:
                self.results[0] = result_gui.compressed_10mr
                self.results[1] = result_gui.compressed_10r
            event.set()
            
        self.dialog_root.after(0, _gui)
        event.wait()
        return res['confirmed']

    def _cli_task_loop(self):
        """命令行终端主任务线程，与 GUI 悬浮监控并行不冲突"""
        print("\n" + "="*80)
        print(f"{'== 启动全维度物理校准系统 V5.4 (终极增益计算版) ==':^80}")
        print("="*80)
        
        res_list = []
        if os.path.exists("resistors.txt"):
            with open("resistors.txt", "r") as f:
                res_list = [line.strip() for line in f if line.strip()]
            print(f"> 已从 resistors.txt 加载 {len(res_list)} 个预设任务。")
        else:
            print("> [提示] 未检测到 resistors.txt 预设文件。")
            print("> 系统已进入【手动回车自动采样模式】（直接按回车，将自动进行 4096 次超滤采集，极度稳定）")

        print("\n" + "-"*90)
        header = f"{'Mode':<6} | {'Label':<12} | {'V_RAW(LSB)':<12} | {'S_RAW(LSB)':<12}"
        print(header)
        print("-" * 90)

        task_idx = 0

        while True:
            if task_idx < len(res_list):
                target_str = res_list[task_idx]
                prompt = f"\n[任务 {task_idx+1}] 请接入 {target_str} 并按回车 (Y结束并计算): "
            else:
                prompt = f"\n[测试点 {task_idx+1}] 请接入负载并【直接按回车】开始测量 (Y结束并计算): "
                target_str = None

            flush_input_buffer()
            u_in = input(prompt).strip().upper()
            if u_in == 'Y': 
                break
            
            if u_in == "":
                if target_str:
                    current_label = target_str
                else:
                    if self.use_ocr:
                        current_label = "OCR_AUTO_MEASURE"
                    else:
                        print("!! 当前未启用摄像头，手动模式下请必须输入电阻或电流值（如 10R 或 1A）")
                        continue
            else:
                current_label = u_in

            print("正在获取系统原始信号并计算电压（4096 次超滤中...）")
            v_raw, s_raw, mode = self.get_data(4096)
            
            if current_label == "OCR_AUTO_MEASURE":
                print("正在通过 OCR 读取万用表实际电流读数...")
                ocr_text = self.get_multimeter_ocr_string()
                
                i_real_phys, current_label_log = self.open_ocr_dialog(ocr_text, default_unit="mA")
                if i_real_phys is None:
                    print("用户放弃了此点，已跳过。")
                    continue
            else:
                val, itype = parse_input(current_label)
                if val is None:
                    print("!! 无法解析当前输入标签。")
                    continue
                    
                if self.use_ocr and itype == "CUR":
                    print("正在通过 OCR 读取万用表实际电流读数...")
                    ocr_text = self.get_multimeter_ocr_string()
                    
                    default_unit = "mA"
                    if "UA" in current_label.upper():
                        default_unit = "uA"
                    elif "MA" in current_label.upper():
                        default_unit = "mA"
                    elif "A" in current_label.upper():
                        default_unit = "A"
                    
                    i_real_phys, current_label_log = self.open_ocr_dialog(ocr_text, default_unit=default_unit)
                    if i_real_phys is None:
                        print("用户放弃了此点，已跳过。")
                        continue
                else:
                    i_real_phys = val if itype == "CUR" else -1.0 
                    current_label_log = current_label

            mode_str = "10mR" if mode == 0 else "LowR"

            row_str = f"{mode_str:<6} | {current_label_log:<12} | {v_raw:<12.1f} | {s_raw:<12.2f}"
            print(row_str)

            # 暂存原始测量数据（不改变逻辑）
            self.raw_cal_data.append({
                "Mode_Val": mode,
                "Mode_Str": mode_str,
                "Input_Label": current_label_log,
                "V_RAW": v_raw,             
                "S_RAW": s_raw,
                "I_Real_Phys_Raw": i_real_phys  
            })
            task_idx += 1

        if self.cap and self.cap.isOpened():
            self.cap.release()
        cv2.destroyAllWindows()

        if not self.raw_cal_data:
            print("没有采集到任何数据。")
            self.dialog_root.after(0, self.dialog_root.quit)
            return

        # 启动一站式计算 GUI 窗口
        print("\n正在启动终极计算面板，请在弹窗中配置参数...")
        is_confirmed = self.open_master_gui()

        if not is_confirmed:
            print("用户放弃保存，程序退出。")
            self.dialog_root.after(0, self.dialog_root.quit)
            return

        self.export()
        self.dialog_root.after(0, self.dialog_root.quit)

    def run(self):
        # 1. 弹出 0.1s 实时悬浮监控窗口
        LiveSensorMonitorGUI(self.dialog_root, self)
        
        # 2. 启动终端主交互逻辑子线程
        cli_thread = threading.Thread(target=self._cli_task_loop, daemon=True)
        cli_thread.start()
        
        # 3. 运行 Tkinter 主循环（保障 GUI 刷新流畅不冻结）
        self.dialog_root.mainloop()

    def export(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        csv_filename = f"calib_report_{ts}.csv"
        
        all_data = self.results[0] + self.results[1]
        if not all_data: return

        c_code_block = self.generate_c_code()

        with open(csv_filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["# 全局校准配置"])
            writer.writerow(["V_LSB_NV", self.v_lsb])
            writer.writerow(["S_Zero_Mode", "Dynamic Interpolation Table"])
            writer.writerow([])
            
            dict_writer = csv.DictWriter(f, fieldnames=all_data[0].keys())
            dict_writer.writeheader()
            dict_writer.writerows(all_data)
            
            writer.writerow([])
            writer.writerow(["# 复制下方单元格即可获得完整代码"])
            writer.writerow(["GEN_C_CODE", c_code_block])

        print("\n" + "="*80)
        print(f">>> 报表已生成: {csv_filename}")
        print(">>> 最终固件代码预览:")
        print(c_code_block)
        print("="*80)

    def generate_c_code(self):
        block = "/* ==================================================================\n"
        block += f" *   自动生成固件增益校准表 - 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        block += " * ================================================================== */\n\n"
        
        if self.results[0]:
            block += f"const GainPoint_t gain_table_10mr[] = {{\n"
            for r in self.results[0]:
                block += f"    {{{r['S_Net_Int']:5d}, {r['Ratio_Factor']:9d}}}, // {r['Input_Label']}\n"
            block += f"}};\n#define GAIN_TABLE_10MR_SIZE {len(self.results[0])}\n\n"
            
        if self.results[1]:
            block += f"const GainPoint_t gain_table_10r[] = {{\n"
            for r in self.results[1]:
                block += f"    {{{r['S_Net_Int']:5d}, {r['Ratio_Factor']:9d}}}, // {r['Input_Label']}\n"
            block += f"}};\n#define GAIN_TABLE_10R_SIZE {len(self.results[1])}\n\n"
            
        return block


if __name__ == "__main__":
    try:
        # 启动校准配置与数码管相机 GUI (提供串口选择与 OCR / 手动模式二选一)
        gui = CameraConfigGUI()
        confirmed, use_ocr, port, baud, cam_idx, rotation_flag, deskew_angle, roi = gui.run()
        
        if confirmed:
            calibrator = ProductionCalibrator(
                port, baud, v_lsb=1250000, 
                use_ocr=use_ocr, 
                cam_idx=cam_idx, 
                rotation_flag=rotation_flag, 
                deskew_angle=deskew_angle, 
                roi=roi
            )
            calibrator.run()
        else:
            print("用户取消了配置，程序已退出。")
            
    except Exception as e:
        print(f"\n程序运行中发生异常: {e}")

