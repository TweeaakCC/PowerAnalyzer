# -*- coding: utf-8 -*-
"""
模块名称: 4.精度测试与预测
版本号: V26.10.13
"""
__version__ = "V26.10.13"

import serial
import serial.tools.list_ports
import struct
import time
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
import re

# 使用 Matplotlib 进行绘图并嵌入 Tkinter
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# --- 硬件默认配置 ---
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


class NoiseAnalyzerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("INA226 物理噪声衰减与信噪比推演分析仪 V1.0")
        self.root.geometry("960x560")
        
        self.captured_data = None  # 存放采集到的原始 LSB 数组
        self.raw_std = 3.0         # 预设默认标准差
        
        self.create_widgets()

    def create_widgets(self):
        # 1. 顶部控制栏
        top_frame = ttk.LabelFrame(self.root, text=" 1. 硬件连接与噪声采样 (采样5秒) ", padding="10")
        top_frame.pack(fill=tk.X, padx=15, pady=10)
        
        ttk.Label(top_frame, text="串口号:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.port_list = get_available_ports()
        self.port_combo = ttk.Combobox(top_frame, values=self.port_list, width=28)
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        else:
            self.port_combo.set(DEFAULT_PORT)
        self.port_combo.grid(row=0, column=1, padx=5, sticky=tk.W)
        
        self.btn_refresh = ttk.Button(top_frame, text="刷新", width=5, command=self.refresh_ports)
        self.btn_refresh.grid(row=0, column=2, padx=(0, 10))
        
        ttk.Label(top_frame, text="波特率:").grid(row=0, column=3, padx=5, sticky=tk.W)
        self.baud_combo = ttk.Combobox(top_frame, values=["2000000", "1000000", "921600", "460800", "115200"], width=12)
        self.baud_combo.set(str(DEFAULT_BAUD))
        self.baud_combo.grid(row=0, column=4, padx=5, sticky=tk.W)
        
        self.btn_sample = ttk.Button(top_frame, text="开始实时采样并分析", command=self.run_sampling)
        self.btn_sample.grid(row=0, column=5, padx=15)
        
        self.status_label = ttk.Label(top_frame, text="状态: 待机中。请选择串口开始采样...", foreground="blue")
        self.status_label.grid(row=0, column=6, padx=5, sticky=tk.W)

        # 2. 中部主体布局：左侧参数输入/推演，右侧图表显示
        main_pane = ttk.Frame(self.root)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        # 左侧面板
        left_frame = ttk.LabelFrame(main_pane, text=" 2. 分辨率推演计算器 ", padding="10", width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))
        left_frame.pack_propagate(False) # 强行锁定宽度
        
        # 参数输入
        ttk.Label(left_frame, text="目标检测微小电流 (uA):").pack(anchor=tk.W, pady=2)
        self.current_entry = ttk.Entry(left_frame, justify="center")
        self.current_entry.insert(0, "0.1")
        self.current_entry.pack(fill=tk.X, pady=4)
        
        ttk.Label(left_frame, text="分流电阻阻值 (R):").pack(anchor=tk.W, pady=2)
        self.res_entry = ttk.Entry(left_frame, justify="center")
        self.res_entry.insert(0, "5")
        self.res_entry.pack(fill=tk.X, pady=4)
        
        ttk.Label(left_frame, text="期望信噪比 SNR 门槛 (推荐3.0):").pack(anchor=tk.W, pady=2)
        self.snr_entry = ttk.Entry(left_frame, justify="center")
        self.snr_entry.insert(0, "3.0")
        self.snr_entry.pack(fill=tk.X, pady=4)
        
        ttk.Button(left_frame, text="一键运行推演", command=self.calculate_resolution).pack(fill=tk.X, pady=10)
        
        # 计算结果展示区
        ttk.Separator(left_frame, orient='horizontal').pack(fill='x', pady=5)
        self.results_txt = tk.Text(left_frame, bg="#F0F0F0", font=("Consolas", 10), bd=0)
        self.results_txt.pack(fill=tk.BOTH, expand=True, pady=5)
        self.results_txt.insert(tk.END, "等待采样或计算...")
        self.results_txt.config(state=tk.DISABLED)

        # 右侧图表区
        right_frame = ttk.LabelFrame(main_pane, text=" 3. 噪声实际衰减率 vs 物理极限衰减率 (Allan 方差简易版) ")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 初始化 Matplotlib 图像
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Averaging Window Size (k)")
        self.ax.set_ylabel("Noise Standard Deviation (LSB)")
        self.ax.grid(True, which="both", ls="--")
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=right_frame)
        # ！！！此处已修正：将 padding=5 替换为标准的 padx=5, pady=5 ！！！
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def refresh_ports(self):
        self.port_list = get_available_ports()
        self.port_combo['values'] = self.port_list
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        messagebox.showinfo("刷新成功", f"扫描到 {len(self.port_list)} 个串口设备！")

    def run_sampling(self):
        """
        开始 5 秒的高频噪声采样，并计算真实的噪声衰减
        """
        raw_port = self.port_combo.get().strip()
        if not raw_port or "无可用串口" in raw_port:
            messagebox.showerror("串口错误", "请先选择或输入有效的串口号（例如 COM3, COM16）！")
            return
            
        match = re.search(r"(COM\d+)", raw_port, re.IGNORECASE)
        port = match.group(1).upper() if match else raw_port.split(":")[0].strip()
        
        raw_baud = self.baud_combo.get().strip()
        try:
            baud = int(raw_baud)
        except ValueError:
            baud = DEFAULT_BAUD
        
        self.status_label.config(text=f"正在连接 {port} 并采集 5 秒数据，请保持负载稳定...", foreground="red")
        self.root.update()
        
        samples = []
        try:
            ser = serial.Serial(port, baud, timeout=1)
            ser.read_until(TAIL) # 同步头
            
            start_time = time.time()
            while time.time() - start_time < 5.0:
                chunk = ser.read_until(TAIL)
                if len(chunk) == 16:
                    _, s_raw, _ = struct.unpack('<fff', chunk[:12])
                    samples.append(s_raw)
            ser.close()
            
            if not samples:
                messagebox.showerror("错误", "未接收到任何串口信号，请检查主控板运行状态。")
                self.status_label.config(text="状态: 接收数据空", foreground="red")
                return
                
            self.captured_data = np.array(samples)
            self.raw_std = np.std(self.captured_data)
            self.status_label.config(text=f"采集完成！总采样数: {len(self.captured_data)}。原始噪声: {self.raw_std:.3f} LSB", foreground="green")
            
            # 刷新图表
            self.update_decay_plot()
            # 运行分辨率推演
            self.calculate_resolution()
            
        except Exception as e:
            messagebox.showerror(
                "串口连接失败",
                f"无法打开串口 {port}：\n{e}\n\n"
                f"排查建议：\n"
                f"1. 确认该串口未被上位机或其他软件占用\n"
                f"2. 确认分析仪 USB 线已插紧并被系统识别\n"
                f"3. 点击【刷新】重新获取最新端口列表"
            )
            self.status_label.config(text="状态: 串口异常", foreground="red")

    def update_decay_plot(self):
        """
        绘制【理论白噪声衰减】与【您当前器件的真实衰减】双曲线对比
        """
        if self.captured_data is None:
            return
            
        self.ax.clear()
        
        # 窗口大小列表 (k值)
        window_sizes = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
        
        # 计算理论衰减 (Gaussian White Noise: Std / sqrt(k))
        theory_stds = [self.raw_std / np.sqrt(k) for k in window_sizes]
        
        # 计算实测衰减 (将连续的数据分成块进行求均值，计算均值后的标准差)
        actual_stds = []
        data_len = len(self.captured_data)
        for k in window_sizes:
            if k == 1:
                actual_stds.append(self.raw_std)
            else:
                # 剔除余数，切分成多组
                truncated_len = data_len - (data_len % k)
                reshaped = self.captured_data[:truncated_len].reshape(-1, k)
                chunk_means = np.mean(reshaped, axis=1)
                actual_stds.append(np.std(chunk_means))
                
        # 绘图
        # 理论曲线（蓝色虚线，物理极致）
        self.ax.plot(window_sizes, theory_stds, 'o--', color='#1f77b4', label='Theoretical Limit (White Noise)')
        # 实测曲线（红色实线，真实电路表现）
        self.ax.plot(window_sizes, actual_stds, 's-', color='#d62728', label='Actual Hardware Performance')
        
        self.ax.set_xscale('log', base=2)
        self.ax.set_xlabel("Averaging Count (k)", fontsize=10)
        self.ax.set_ylabel("Noise Standard Deviation (LSB)", fontsize=10)
        self.ax.set_title("Noise Decay Curve: Theory vs Reality", fontsize=11, fontweight="bold")
        self.ax.grid(True, which="both", ls="--", alpha=0.5)
        self.ax.legend(loc="upper right")
        
        self.canvas.draw()
        
        # 返回实测数据列表供推演使用
        self.window_sizes = window_sizes
        self.actual_stds = dict(zip(window_sizes, actual_stds))

    def calculate_resolution(self):
        """
        核心物理推演：计算想要分出目标微小电流，理论和现实中各需要多少次平均
        """
        try:
            target_i_ua = float(self.current_entry.get().strip())
            shunt_r = float(self.res_entry.get().strip())
            target_snr = float(self.snr_entry.get().strip())
        except ValueError:
            messagebox.showerror("错误", "参数输入有误，请输入合理的数值。")
            return
            
        # 1. 换算信号强度 (LSB)
        # INA226 步进为 2.5uV
        sig_v = (target_i_ua * 1e-6) * shunt_r
        sig_lsb = sig_v / 2.5e-6
        
        # 2. 目标最高容许的标准差
        max_allow_noise_std = sig_lsb / target_snr
        
        # 3. 理论上所需的平均次数 k_theory
        k_theory = (self.raw_std / max_allow_noise_std) ** 2 if max_allow_noise_std > 0 else float('inf')
        
        # 4. 实测所需的平均次数 k_actual
        k_actual_str = "无法探测 (噪声底限制)"
        if self.captured_data is not None and hasattr(self, 'actual_stds'):
            found = False
            for k in self.window_sizes:
                if self.actual_stds[k] <= max_allow_noise_std:
                    k_actual_str = f"{k} 次平均"
                    found = True
                    break
            if not found:
                if self.actual_stds[1024] > max_allow_noise_std:
                    k_actual_str = "无法探测 (已达运放/电源噪声底)"
                else:
                    k_actual_str = "> 1024 次平均"
        else:
            k_actual_str = "等待数据采样..."

        # 5. 更新文本区
        self.results_txt.config(state=tk.NORMAL)
        self.results_txt.delete('1.0', tk.END)
        
        report = (
            f"=== 物理分辨率推演报告 ===\n"
            f"目标电流:  {target_i_ua:.3f} uA\n"
            f"分流电阻:  {shunt_r:.2f} R\n"
            f"产生分流电压: {sig_v*1e6:.3f} uV\n"
            f"相当于信号强: {sig_lsb:.4f} LSB\n"
            f"期望信噪比:  {target_snr:.1f}\n"
            f"--------------------------\n"
            f"容许最大噪声波动:\n"
            f" -> {max_allow_noise_std:.4f} LSB\n"
            f"--------------------------\n"
            f"【完美高斯白噪声预估】:\n"
            f" -> 理论需平均: {int(np.ceil(k_theory))} 次\n\n"
            f"【基于您当前的硬件实测】:\n"
            f" -> 实际需平均: {k_actual_str}\n"
        )
        
        if sig_lsb < 1.0:
            report += "\n[注] 目标低于 1 LSB，需要依赖系统原生的抖动（Dither）进行亚分辨率探测。"
            
        if self.captured_data is not None and hasattr(self, 'actual_stds'):
            ratio = self.actual_stds[1024] / self.raw_std
            if ratio > 0.15:
                report += "\n\n[!!! 警告 !!!]\n实测衰减曲线变平。说明系统有明显的1/f低频闪烁噪声、温漂或电源纹波。单纯堆叠平均次数已经无法继续提升分辨率！"
                
        self.results_txt.insert(tk.END, report)
        self.results_txt.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = NoiseAnalyzerGUI()
    app.run()
