# -*- coding: utf-8 -*-
"""
模块名称: 1.电压校准 - 可选
版本号: V26.10.13
"""
__version__ = "V26.10.13"

import serial
import serial.tools.list_ports
import struct
import time
import numpy as np
import cv2
import re
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import simpledialog

# --- 协议默认配置 ---
DEFAULT_PORT = "COM5"          
DEFAULT_BAUD = 2000000         
PACKET_SIZE = 16
TAIL = b'\x00\x00\x80\x7F'


def deskew_image(img, angle_deg):
    """
    仿射变换拉直算法
    """
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


class CameraConfigGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("电压校准配置与串口选择")
        self.root.geometry("490x440") 
        self.root.resizable(False, False)
        
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(1000, lambda: self.root.attributes("-topmost", False))
        
        self.selected_port = DEFAULT_PORT
        self.selected_baud = DEFAULT_BAUD
        self.selected_camera_idx = 0
        self.selected_rotation = 0  
        self.selected_deskew = 12  
        self.roi = None
        self.is_confirmed = False
        self.use_ocr = True  # OCR功能开关

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 串口选择与一键刷新
        ttk.Label(main_frame, text="分析仪串口:", font=("Arial", 10)).grid(row=0, column=0, sticky=tk.W, pady=6)
        port_frame = ttk.Frame(main_frame)
        port_frame.grid(row=0, column=1, sticky=tk.W, pady=6)
        
        self.port_list = get_available_ports()
        self.port_combo = ttk.Combobox(port_frame, values=self.port_list, width=26)
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        else:
            self.port_combo.set(DEFAULT_PORT)
        self.port_combo.pack(side=tk.LEFT, padx=(0, 5))
        
        self.btn_refresh = ttk.Button(port_frame, text="刷新", width=5, command=self.refresh_ports)
        self.btn_refresh.pack(side=tk.LEFT)

        # 2. 波特率配置
        ttk.Label(main_frame, text="通信波特率:", font=("Arial", 10)).grid(row=1, column=0, sticky=tk.W, pady=6)
        self.baud_combo = ttk.Combobox(main_frame, values=["2000000", "1500000", "921600", "115200"], width=16)
        self.baud_combo.set(str(DEFAULT_BAUD))
        self.baud_combo.grid(row=1, column=1, sticky=tk.W, pady=6)

        # 3. 摄像头选择
        ttk.Label(main_frame, text="选择摄像头:", font=("Arial", 10)).grid(row=2, column=0, sticky=tk.W, pady=6)
        cameras = get_available_cameras()
        self.camera_combo = ttk.Combobox(main_frame, values=cameras, width=33, state="readonly")
        self.camera_combo.current(0)
        self.camera_combo.grid(row=2, column=1, sticky=tk.W, pady=6)

        # 4. 画面旋转角度
        ttk.Label(main_frame, text="画面旋转角度:", font=("Arial", 10)).grid(row=3, column=0, sticky=tk.W, pady=6)
        self.rotation_combo = ttk.Combobox(main_frame, values=["0°", "90° 顺时针", "180°", "270° 顺时针"], width=16, state="readonly")
        self.rotation_combo.current(0)
        self.rotation_combo.grid(row=3, column=1, sticky=tk.W, pady=6)

        # 5. 数码管倾斜校正
        ttk.Label(main_frame, text="数码管倾斜校正:", font=("Arial", 10)).grid(row=4, column=0, sticky=tk.W, pady=6)
        self.deskew_combo = ttk.Combobox(main_frame, values=["0° (垂直屏)", "5°", "10°", "12° (推荐)", "15°", "-5°", "-10°"], width=16, state="readonly")
        self.deskew_combo.current(3) 
        self.deskew_combo.grid(row=4, column=1, sticky=tk.W, pady=6)

        ttk.Separator(main_frame, orient='horizontal').grid(row=5, column=0, columnspan=2, sticky='ew', pady=10)

        # 操作按钮区
        self.btn_preview = ttk.Button(main_frame, text="打开预览 并 框选数码管屏幕", command=self.preview_and_crop)
        self.btn_preview.grid(row=6, column=0, columnspan=2, sticky='ew', pady=4)

        self.btn_confirm = ttk.Button(main_frame, text="确认配置并开始校准 (带 OCR 自动识别)", command=self.confirm_settings)
        self.btn_confirm.grid(row=7, column=0, columnspan=2, sticky='ew', pady=4)

        self.btn_no_ocr = ttk.Button(main_frame, text="不启动 OCR (手动输入电压模式)", command=self.confirm_no_ocr)
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
    def __init__(self, parent, detected_val_str):
        self.top = tk.Toplevel(parent)
        self.top.title("数据确认")
        self.top.geometry("380x160")
        self.top.resizable(False, False)
        self.top.grab_set()  
        
        self.result = None
        
        ttk.Label(self.top, text=f"数码管识别结果: {detected_val_str} V", font=("Arial", 12, "bold"), foreground="green").pack(pady=10)
        ttk.Label(self.top, text="如识别有误请在下方修改，无误直接按 回车 确认:").pack(pady=2)
        
        self.entry = ttk.Entry(self.top, font=("Arial", 12), width=20, justify="center")
        self.entry.insert(0, detected_val_str)
        self.entry.pack(pady=5)
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)  
        
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
        try:
            self.result = float(self.entry.get())
            self.top.destroy()
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字！")

    def on_cancel(self):
        self.result = None
        self.top.destroy()


