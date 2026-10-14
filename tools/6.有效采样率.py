# -*- coding: utf-8 -*-
"""
模块名称: 6.有效采样率
版本号: V26.10.13
"""
__version__ = "V26.10.13"

import serial
import serial.tools.list_ports
import struct
import time
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# --- 配置 ---
DEFAULT_PORT = "COM5"
DEFAULT_BAUD = 1500000
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


class SamplingRateAnalyzerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("低功耗分析仪 - 有效采样率与吞吐效率分析仪 V1.0")
        self.root.geometry("700x560")
        self.root.minsize(640, 500)
        
        self.is_sampling = False
        
        self.create_widgets()

    def create_widgets(self):
        # 1. 顶部控制栏
        top_frame = ttk.LabelFrame(self.root, text=" 1. 硬件连接与采样配置 ", padding="12")
        top_frame.pack(fill=tk.X, padx=15, pady=10)

        # 串口
        ttk.Label(top_frame, text="串口号:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.port_list = get_available_ports()
        self.port_combo = ttk.Combobox(top_frame, values=self.port_list, width=26)
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        else:
            self.port_combo.set(DEFAULT_PORT)
        self.port_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        self.btn_refresh = ttk.Button(top_frame, text="刷新", width=5, command=self.refresh_ports)
        self.btn_refresh.grid(row=0, column=2, padx=(0, 10), pady=5)

        # 波特率
        ttk.Label(top_frame, text="波特率:").grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)
        self.baud_combo = ttk.Combobox(top_frame, values=["1500000", "2000000", "1000000", "921600", "460800", "115200"], width=10)
        self.baud_combo.set(str(DEFAULT_BAUD))
        self.baud_combo.grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)

        # 采样时长
        ttk.Label(top_frame, text="采样时长:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.duration_combo = ttk.Combobox(top_frame, values=["3 秒", "5 秒", "10 秒"], width=10, state="readonly")
        self.duration_combo.current(1)  # 默认 5 秒
        self.duration_combo.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        # 操作按钮
        self.btn_start = ttk.Button(top_frame, text="开始采样与分析", command=self.start_analysis)
        self.btn_start.grid(row=1, column=3, columnspan=2, padx=5, pady=5, sticky=tk.EW)

        # 2. 状态与进度指示
        status_frame = ttk.Frame(self.root, padding="5")
        status_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.status_label = ttk.Label(status_frame, text="状态: 待机中。请选择串口后点击【开始采样与分析】...", foreground="blue", font=("Arial", 10))
        self.status_label.pack(side=tk.LEFT, pady=2)

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill=tk.X, padx=15, pady=(0, 10))

        # 3. 分析报告展示区
        report_frame = ttk.LabelFrame(self.root, text=" 2. 采样效率分析报告与 MCU 调优建议 ", padding="12")
        report_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        self.txt_report = tk.Text(report_frame, bg="#F4F5F7", font=("Consolas", 11), bd=0, padx=10, pady=10)
        self.txt_report.pack(fill=tk.BOTH, expand=True)
        self.txt_report.insert(tk.END, "等待启动测试...\n\n点击【开始采样与分析】后，系统将进行高频连续数据录制，并分析真实物理有效帧率与丢帧/重复率。")
        self.txt_report.config(state=tk.DISABLED)

    def refresh_ports(self):
        self.port_list = get_available_ports()
        self.port_combo['values'] = self.port_list
        if self.port_list and "无可用串口" not in self.port_list[0]:
            self.port_combo.current(0)
        messagebox.showinfo("刷新成功", f"扫描到 {len(self.port_list)} 个串口设备！")

    def start_analysis(self):
        if self.is_sampling:
            return

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

        dur_text = self.duration_combo.get()
        dur_match = re.search(r"\d+", dur_text)
        duration_sec = float(dur_match.group()) if dur_match else 5.0

        # 预测试串口能否打开
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
            return

        self.is_sampling = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_refresh.config(state=tk.DISABLED)
        self.status_label.config(text=f"正在录制数据 ({port} @ {baud}bps, 预计需 {duration_sec:.0f} 秒)...", foreground="red")
        self.progress['value'] = 0

        # 启动后台工作线程
        t = threading.Thread(target=self._worker_sampling, args=(port, baud, duration_sec), daemon=True)
        t.start()

    def _worker_sampling(self, port, baud, duration_sec):
        try:
            ser = serial.Serial(port, baud, timeout=1)
            ser.flushInput()

            raw_buf = bytearray()
            samples = []  # 格式: (时间戳, V_val, int(I_val))
            start_time = time.time()

            while True:
                elapsed = time.time() - start_time
                if elapsed >= duration_sec:
                    break

                # 更新进度条
                progress_pct = min(100.0, (elapsed / duration_sec) * 100.0)
                self.root.after(0, lambda p=progress_pct: self._update_progress(p))

                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    raw_buf.extend(data)

                    # 寻找 12 字节包 [float V][float I][00 00 80 7F]
                    while len(raw_buf) >= 12:
                        idx = raw_buf.find(TAIL)
                        if idx == 8:
                            try:
                                v_val, i_val = struct.unpack('<ff', raw_buf[0:8])
                                samples.append((time.time(), v_val, int(i_val)))
                            except Exception:
                                pass
                            del raw_buf[:12]
                        elif idx != -1:
                            del raw_buf[:idx + 4]
                        else:
                            if len(raw_buf) > 64:
                                del raw_buf[:-4]
                            break
                else:
                    time.sleep(0.001)

            ser.close()

            # 采样完成，进行数据分析
            self.root.after(0, lambda: self._process_results(samples, duration_sec))

        except Exception as e:
            self.root.after(0, lambda err=str(e): self._handle_error(err))

    def _update_progress(self, val):
        self.progress['value'] = val

    def _handle_error(self, err_msg):
        self.is_sampling = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_refresh.config(state=tk.NORMAL)
        self.progress['value'] = 0
        self.status_label.config(text="状态: 采样过程中发生异常", foreground="red")
        messagebox.showerror("采集异常", f"采样过程中出现错误：\n{err_msg}")

    def _process_results(self, samples, expected_duration):
        self.is_sampling = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_refresh.config(state=tk.NORMAL)
        self.progress['value'] = 100

        if len(samples) < 2:
            self.status_label.config(text="状态: 收到数据不足", foreground="red")
            messagebox.showerror("数据不足", "收到的有效数据包太少，无法进行采样率与效率分析。\n请检查分析仪是否处于工作状态并正常输出数据包。")
            return

        total_frames = len(samples)
        duration = samples[-1][0] - samples[0][0]
        if duration <= 0:
            duration = expected_duration
            
        raw_freq = total_frames / duration

        unique_i_samples = 0
        intervals = []

        for i in range(1, len(samples)):
            t_curr, v_curr, i_curr = samples[i]
            t_prev, v_prev, i_prev = samples[i - 1]

            intervals.append((t_curr - t_prev) * 1000000)

            # 判定电流值是否发生了变化（判断是否为新一次物理采样）
            if i_curr != i_prev:
                unique_i_samples += 1

        eff_freq = unique_i_samples / duration if duration > 0 else 0
        avg_interval_us = sum(intervals) / len(intervals) if intervals else 0
        dup_pct = ((total_frames - unique_i_samples) / total_frames) * 100.0 if total_frames > 0 else 0

        self.status_label.config(
            text=f"状态: 分析完成！总包数: {total_frames}，物理有效帧率: {eff_freq:.1f} Hz",
            foreground="green"
        )

        # 构建报告
        report = []
        report.append("=" * 60)
        report.append("          【低功耗分析仪采样效率与吞吐分析报告】")
        report.append("=" * 60)
        report.append(f" 1. 采集总耗时:          {duration:.2f} 秒")
        report.append(f" 2. 接收有效数据包:      {total_frames} 包")
        report.append(f" 3. 串口总帧率 (Raw):    {raw_freq:.2f} Hz")
        report.append(f" 4. 帧平均间隔 (Time):   {avg_interval_us:.1f} us")
        report.append(f" 5. 物理有效帧率 (Eff):  {eff_freq:.2f} Hz")
        report.append(f" 6. 数据重复率:          {dup_pct:.2f}%")
        report.append("-" * 60)

        if raw_freq > eff_freq * 1.1 and eff_freq > 0:
            ratio = total_frames / unique_i_samples if unique_i_samples > 0 else 1.0
            suggested_us = int(1000000 / eff_freq)
            report.append("【诊断结论】:")
            report.append(f" -> MCU 串口发送速率 ({raw_freq:.0f} Hz) 明显高于 ADC 物理刷新率 ({eff_freq:.0f} Hz)。")
            report.append(f" -> 这意味着每发送约 {ratio:.1f} 包数据，其中仅有 1 包是真正的新数据。")
            report.append(f" -> 建议调优措施：将 MCU 固件中的 App_Measure_Update 发送限速为: {suggested_us} us。")
        else:
            report.append("【诊断结论】:")
            report.append(" -> MCU 串口发送与 ADC 硬件更新基本同步，效率极高，无冗余开销！")

        report.append("=" * 60)

        report_text = "\n".join(report)

        self.txt_report.config(state=tk.NORMAL)
        self.txt_report.delete("1.0", tk.END)
        self.txt_report.insert(tk.END, report_text)
        self.txt_report.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = SamplingRateAnalyzerGUI()
    app.run()
