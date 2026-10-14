# -*- coding: utf-8 -*-
"""
模块名称: 2.电流零点校准 - 显示
版本号: V26.10.13
"""
__version__ = "V26.10.13"

import serial
import serial.tools.list_ports
import struct
import time
import math
import numpy as np
import threading
import re
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# --- 串口与协议配置 ---
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


def calculate_distance(p, start, end):
    x, y = p; x1, y1 = start; x2, y2 = end
    area = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1)
    bottom = math.sqrt((y2 - y1)**2 + (x2 - x1)**2)
    return area / bottom if bottom != 0 else 0


def rdp_simplify_to_indices(points, epsilon):
    if len(points) < 3:
        return list(range(len(points)))
        
    def _rdp(pts, eps, start_idx, end_idx):
        dmax, index = 0, start_idx
        for i in range(start_idx + 1, end_idx):
            d = calculate_distance(pts[i], pts[start_idx], pts[end_idx])
            if d > dmax:
                index, dmax = i, d
        if dmax > eps:
            return _rdp(pts, eps, start_idx, index)[:-1] + _rdp(pts, eps, index, end_idx)
        return [start_idx, end_idx]
        
    return _rdp(points, epsilon, 0, len(points) - 1)


class RDPCompressorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("电流零点校准 - RDP 实时压缩调参仪 V1.1")
        self.root.geometry("980x720")
        
        # 核心业务变量
        self.raw_samples = []
        self.is_recording = False
        self.serial_port = None
        self.v_lsb = 1250000
        
        # 实时传感器监控变量
        self.latest_v_r = 0.0
        self.latest_s_r = 0.0
        self.latest_m = 0
        
        self.bucket_maps = {0: {}, 1: {}}
        self.smoothed_points = {0: [], 1: []}
        self.raw_points_map = {0: [], 1: []}
        
        # 先行初始化为空，防止 trigger_recalc 报错
        self.slider_10mr = None
        self.slider_10r = None
        self.code_txt = None
        self.status_label = None

        self.create_widgets()

    def create_widgets(self):
        # 1. 顶部控制栏
        top_frame = ttk.LabelFrame(self.root, text=" 1. 物理零点全量录制控制 ", padding="10")
        top_frame.pack(fill=tk.X, padx=15, pady=5)
        
        ttk.Label(top_frame, text="分析仪串口:").grid(row=0, column=0, padx=4)
        self.port_list = get_available_ports()
        self.port_combo = ttk.Combobox(top_frame, values=self.port_list, width=22)
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        else:
            self.port_combo.set(DEFAULT_PORT)
        self.port_combo.grid(row=0, column=1, padx=4)
        
        self.btn_refresh = ttk.Button(top_frame, text="刷新", width=5, command=self.refresh_ports)
        self.btn_refresh.grid(row=0, column=2, padx=(0, 6))
        
        ttk.Label(top_frame, text="波特率:").grid(row=0, column=3, padx=4)
        self.baud_combo = ttk.Combobox(top_frame, values=["2000000", "1500000", "921600", "115200"], width=10)
        self.baud_combo.set(str(DEFAULT_BAUD))
        self.baud_combo.grid(row=0, column=4, padx=4)
        
        ttk.Label(top_frame, text="V_LSB_NV:").grid(row=0, column=5, padx=4)
        self.v_lsb_entry = ttk.Entry(top_frame, width=9)
        self.v_lsb_entry.insert(0, "1250000")  # 默认使用 1250000 电压 LSB
        self.v_lsb_entry.grid(row=0, column=6, padx=4)
        
        self.btn_record = ttk.Button(top_frame, text="开始录制数据", command=self.toggle_recording)
        self.btn_record.grid(row=0, column=7, padx=10)
        
        self.status_label = ttk.Label(top_frame, text="状态: 待机。请接入负载并开始...", foreground="blue")
        self.status_label.grid(row=0, column=8, padx=5, sticky=tk.W)

        # 2. INA226 传感器实时监控面板 (0.1秒/100ms 刷新率)
        monitor_frame = ttk.LabelFrame(self.root, text=" 2. INA226 传感器实时监控 (0.1s 刷新) ", padding="10")
        monitor_frame.pack(fill=tk.X, padx=15, pady=5)

        ttk.Label(monitor_frame, text="换算电压:").grid(row=0, column=0, padx=(5, 2), sticky=tk.E)
        self.lbl_v_val = ttk.Label(monitor_frame, text="0.000 V (0 mV)", font=("Consolas", 10, "bold"), foreground="#2B6CB0")
        self.lbl_v_val.grid(row=0, column=1, padx=(0, 20), sticky=tk.W)

        ttk.Label(monitor_frame, text="电流 Raw 值:").grid(row=0, column=2, padx=(5, 2), sticky=tk.E)
        self.lbl_raw_val = ttk.Label(monitor_frame, text="0.00", font=("Consolas", 10, "bold"), foreground="#2C5282")
        self.lbl_raw_val.grid(row=0, column=3, padx=(0, 20), sticky=tk.W)

        ttk.Label(monitor_frame, text="量程占比(16-bit):").grid(row=0, column=4, padx=(5, 2), sticky=tk.E)
        self.lbl_pct_val = ttk.Label(monitor_frame, text="0.00 %", font=("Consolas", 10, "bold"), foreground="#805AD5")
        self.lbl_pct_val.grid(row=0, column=5, padx=(0, 20), sticky=tk.W)

        ttk.Label(monitor_frame, text="当前档位:").grid(row=0, column=6, padx=(5, 2), sticky=tk.E)
        self.lbl_gear_val = ttk.Label(monitor_frame, text="待机 (未录制)", font=("Consolas", 10, "bold"), foreground="#C53030")
        self.lbl_gear_val.grid(row=0, column=7, padx=5, sticky=tk.W)

        # 3. 中部滑块调参面板
        self.slider_frame = ttk.LabelFrame(self.root, text=" 3. RDP 容差实时微调阻尼 ", padding="10")
        self.slider_frame.pack(fill=tk.X, padx=15, pady=5)
        
        # 10mR 档 Epsilon 滑块
        ttk.Label(self.slider_frame, text="10mR 档 RDP 容差 (Epsilon):").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.eps_10mr_val_label = ttk.Label(self.slider_frame, text="0.50", font=("Arial", 10, "bold"), foreground="brown")
        self.eps_10mr_val_label.grid(row=0, column=1, padx=5)
        self.slider_10mr = ttk.Scale(self.slider_frame, from_=0.01, to=3.0, value=0.50, length=400, command=self.on_slider_changed)
        self.slider_10mr.grid(row=0, column=2, padx=10, pady=5)
        
        # 100R 档 Epsilon 滑块
        ttk.Label(self.slider_frame, text="100R 档 RDP 容差 (Epsilon):").grid(row=1, column=0, padx=5, sticky=tk.W)
        self.eps_100r_val_label = ttk.Label(self.slider_frame, text="1.00", font=("Arial", 10, "bold"), foreground="brown")
        self.eps_100r_val_label.grid(row=1, column=1, padx=5)
        self.slider_100r = ttk.Scale(self.slider_frame, from_=0.01, to=15.0, value=1.00, length=400, command=self.on_slider_changed)
        self.slider_100r.grid(row=1, column=2, padx=10, pady=5)
        
        self.set_sliders_state("disabled")

        # 4. 底部 C 代码输出区域
        bottom_frame = ttk.LabelFrame(self.root, text=" 4. 生成的 C 语言零点校准表 (Q8 放大256倍格式，实时刷新) ")
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        self.code_txt = scrolledtext.ScrolledText(bottom_frame, font=("Consolas", 10), bg="#2D3748", fg="#F7FAFC", insertbackground="white")
        self.code_txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.code_txt.insert(tk.END, "请先启动上方录制，改变电压，并旋动切档。完成后点击“停止录制”生成代码...")

    def refresh_ports(self):
        self.port_list = get_available_ports()
        self.port_combo['values'] = self.port_list
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        messagebox.showinfo("刷新成功", f"扫描到 {len(self.port_list)} 个串口设备！")

    def set_sliders_state(self, state):
        self.slider_10mr.config(state=state)
        self.slider_100r.config(state=state)

    def toggle_recording(self):
        if not self.is_recording:
            raw_port = self.port_combo.get().strip()
            if not raw_port or "无可用串口" in raw_port:
                messagebox.showerror("串口错误", "请先选择或输入有效的串口号！")
                return
            match = re.search(r"(COM\d+)", raw_port, re.IGNORECASE)
            port = match.group(1).upper() if match else raw_port.split(":")[0].strip()

            raw_baud = self.baud_combo.get().strip()
            try:
                baud = int(raw_baud)
            except ValueError:
                baud = DEFAULT_BAUD

            # 预测试串口连通性，防止被占用或打不开时程序崩溃
            try:
                test_ser = serial.Serial(port, baud, timeout=0.5)
                test_ser.close()
            except Exception as e:
                messagebox.showerror(
                    "串口连接失败",
                    f"无法打开串口 {port}：\n{e}\n\n"
                    f"排查建议：\n"
                    f"1. 确认该串口未被上位机或其他软件占用\n"
                    f"2. 确认设备 USB 连线已插紧并被系统识别\n"
                    f"3. 点击【刷新】重新获取最新端口列表"
                )
                return

            v_lsb_str = self.v_lsb_entry.get().strip()
            try:
                self.v_lsb = int(v_lsb_str)
            except ValueError:
                messagebox.showerror("错误", "V_LSB_NV 必须是有效的整数！")
                return
                
            self.selected_port_name = port
            self.selected_baud_val = baud
            self.raw_samples = []
            self.is_recording = True
            self.btn_record.config(text="停止录制 并 调参")
            self.status_label.config(text="正在全量录制中，请缓慢旋动电压源并切档...", foreground="red")
            self.set_sliders_state("disabled")
            
            # 开启后台接收线程
            self.recv_thread = threading.Thread(target=self.serial_reader, daemon=True)
            self.recv_thread.start()
            
            # 开启 GUI 刷新定时器 (100ms = 0.1s 刷新一次)
            self.root.after(100, self.update_gui_status)
        else:
            # 停止录制
            self.is_recording = False
            self.btn_record.config(text="开始录制数据")
            self.status_label.config(text="正在进行数据归一化平均与预平滑，请稍候...", foreground="orange")
            self.lbl_gear_val.config(text="录制已停止", foreground="gray")
            self.root.update()
            
            # 关闭串口
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                
            self.process_raw_data()

    def serial_reader(self):
        port = getattr(self, 'selected_port_name', DEFAULT_PORT)
        baud = getattr(self, 'selected_baud_val', DEFAULT_BAUD)
        
        try:
            self.serial_port = serial.Serial(port, baud, timeout=0.5)
            self.serial_port.reset_input_buffer()
            self.serial_port.read_until(TAIL)
            
            current_m = None
            ignore_until = 0.0
            
            while self.is_recording:
                if self.serial_port.in_waiting >= 16:
                    chunk = self.serial_port.read_until(TAIL)
                    if len(chunk) == 16:
                        try:
                            v_r, s_r, m_float = struct.unpack('<fff', chunk[:12])
                            m_val = int(m_float)
                            now = time.time()
                            
                            # 保存最新数据，供 GUI 实时显示
                            self.latest_v_r = v_r
                            self.latest_s_r = s_r
                            self.latest_m = m_val
                            
                            if current_m is not None and m_val != current_m:
                                ignore_until = now + 1.0
                            current_m = m_val
                            
                            if now < ignore_until:
                                continue
                                
                            self.raw_samples.append((v_r, s_r, m_val))
                        except Exception:
                            pass
                else:
                    time.sleep(0.002)
        except Exception as e:
            self.is_recording = False
            self.root.after(0, lambda: self.btn_record.config(text="开始录制数据"))
            self.root.after(0, lambda: self.status_label.config(text=f"录制异常中断: {e}", foreground="red"))
            self.root.after(0, lambda: messagebox.showerror("串口断开", f"录制中断: {e}"))

    def update_gui_status(self):
        """GUI 定时刷新函数 (每 0.1 秒触发一次)"""
        if self.is_recording:
            # 1. 电压换算计算
            v_mv = (self.latest_v_r * self.v_lsb) / 1000000.0
            v_v = v_mv / 1000.0
            self.lbl_v_val.config(text=f"{v_v:.3f} V ({v_mv:.0f} mV)")

            # 2. 原始电流 RAW 值
            self.lbl_raw_val.config(text=f"{self.latest_s_r:.2f}")

            # 3. 电流占用满量程百分比 (INA226 16-bit 采样，满量程为 ±32768 LSB)
            pct = (abs(self.latest_s_r) / 32768.0) * 100.0
            self.lbl_pct_val.config(text=f"{pct:.2f} %")

            # 4. 当前档位
            gear_map = {0: "10mR 档 (0)", 1: "100R 档 (1)"}
            gear_str = gear_map.get(self.latest_m, f"档位 {self.latest_m}")
            self.lbl_gear_val.config(text=gear_str, foreground="#2B6CB0")

            # 更新录制进度提示
            self.status_label.config(text=f"正在录制：累计已捕获 {len(self.raw_samples)} 帧数据...", foreground="red")
            
            # 定时 100ms (0.1 秒) 后再次执行
            self.root.after(100, self.update_gui_status)

    def process_raw_data(self):
        if not self.raw_samples:
            self.status_label.config(text="未捕获到任何有效数据，已恢复。", foreground="blue")
            return
            
        self.bucket_maps = {0: {}, 1: {}}
        for v_r, s_r, m in self.raw_samples:
            v_mv = int((v_r * self.v_lsb) / 1000000)
            v_bucket = (v_mv // 100) * 100
            if v_bucket not in self.bucket_maps[m]: 
                self.bucket_maps[m][v_bucket] = [0.0, 0]
            self.bucket_maps[m][v_bucket][0] += s_r
            self.bucket_maps[m][v_bucket][1] += 1

        self.smoothed_points = {0: [], 1: []}
        self.raw_points_map = {0: [], 1: []}
        
        for m in [0, 1]:
            data = self.bucket_maps[m]
            if not data: continue
            
            v_keys = sorted(data.keys())
            raw_points = [(v, data[v][0]/data[v][1]) for v in v_keys]
            self.raw_points_map[m] = raw_points
            
            smoothed = []
            win = 3
            for i in range(len(raw_points)):
                subset = [p[1] for p in raw_points[max(0, i-win):min(len(raw_points), i+win+1)]]
                smoothed.append((raw_points[i][0], sum(subset)/len(subset)))
            self.smoothed_points[m] = smoothed
            
        self.set_sliders_state("normal")
        self.recalculate()

    def on_slider_changed(self, event):
        """滑块值发生变化时的实时响应"""
        if (self.slider_10mr is None or self.slider_100r is None or 
            self.code_txt is None or self.status_label is None):
            return

        if self.captured_data_empty():
            return
            
        eps_10mr = float(self.slider_10mr.get())
        eps_100r = float(self.slider_100r.get())
        
        self.eps_10mr_val_label.config(text=f"{eps_10mr:.2f}")
        self.eps_100r_val_label.config(text=f"{eps_100r:.2f}")
        
        self.generate_and_render_c_code(eps_10mr, eps_100r)

    def recalculate(self):
        self.on_slider_changed(None)

    def captured_data_empty(self):
        return not self.smoothed_points[0] and not self.smoothed_points[1]

    def generate_and_render_c_code(self, eps_10mr, eps_100r):
        code_output = ""
        summary_lines = []
        
        for m in [0, 1]:
            name = "table_10mr" if m == 0 else "table_100r"
            eps = eps_10mr if m == 0 else eps_100r
            smoothed = self.smoothed_points[m]
            raw_points = self.raw_points_map[m]
            
            if not smoothed: 
                continue
            
            # 1. 运行 RDP 算法压缩
            indices = rdp_simplify_to_indices(smoothed, eps)
            final_points = [raw_points[i] for i in indices]

            # 2. 水平冗余合并
            perfect_points = [final_points[0]]
            for i in range(1, len(final_points)-1):
                prev_val = int(round(perfect_points[-1][1] * 256))
                curr_val = int(round(final_points[i][1] * 256))
                next_val = int(round(final_points[i+1][1] * 256))
                if curr_val == prev_val == next_val:
                    continue
                perfect_points.append(final_points[i])
            perfect_points.append(final_points[-1])

            # 3. 异常坏包拦截过滤 (仅针对 10mR)
            if m == 0: 
                perfect_points = [p for p in perfect_points if p[1] < 25]

            # 4. 生成 C 语言代码结构体
            summary_lines.append(f"// 校准表({name}): {len(raw_points)} 桶 -> 压缩后为 {len(perfect_points)} 关键点 (Epsilon={eps:.2f})")
            
            code_output += f"const CalPoint_t {name}[] = {{\n"
            for p in perfect_points:
                offset_q8 = int(round(p[1] * 256))
                code_output += f"    {{{int(p[0]):5d}, {offset_q8:5d}}}, // {p[0]/1000:.1f}V (实际：{p[1]:.2f} LSB)\n"
            code_output += f"}};\n"
            code_output += f"#define {name.upper()}_SIZE {len(perfect_points)}\n\n"

        final_report = "/*\n" + "\n".join(summary_lines) + "\n*/\n\n" + code_output
        
        self.code_txt.delete('1.0', tk.END)
        self.code_txt.insert(tk.END, final_report)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = RDPCompressorGUI()
    app.run()