class CalibMaster:
    def __init__(self, port, baud, camera_idx, rotation_flag, deskew_angle, roi, use_ocr=True):
        self.dialog_root = tk.Tk()
        self.dialog_root.withdraw()  
        
        self.port = port
        self.baud = baud
        self.camera_idx = camera_idx
        self.rotation_flag = rotation_flag
        self.deskew_angle = deskew_angle
        self.roi = roi
        self.use_ocr = use_ocr
        
        self.ser = None
        self.connect_serial()
        
        # 仅当启动 OCR 时才激活摄像头工具链
        if self.use_ocr:
            self.cap = cv2.VideoCapture(self.camera_idx, cv2.CAP_DSHOW)
        else:
            self.cap = None

    def connect_serial(self):
        try:
            if self.ser is not None and self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(self.port, self.baud, timeout=2.0)
            print(f"系统就绪：已连接 {self.port} @ {self.baud}bps")
            return True
        except Exception as e:
            print(f"\n[串口错误] 无法打开串口 {self.port}: {e}")
            return False

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
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 6))
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

    def get_multimeter_value(self):
        if self.cap is None or not self.cap.isOpened():
            return None
        for _ in range(5):
            ret, frame = self.cap.read()
        if not ret:
            return None
            
        if self.rotation_flag is not None:
            frame = cv2.rotate(frame, self.rotation_flag)
        if self.roi:
            x, y, w, h = self.roi
            cropped = frame[y:y+h, x:x+w]
        else:
            cropped = frame
            
        try:
            raw_text = self.parse_multimeter_screen(cropped)
            print(f"[数码管解析原始结果]: '{raw_text}'")
            match = re.search(r"[-+]?\d*\.\d+|\d+", raw_text)
            if match:
                return float(match.group())
        except Exception as e:
            print(f"解析出错: {e}")
            
        return None

    def flush_and_capture(self, sample_count=4096):
        try:
            self.ser.flushInput()
        except (serial.SerialException, AttributeError):
            print(f"\n[串口通信异常] 连接已断开，正在尝试重新建立连接...")
            while not self.connect_serial():
                time.sleep(1)
            self.ser.flushInput()

        raw_buf = bytearray()
        v_samples = []
        start_t = time.time()
        
        while len(v_samples) < sample_count:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.read(self.ser.in_waiting)
                    raw_buf.extend(data)
                    while len(raw_buf) >= PACKET_SIZE:
                        idx = raw_buf.find(TAIL)
                        if idx == 12:
                            v, s, m = struct.unpack('<fff', raw_buf[0:12])
                            v_samples.append(v)
                            del raw_buf[:16]
                        elif idx != -1: del raw_buf[:idx+4]
                        else: break
            except (serial.SerialException, PermissionError) as e:
                print(f"\n[读取中途断开] {e}，正在尝试重连...")
                while not self.connect_serial():
                    time.sleep(1)
                break  
                
            if time.time() - start_t > 4.0:
                break
                
        if not v_samples:
            return None
        return {
            "avg": np.mean(v_samples),
            "min": np.min(v_samples),
            "max": np.max(v_samples),
            "std": np.std(v_samples),
            "pp": np.max(v_samples) - np.min(v_samples),
            "count": len(v_samples)
        }

    def start_voltage_cal(self):
        print("\n" + "="*50)
        mode_str = "OCR识别模式" if self.use_ocr else "纯手动输入模式"
        print(f"【电压线性度校准向导 - 4096次深度平均 ({mode_str})】")
        print("="*50)
        points = []
        while True:
            flush_input_buffer()
            
            user_input = input(f"\n[待机中] 按 ENTER 开始读取当前点数据，输入 'Y' 结束并计算: ").strip().upper()
            if user_input == 'Y':
                if len(points) < 1:
                    print("错误：请至少提供一个校准点。")
                    continue
                break
            
            # 判断是否启用 OCR
            if self.use_ocr:
                print("正在读取万用表屏幕...")
                real_v = self.get_multimeter_value()
                
                if real_v is None:
                    print("【段码识别失败】")
                    manual_str = simpledialog.askstring("识别失败", "数码管未解析成功，请手动输入万用表数值:", parent=self.dialog_root)
                    if not manual_str:
                        print("已跳过此点。")
                        continue
                    try:
                        real_v = float(manual_str)
                    except ValueError:
                        print("输入无效数字，已跳过。")
                        continue
                else:
                    dialog = OCRConfirmationDialog(self.dialog_root, f"{real_v:.4f}")
                    self.dialog_root.wait_window(dialog.top)  
                    
                    real_v = dialog.result
                    if real_v is None:
                        print("用户放弃了此点。")
                        continue
            else:
                # 未开启 OCR 时直接请求用户手动输入电压值
                manual_str = simpledialog.askstring("手动输入电压", "请输入当前万用表实际电压值 (V):", parent=self.dialog_root)
                if not manual_str:
                    print("用户取消输入，已跳过此点。")
                    continue
                try:
                    real_v = float(manual_str)
                except ValueError:
                    print("输入无效数字，已跳过。")
                    continue

            print("正在采集设备电压信号（正在进行 4096 次级联深度平均，耗时约 0.8 秒）...")
            stats = self.flush_and_capture(4096)
            if stats is None:
                print("[采集失败] 未能获取到有效的串口数据，已跳过。")
                continue
            
            point_lsb = (real_v * 1e9) / stats['avg']
            point_data = {
                "real_v": real_v,
                "avg_raw": stats['avg'],
                "min": stats['min'],
                "max": stats['max'],
                "pp": stats['pp'],
                "std": stats['std'],
                "lsb": point_lsb
            }
            points.append(point_data)
            print("-" * 30)
            print(f"  当前测试电压:       {real_v:.4f} V")
            print(f"  平均原始值 (Mean): {stats['avg']:.4f}")
            print(f"  单点计算 LSB:       {point_lsb:.2f} nV")
            print("-" * 30)

        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
        cv2.destroyAllWindows()
        self.dialog_root.destroy()

        if not points:
            return
        all_lsbs = [p['lsb'] for p in points]
        avg_lsb = np.mean(all_lsbs)
        print("\n" + "#"*50)
        print("【最终汇总报告】")
        print("#"*50)
        print(f"{'实测电压(V)':<15} | {'平均RAW':<15} | {'单点LSB(nV)':<15} | {'相对偏差'}")
        print("-" * 65)
        for p in points:
            deviation = p['lsb'] - avg_lsb
            print(f"{p['real_v']:<15.4f} | {p['avg_raw']:<15.2f} | {p['lsb']:<15.2f} | {deviation:+.2f}")
        print("-" * 65)
        print(f"\n>>> 推荐固件参数：cal_v_lsb_nv = {int(round(avg_lsb))}")
        print(f">>> 线性度最大极差：{max(all_lsbs) - min(all_lsbs):.2f} nV")
        print("#"*50)


if __name__ == "__main__":
    gui = CameraConfigGUI()
    confirmed, use_ocr, port, baud, cam_idx, rotation_flag, deskew_angle, roi = gui.run()
    
    if confirmed:
        master = CalibMaster(port, baud, cam_idx, rotation_flag, deskew_angle, roi, use_ocr=use_ocr)
        master.start_voltage_cal()
    else:
        print("用户取消了配置或直接关闭了窗口。")

