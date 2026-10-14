# -*- coding: utf-8 -*-
"""
模块名称: 7.上位机
版本号: V26.10.14
"""
__version__ = "V26.10.14"

import sys
import os
import time
import datetime
import struct
import gzip  # 实时无损高压缩率保存
import json  # 全自动本地配置记忆
import numpy as np
import pandas as pd  # 高速导入 CSV 及 CSV.GZ 数据
import serial
import serial.tools.list_ports
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

# ==========================================
# 高 DPI 适配与 Numpy 兼容处理
# ==========================================
# 清理冲突的环境变量，避免二次缩放
os.environ.pop("QT_AUTO_SCREEN_SCALE_FACTOR", None)

# 启用 Qt 原生高 DPI 适配及浮点直通策略 (彻底解决 150%、225% 等非整数缩放四舍五入导致的像素压缩与偏移)
if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
if hasattr(QtGui.QGuiApplication, 'setHighDpiScaleFactorRoundingPolicy'):
    QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

if hasattr(np, 'trapezoid'):
    np_trapz = np.trapezoid
else:
    np_trapz = np.trapz

TAIL = b'\x00\x00\x80\x7F'

# ==========================================
# 动态单位换挡格式化函数
# ==========================================
def format_voltage(v):
    abs_v = abs(v)
    if abs_v < 1.0: return f"{v * 1000.0:.3f} mV"
    return f"{v:.4f} V"

def format_current(i_amp):
    abs_i = abs(i_amp)
    if abs_i < 1e-6:   return f"{i_amp * 1e9:.2f} nA"
    elif abs_i < 1e-3: return f"{i_amp * 1e6:.2f} µA"
    elif abs_i < 1.0:  return f"{i_amp * 1e3:.3f} mA"
    else:              return f"{i_amp:.4f} A"

def format_power(p_watt):
    abs_p = abs(p_watt)
    if abs_p < 1e-6:   return f"{p_watt * 1e9:.2f} nW"
    elif abs_p < 1e-3: return f"{p_watt * 1e6:.2f} µW"
    elif abs_p < 1.0:  return f"{p_watt * 1e3:.3f} mW"
    else:              return f"{p_watt:.4f} W"

def format_capacity(ah):
    abs_val = abs(ah)
    if abs_val < 1e-6:   return f"{ah * 1e9:.3f} nAh"
    elif abs_val < 1e-3: return f"{ah * 1e6:.3f} µAh"
    elif abs_val < 1.0:  return f"{ah * 1000.0:.4f} mAh"
    else:                return f"{ah:.4f} Ah"

def format_energy(wh):
    abs_val = abs(wh)
    if abs_val < 1e-6:   return f"{wh * 1e9:.3f} nWh"
    elif abs_val < 1e-3: return f"{wh * 1e6:.3f} µWh"
    elif abs_val < 1.0:  return f"{wh * 1000.0:.4f} mWh"
    else:                return f"{wh:.4f} Wh"


def format_lifetime_hours(hours):
    """电池寿命格式化：输入小时数，输出易读的 年/天/小时/分钟/秒"""
    if hours != hours or hours in (float('inf'), float('-inf')) or hours < 0:
        return "--"
    if hours < 1.0 / 60.0:
        return f"{hours * 3600.0:.0f} 秒"
    if hours < 1.0:
        return f"{hours * 60.0:.1f} 分钟"
    if hours < 24.0:
        return f"{hours:.2f} 小时"
    days = int(hours / 24.0)
    rem_hours = hours - days * 24.0
    if days < 365:
        return f"{days} 天 {rem_hours:.1f} 小时"
    
    # 超过 1 年：明确格式化为 "X 年 Y 天 (共 Z 天)"，杜绝 "1.1 年 (37 天)" 让人误以为 1.1年只有37天的误解
    years = int(days // 365.25)
    rem_days = int(days % 365.25)
    if rem_days > 0:
        return f"{years} 年 {rem_days} 天 (共 {days} 天)"
    else:
        return f"{years} 年整 (共 {days} 天)"


def format_human_duration(seconds):
    """人类习惯的时长格式化（年月日时分秒毫秒微秒）"""
    if seconds != seconds or seconds in (float('inf'), float('-inf')) or seconds < 0:
        return "--"
    if seconds < 1e-4:
        return f"{seconds * 1e6:.2f} us"
    if seconds < 1.0:
        return f"{seconds * 1000.0:.2f} ms"
    if seconds < 60.0:
        return f"{seconds:.4f} 秒"
    
    days = int(seconds // 86400)
    rem = seconds % 86400
    hours = int(rem // 3600)
    rem = rem % 3600
    minutes = int(rem // 60)
    sec = rem % 60
    
    if days >= 365:
        years = days // 365
        rem_days = days % 365
        return f"{years}年 {rem_days}天 {hours:02d}时{minutes:02d}分{sec:02.0f}秒"
    if days >= 30:
        months = days // 30
        d = days % 30
        return f"{months}月 {d}天 {hours:02d}时{minutes:02d}分{sec:02.0f}秒"
    if days > 0:
        return f"{days}天 {hours:02d}时{minutes:02d}分{sec:02.0f}秒"
    if hours > 0:
        return f"{hours}小时 {minutes:02d}分{sec:04.1f}秒"
    return f"{minutes}分 {sec:05.2f}秒"


def format_human_time_tick(val, spacing):
    """图表 X 轴时间刻度标签（人类时钟模式：年月日时分秒）"""
    if val < 0:
        sign = "-"
        val = abs(val)
    else:
        sign = ""
        
    # 微小精度预处理，杜绝浮点 59.9999 进位到 60 秒导致的“分:60”显示瑕疵
    if spacing >= 1:
        val = round(val)
    elif spacing >= 0.01:
        val = round(val, 2)
    elif spacing >= 0.001:
        val = round(val, 3)
    else:
        val = round(val, 4)

    days = int(val // 86400)
    rem = val % 86400
    hours = int(rem // 3600)
    rem = rem % 3600
    minutes = int(rem // 60)
    seconds = rem % 60
    
    if days >= 365:
        years = days // 365
        rem_days = days % 365
        if spacing >= 86400:
            return f"{sign}{years}年{rem_days}天"
        return f"{sign}{years}年{rem_days}天{hours:02d}时"
    elif days >= 30:
        months = days // 30
        d = days % 30
        if spacing >= 86400:
            return f"{sign}{months}月{d}天"
        return f"{sign}{months}月{d}天{hours:02d}时"
    elif spacing >= 86400:
        if hours == 0 and minutes == 0:
            return f"{sign}{days}天"
        return f"{sign}{days}天{hours:02d}时"
    elif spacing >= 3600:
        if days > 0:
            return f"{sign}{days}天{hours:02d}:{minutes:02d}"
        return f"{sign}{hours:02d}:{minutes:02d}:{int(seconds):02d}"
    elif spacing >= 60:
        if days > 0:
            return f"{sign}{days}天{hours:02d}:{minutes:02d}"
        if hours > 0:
            return f"{sign}{hours:02d}:{minutes:02d}:{int(seconds):02d}"
        return f"{sign}{minutes:02d}:{int(seconds):02d}"
    elif spacing >= 1:
        if days > 0:
            return f"{sign}{days}天{hours:02d}:{minutes:02d}:{int(seconds):02d}"
        if hours > 0:
            return f"{sign}{hours:02d}:{minutes:02d}:{int(seconds):02d}"
        return f"{sign}{minutes:02d}:{int(seconds):02d}"
    else:
        if spacing >= 0.01:
            sec_str = f"{seconds:05.2f}"
        elif spacing >= 0.001:
            sec_str = f"{seconds:06.3f}"
        else:
            sec_str = f"{seconds:.4f}"
            
        if days > 0:
            return f"{sign}{days}天{hours:02d}:{minutes:02d}:{sec_str}"
        if hours > 0:
            return f"{sign}{hours:02d}:{minutes:02d}:{sec_str}"
        return f"{sign}{minutes:02d}:{sec_str}"


class HumanTimeAxisItem(pg.AxisItem):
    """智能时间轴：支持纯秒制（s, ks, Ms）与人类习惯时钟（年月日时分秒）双模式平滑切换"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_second_clock = False

    def set_second_clock(self, enabled):
        self.use_second_clock = enabled
        if enabled:
            self.enableAutoSIPrefix(True)
        else:
            self.enableAutoSIPrefix(False)
            self.labelUnitPrefix = ''
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        if self.use_second_clock:
            return super().tickStrings(values, scale, spacing)
        return [format_human_time_tick(v, spacing) for v in values]




# ==========================================
# 零间隙、完全物理居中的复选框组件
# ==========================================
class CenteredCheckBox(QtWidgets.QWidget):
    state_changed = QtCore.pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.stateChanged.connect(self.state_changed.emit)
        layout.addWidget(self.checkbox)
        layout.setAlignment(QtCore.Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        
    def isChecked(self):
        return self.checkbox.isChecked()
        
    def setChecked(self, checked):
        self.checkbox.setChecked(checked)


# ==========================================
# 🎯 支持 Excel 级挤压对齐与自动表头的表格组件
# ==========================================
class CopyableTableWidget(QtWidgets.QTableWidget):
    def keyPressEvent(self, event):
        """
        拦截键盘事件，当按下 Ctrl+C 时执行多选复制，自动对齐表头并进行列挤压
        """
        if event.matches(QtGui.QKeySequence.Copy):
            self.copy_selection_to_clipboard()
        else:
            super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        # 1. 提取被选中单元格对应的唯一列号和行号（排序以保持先后关系）
        selected_cols = sorted(list(set(idx.column() for idx in indexes)))
        selected_rows = sorted(list(set(idx.row() for idx in indexes)))

        # 2. 建立选中单元格的坐标映射集合，用于快速匹配
        selected_coords = {(idx.row(), idx.column()) for idx in indexes}

        output_rows = []

        # 3. 自动抓取选中列的表头并挤压拼接 [2]
        headers = []
        for c in selected_cols:
            header_item = self.horizontalHeaderItem(c)
            headers.append(header_item.text() if header_item else f"列 {c}")
        output_rows.append("\t".join(headers))

        # 4. 按行提取数据，仅保留选中列的值进行对齐拼接 [2]
        for r in selected_rows:
            row_data = []
            for c in selected_cols:
                if (r, c) in selected_coords:
                    item = self.item(r, c)
                    if item:
                        text = item.text()
                    else:
                        # 提取复选框小组件的可读状态
                        widget = self.cellWidget(r, c)
                        if widget and hasattr(widget, 'checkbox'):
                            text = "已勾选" if widget.checkbox.isChecked() else "未勾选"
                        else:
                            text = ""
                    row_data.append(text)
                else:
                    # 如果该特定坐标格未被框选（如单格不规则多选），在此列保留空位以维持与表头的上下列对齐 [2]
                    row_data.append("")
            output_rows.append("\t".join(row_data))

        # 5. 写入剪贴板
        clipboard_text = "\n".join(output_rows)
        QtWidgets.QApplication.clipboard().setText(clipboard_text)


# ==========================================
# 大配置对话框 (整合最大/最小峰值双向判定)
# ==========================================
class EventConfigDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, current_configs=None, active_boundary_ma=0.5, gap_tolerance_ms=300):
        super().__init__(parent)
        self.setWindowTitle("通用分析与事件分类配置器")
        self.resize(850, 480)
        if parent:
            self.setStyleSheet(parent.styleSheet())
            
        self.configs = [dict(c) for c in current_configs] if current_configs else []
        self.active_boundary_ma = active_boundary_ma
        self.gap_tolerance_ms = gap_tolerance_ms
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. 全局判定参数配置 (大面板整合)
        global_group = QtWidgets.QGroupBox("全局状态切割参数 (基于原始数据判定)")
        global_group.setStyleSheet("QGroupBox { font-weight: bold; color: #ffa500; border: 1px solid #4a4a5a; padding: 10px; margin-top: 10px; }")
        global_layout = QtWidgets.QHBoxLayout(global_group)
        
        self.spin_boundary = QtWidgets.QDoubleSpinBox()
        self.spin_boundary.setRange(0.01, 10.0)
        self.spin_boundary.setValue(self.active_boundary_ma)
        self.spin_boundary.setSuffix(" mA")
        self.spin_boundary.setDecimals(2)
        
        self.spin_gap = QtWidgets.QSpinBox()
        self.spin_gap.setRange(10, 2000)
        self.spin_gap.setValue(self.gap_tolerance_ms)
        self.spin_gap.setSuffix(" ms")
        self.spin_gap.setSingleStep(50)
        
        global_layout.addWidget(QtWidgets.QLabel("全局唤醒门限:"))
        global_layout.addWidget(self.spin_boundary)
        global_layout.addSpacing(25)
        global_layout.addWidget(QtWidgets.QLabel("广播包合并容差:"))
        global_layout.addWidget(self.spin_gap)
        global_layout.addStretch()
        layout.addWidget(global_group)

        # 2. 已知规则列表
        table_lbl = QtWidgets.QLabel("🎯 已知事件规则分类表 (不符合表内规则的自动判定为‘未知活跃事件’)：")
        table_lbl.setStyleSheet("font-weight: bold; color: #ffffff;")
        layout.addWidget(table_lbl)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["事件名称", "最小时间 (ms)", "最大时间 (ms)", "最小峰值 (mA)", "最大峰值 (mA)", "指示高度 (mA)"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1a1a24; gridline-color: #2d2d3a; color: white; font-size: 11pt; }
            QHeaderView::section { background-color: #2a2a38; color: #00f0ff; border: 1px solid #2d2d3a; padding: 4px; font-size: 11pt; }
            QTableWidget::item:selected { background-color: #3d3d52; }
        """)
        layout.addWidget(self.table)

        self.load_configs_to_table()

        # 按钮栏
        btn_bar = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("添加分类")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_add.setStyleSheet("background-color: #1e3a2f; border: 1px solid #2e5a3f;")
        
        self.btn_del = QtWidgets.QPushButton("删除选中")
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_del.setStyleSheet("background-color: #6a1b29; border: 1px solid #8a2b3c;")
        
        self.btn_save = QtWidgets.QPushButton("保存并应用")
        self.btn_save.clicked.connect(self.save_and_accept)
        self.btn_save.setStyleSheet("background-color: #004d61; border: 1px solid #00f0ff; color: #00f0ff;")
        
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)

        btn_bar.addWidget(self.btn_add)
        btn_bar.addWidget(self.btn_del)
        btn_bar.addStretch()
        btn_bar.addWidget(self.btn_cancel)
        btn_bar.addWidget(self.btn_save)
        layout.addLayout(btn_bar)

    def load_configs_to_table(self):
        self.table.setRowCount(0)
        for cfg in self.configs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(cfg["name"]))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{cfg['min_ms']:.1f}"))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{cfg['max_ms']:.1f}"))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(f"{cfg.get('min_peak_ma', 0.0):.2f}"))
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(f"{cfg.get('max_peak_ma', 99.0):.2f}"))
            self.table.setItem(row, 5, QtWidgets.QTableWidgetItem(f"{cfg['level_ma']:.2f}"))

    def add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem("新分类"))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem("0.0"))
        self.table.setItem(row, 2, QtWidgets.QTableWidgetItem("100.0"))
        self.table.setItem(row, 3, QtWidgets.QTableWidgetItem("1.00"))  
        self.table.setItem(row, 4, QtWidgets.QTableWidgetItem("99.00"))  
        self.table.setItem(row, 5, QtWidgets.QTableWidgetItem("2.00"))

    def delete_row(self):
        curr_row = self.table.currentRow()
        if curr_row >= 0:
            self.table.removeRow(curr_row)

    def save_and_accept(self):
        self.active_boundary_ma = self.spin_boundary.value()
        self.gap_tolerance_ms = self.spin_gap.value()

        new_configs = []
        for r in range(self.table.rowCount()):
            item_name = self.table.item(r, 0)
            item_min = self.table.item(r, 1)
            item_max = self.table.item(r, 2)
            item_peak_min = self.table.item(r, 3)
            item_peak_max = self.table.item(r, 4)
            item_lvl = self.table.item(r, 5)

            if item_name and item_min and item_max and item_peak_min and item_peak_max and item_lvl:
                try:
                    new_configs.append({
                        "name": item_name.text().strip(),
                        "min_ms": float(item_min.text()),
                        "max_ms": float(item_max.text()),
                        "min_peak_ma": float(item_peak_min.text()),  
                        "max_peak_ma": float(item_peak_max.text()),  
                        "level_ma": float(item_lvl.text())
                    })
                except ValueError:
                    QtWidgets.QMessageBox.warning(self, "输入格式错误", f"第 {r+1} 参数必须为纯数字！")
                    return
        self.configs = new_configs
        self.accept()


# ==========================================
# 电池预置型号库默认配置 (包含真实物理参数)
# ==========================================
DEFAULT_BATTERY_PRESETS = [
    {
        "name": "CR2032 纽扣电池 (220mAh, 3V直供)",
        "capacity_mah": 220.0,
        "dod_pct": 85.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 0.1
    },
    {
        "name": "CR2450 大纽扣电池 (600mAh, 3V直供)",
        "capacity_mah": 600.0,
        "dod_pct": 85.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 0.1
    },
    {
        "name": "CR1220 微型纽扣 (40mAh, 3V直供)",
        "capacity_mah": 40.0,
        "dod_pct": 80.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 0.1
    },
    {
        "name": "AA 碱性电池×2 (2500mAh, 3V整机)",
        "capacity_mah": 2500.0,
        "dod_pct": 75.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 0.3
    },
    {
        "name": "AAA 碱性电池×2 (1000mAh, 3V整机)",
        "capacity_mah": 1000.0,
        "dod_pct": 75.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 0.3
    },
    {
        "name": "18650 锂电池 (2600mAh, 3.7V整机)",
        "capacity_mah": 2600.0,
        "dod_pct": 85.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 2.0
    },
    {
        "name": "18650降压测1.8V负载 (2600mAh, 185%)",
        "capacity_mah": 2600.0,
        "dod_pct": 85.0,
        "eff_pct": 185.0,
        "self_discharge_pct": 2.0
    },
    {
        "name": "聚合物小锂电 (500mAh, 3.7V整机)",
        "capacity_mah": 500.0,
        "dod_pct": 80.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 2.5
    },
    {
        "name": "ER14250 锂亚电池 (1200mAh, 3.6V整机)",
        "capacity_mah": 1200.0,
        "dod_pct": 90.0,
        "eff_pct": 100.0,
        "self_discharge_pct": 0.08
    }
]


# ==========================================
# 电池预置库配置对话框
# ==========================================
class BatteryConfigDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, current_presets=None):
        super().__init__(parent)
        self.setWindowTitle("🔋 电池预置参数库配置")
        self.resize(820, 480)
        self.setStyleSheet("""
            QDialog {
                background-color: #14141c;
                color: #e0e0e0;
            }
            QLabel {
                color: #e0e0e0;
            }
        """)
            
        self.presets = [dict(p) for p in current_presets] if current_presets else [dict(p) for p in DEFAULT_BATTERY_PRESETS]
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        desc_lbl = QtWidgets.QLabel("🎯 电池预置型号库管理 (可增加、修改或删除常用电池种类，配置将持久化保存)：")
        desc_lbl.setStyleSheet("font-weight: bold; color: #00ff66; font-size: 11pt;")
        layout.addWidget(desc_lbl)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["电池型号/名称", "标称容量 (mAh)", "放电深度 DoD (%)", "转换效率 (%)", "月自放电率 (%/月)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for c in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a24;
                gridline-color: #2d2d3a;
                color: white;
                font-size: 11pt;
                border: 1px solid #333344;
            }
            QHeaderView::section {
                background-color: #222230;
                color: #00ff66;
                border: 1px solid #2d2d3a;
                padding: 6px;
                font-size: 11pt;
                font-weight: bold;
            }
            QTableWidget::item:selected {
                background-color: #3d3d52;
                color: #00f0ff;
            }
        """)
        layout.addWidget(self.table)

        self.load_presets_to_table()

        btn_bar = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("添加电池型号")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_add.setStyleSheet("background-color: #1e3a2f; border: 1px solid #2e5a3f; color: #00ff66;")
        
        self.btn_del = QtWidgets.QPushButton("删除选中")
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_del.setStyleSheet("background-color: #6a1b29; border: 1px solid #8a2b3c; color: #ffffff;")
        
        self.btn_reset = QtWidgets.QPushButton("恢复出厂预置")
        self.btn_reset.clicked.connect(self.reset_to_default)
        self.btn_reset.setStyleSheet("background-color: #2a2a38; border: 1px solid #555566; color: #ffa500;")

        self.btn_save = QtWidgets.QPushButton("保存并应用")
        self.btn_save.clicked.connect(self.save_and_accept)
        self.btn_save.setStyleSheet("background-color: #004d61; border: 1px solid #00f0ff; color: #00f0ff;")
        
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)

        btn_bar.addWidget(self.btn_add)
        btn_bar.addWidget(self.btn_del)
        btn_bar.addWidget(self.btn_reset)
        btn_bar.addStretch()
        btn_bar.addWidget(self.btn_cancel)
        btn_bar.addWidget(self.btn_save)
        layout.addLayout(btn_bar)

    def load_presets_to_table(self):
        self.table.setRowCount(0)
        for p in self.presets:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(p.get("name", "未命名电池"))))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{float(p.get('capacity_mah', 220.0)):.1f}"))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{float(p.get('dod_pct', 85.0)):.1f}"))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(f"{float(p.get('eff_pct', 100.0)):.1f}"))
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(f"{float(p.get('self_discharge_pct', 0.1)):.2f}"))

    def add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem("自定义电池型号"))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem("240.0"))
        self.table.setItem(row, 2, QtWidgets.QTableWidgetItem("85.0"))
        self.table.setItem(row, 3, QtWidgets.QTableWidgetItem("100.0"))
        self.table.setItem(row, 4, QtWidgets.QTableWidgetItem("0.10"))

    def delete_row(self):
        curr_row = self.table.currentRow()
        if curr_row >= 0:
            self.table.removeRow(curr_row)

    def reset_to_default(self):
        self.presets = [dict(p) for p in DEFAULT_BATTERY_PRESETS]
        self.load_presets_to_table()

    def save_and_accept(self):
        new_presets = []
        for r in range(self.table.rowCount()):
            item_name = self.table.item(r, 0)
            item_cap = self.table.item(r, 1)
            item_dod = self.table.item(r, 2)
            item_eff = self.table.item(r, 3)
            item_sd = self.table.item(r, 4)

            if item_name and item_cap and item_dod and item_eff and item_sd:
                try:
                    name_str = item_name.text().strip()
                    if not name_str:
                        name_str = f"电池型号_{r+1}"
                    cap_val = float(item_cap.text())
                    dod_val = float(item_dod.text())
                    eff_val = float(item_eff.text())
                    sd_val = float(item_sd.text())
                    if cap_val <= 0 or dod_val <= 0 or eff_val <= 0 or sd_val < 0:
                        QtWidgets.QMessageBox.warning(self, "参数数值错误", f"第 {r+1} 行容量、DoD和效率必须大于0，自放电率不能为负！")
                        return
                    new_presets.append({
                        "name": name_str,
                        "capacity_mah": cap_val,
                        "dod_pct": dod_val,
                        "eff_pct": eff_val,
                        "self_discharge_pct": sd_val
                    })
                except ValueError:
                    QtWidgets.QMessageBox.warning(self, "输入格式错误", f"第 {r+1} 行参数必须为纯数字！")
                    return
        if not new_presets:
            QtWidgets.QMessageBox.warning(self, "预置库为空", "请至少保留一个电池型号配置！")
            return
        self.presets = new_presets
        self.accept()


# ==========================================
# 升级：带选择保护的自刷串口下拉框
# ==========================================
class AutoRefreshComboBox(QtWidgets.QComboBox):
    def showPopup(self):
        """
        每次下拉展开时动态捕获最新串口，并绝对对齐上次保存或正在连接的串口
        """
        curr_text = self.currentText()
        self.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["未找到串口"]
        self.addItems(ports)
        
        index = self.findText(curr_text)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.addItem(curr_text)
            self.setCurrentText(curr_text)
            
        super().showPopup()


class ROIDragViewBox(pg.ViewBox):
    def __init__(self, main_window, *args, **kwds):
        super().__init__(*args, **kwds)
        self.main_window = main_window
        self.start_x = None

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == QtCore.Qt.LeftButton:
            ev.accept()
            if ev.isStart():
                pos = self.mapSceneToView(ev.buttonDownScenePos())
                self.start_x = pos.x()
                self.main_window.region.blockSignals(True)
                self.main_window.region.setRegion([self.start_x, self.start_x])
                self.main_window.region.blockSignals(False)
                self.main_window.region.show()
                self.main_window.stats_popup.hide()
            elif ev.isFinish():
                self.main_window.stats_popup.show()
                self.main_window.on_region_changed()
            else:
                pos = self.mapSceneToView(ev.scenePos())
                current_x = pos.x()
                self.main_window.region.blockSignals(True)
                self.main_window.region.setRegion([min(self.start_x, current_x), max(self.start_x, current_x)])
                self.main_window.region.blockSignals(False)
        else:
            super().mouseDragEvent(ev, axis)

    def mouseClickEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            ev.accept()
            self.main_window.region.hide()
            self.main_window.stats_popup.hide()
        else:
            super().mouseClickEvent(ev)


class SerialReaderThread(QtCore.QThread):
    data_received = QtCore.pyqtSignal(np.ndarray, np.ndarray)
    error_occurred = QtCore.pyqtSignal(str)

    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = True
        self.v_batch = []
        self.i_batch = []
        self.last_emit_time = time.time()

    def run(self):
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.1)
            ser.flushInput()
        except Exception as e:
            self.error_occurred.emit(f"无法打开串口 {self.port}: {str(e)}")
            return

        raw_buf = bytearray()
        while self.running:
            try:
                if ser.in_waiting:
                    raw_buf.extend(ser.read(ser.in_waiting))

                while len(raw_buf) >= 12:
                    idx = raw_buf.find(TAIL)
                    if idx == 8:
                        try:
                            v, i = struct.unpack('<ff', raw_buf[0:8])
                            v_real = v * 0.001
                            i_real = (i * 0.1) * 1e-6
                            
                            if -5.0 <= v_real <= 36.0 and -1.0 <= i_real <= 10.0:
                                self.v_batch.append(v_real)
                                self.i_batch.append(i_real)
                        except struct.error:
                            pass
                        del raw_buf[:12]
                    elif idx != -1:
                        del raw_buf[:idx + 4]
                    else:
                        if len(raw_buf) > 4:
                            del raw_buf[:-4]
                        break

                now = time.time()
                if now - self.last_emit_time >= 0.030 and len(self.v_batch) > 0:
                    self.data_received.emit(
                        np.array(self.v_batch, dtype=np.float32),
                        np.array(self.i_batch, dtype=np.float32)
                    )
                    self.v_batch.clear()
                    self.i_batch.clear()
                    self.last_emit_time = now
                
                time.sleep(0.001)
            except Exception as e:
                self.error_occurred.emit(f"串口读取错误: {str(e)}")
                break

        if 'ser' in locals() and ser.is_open:
            ser.close()

    def stop(self):
        self.running = False
        self.wait()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("低功耗分析")
        self.resize(1400, 850)
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0d12; }
            QLabel { color: #b0b0bc; font-family: 'Segoe UI', 'Microsoft YaHei'; }
            QPushButton { 
                background-color: #2a2a38; color: white; border: 1px solid #3d3d52; 
                padding: 5px 12px; border-radius: 4px; font-weight: bold; font-size: 11pt;
            }
            QPushButton:hover { background-color: #3a3a4e; }
            QPushButton:pressed { background-color: #1e1e28; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { 
                background-color: #1a1a24; color: #00f0ff; border: 1px solid #2d2d3a; 
                padding: 4px 8px; border-radius: 3px; font-size: 11pt; font-weight: bold;
            }
            QCheckBox { color: #e0e0e0; font-size: 11pt; font-weight: bold; }
        """)

        # 初始化时钟参数
        self.sample_rate = 7092 
        self.dt = 1.0 / self.sample_rate
        self.is_running = False  

        self.max_len = 36000000
        self.is_offline_loaded = False 
        
        self.v_buffer = np.zeros(self.max_len, dtype=np.float32)
        self.i_buffer = np.zeros(self.max_len, dtype=np.float32)
        self.t_buffer = np.zeros(self.max_len, dtype=np.float64)
        
        # 指示线全 NaN 初始化
        self.state_buffer = np.full(self.max_len, np.nan, dtype=np.float32)
        
        self.parsed_events = []      
        self.last_single_event = None  
        self.row_stats = []          # 缓存抽屉表格当前每行的物理原始数据
        
        # 判定保护锁：启动加载时设为 True 阻断任何写盘，加载完毕变 False 激活即时修改保存
        self.is_loading_config = False 
        
        # 去皮基准相关的缓存状态
        self.current_avg_i = 0.0
        self.tare_offset_i = 0.0

        # 默认的切割规则参数（如果本地没有 config.json，则使用此初始值）
        self.active_boundary_ma = 0.5   
        self.gap_tolerance_ms = 300     
        
        # 已知事件规则池
        self.event_configs = [
            {"name": "仅测量未上报", "min_ms": 0.0, "max_ms": 50.0, "min_peak_ma": 5.0, "max_peak_ma": 12.0, "level_ma": 3.0},
            {"name": "测量并广播上报", "min_ms": 500.0, "max_ms": 999999.0, "min_peak_ma": 5.0, "max_peak_ma": 12.0, "level_ma": 6.0}
        ]
        
        # 预置电池库参数
        self.battery_presets = [dict(p) for p in DEFAULT_BATTERY_PRESETS]
        self.is_applying_battery_preset = False
        
        self.ptr = 0  
        self.total_count = 0  
        self.pause_ptr = 0     
        self.csv_file = None   

        self.rt_v_sum = 0.0
        self.rt_i_sum = 0.0
        self.rt_p_sum = 0.0
        self.rt_accum_count = 0

        # 校准模块专用时钟源
        self.start_wall_time = 0.0

        self.t_overview = None
        self.v_overview = None
        self.i_overview = None
        self.s_overview = None  

        # 电池寿命估算缓存（最近一次框选统计）
        self.last_region_duration_s = 0.0
        self.last_region_charge_ah = 0.0
        self.last_region_avg_i = 0.0

        self.serial_thread = None
        self.init_ui()
        
        # 启动时自动载入配置
        self.load_settings()

        # 全载入完毕后再绑定信号监听，彻底根治配置被初始默认值覆盖的死循环
        self.txt_baud.textChanged.connect(self.save_settings)
        self.spin_avg_count.valueChanged.connect(self.save_settings)
        self.spin_min_yrange.valueChanged.connect(self.save_settings)
        self.spin_sample_interval.valueChanged.connect(self.save_settings)
        self.chk_voltage.stateChanged.connect(self.save_settings)
        self.chk_save_csv.stateChanged.connect(self.save_settings)
        self.chk_limit_span.stateChanged.connect(self.save_settings)
        self.chk_second_clock.stateChanged.connect(self.save_settings)
        self.chk_enable_analysis.stateChanged.connect(self.save_settings)
        self.chk_show_current.stateChanged.connect(self.save_settings)
        self.combo_port.currentIndexChanged.connect(self.save_settings)
        self.spin_battery_capacity.valueChanged.connect(self.save_settings)
        self.spin_battery_dod.valueChanged.connect(self.save_settings)
        self.spin_battery_eff.valueChanged.connect(self.save_settings)
        self.spin_battery_self_discharge.valueChanged.connect(self.save_settings)

    def init_ui(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ================= 控制面板（双行高密度布局） =================
        controls_layout = QtWidgets.QVBoxLayout()
        controls_layout.setSpacing(8)

        # 第一行：实时串口连接、物理参数监控、全选
        row1_layout = QtWidgets.QHBoxLayout()
        self.combo_port = AutoRefreshComboBox()
        self.combo_port.setMinimumWidth(100)
        initial_ports = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_port.addItems(initial_ports if initial_ports else ["COM1"])
        
        self.txt_baud = QtWidgets.QLineEdit("1500000")
        self.txt_baud.setMaximumWidth(100)
        
        self.btn_connect = QtWidgets.QPushButton("连接设备")
        self.btn_connect.clicked.connect(self.toggle_connection)
        
        # 暂停/开始刷新按钮，初始置灰
        self.btn_run_pause = QtWidgets.QPushButton("开始刷新")
        self.btn_run_pause.setEnabled(False)
        self.btn_run_pause.clicked.connect(self.toggle_run_pause)
        self.btn_run_pause.setStyleSheet("background-color: #1a1a24; color: #4a4a5a; border: 1px solid #2d2d3a;")
        
        # “全选”按钮
        self.btn_select_all = QtWidgets.QPushButton("全选")
        self.btn_select_all.clicked.connect(self.select_all_data)

        self.chk_voltage = QtWidgets.QCheckBox("显示电压")
        self.chk_save_csv = QtWidgets.QCheckBox("保存 CSV")
        self.chk_limit_span = QtWidgets.QCheckBox("限制显示跨度")
        self.chk_second_clock = QtWidgets.QCheckBox("秒制时钟")
        self.chk_second_clock.setToolTip("开启后强制采用秒制单位(s, ks, Ms)；关闭后采用人类习惯单位(年月日时分秒)")
        self.chk_second_clock.stateChanged.connect(self.toggle_second_clock)

        row1_layout.addWidget(QtWidgets.QLabel("串口:"))
        row1_layout.addWidget(self.combo_port)
        row1_layout.addWidget(QtWidgets.QLabel("波特率:"))
        row1_layout.addWidget(self.txt_baud)
        row1_layout.addWidget(self.btn_connect)
        row1_layout.addWidget(self.btn_run_pause)
        row1_layout.addWidget(self.btn_select_all)  
        row1_layout.addSpacing(15)
        row1_layout.addWidget(self.chk_voltage)
        row1_layout.addSpacing(10)
        row1_layout.addWidget(self.chk_save_csv)
        row1_layout.addSpacing(10)
        row1_layout.addWidget(self.chk_limit_span)
        row1_layout.addSpacing(10)
        row1_layout.addWidget(self.chk_second_clock)
        row1_layout.addStretch()

        self.lbl_real_v = QtWidgets.QLabel("电压: -- V")
        self.lbl_real_i = QtWidgets.QLabel("电流: -- A")
        self.lbl_real_p = QtWidgets.QLabel("功率: -- W")
        self.lbl_real_v.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ff007f; padding-right: 15px;")
        self.lbl_real_i.setStyleSheet("font-size: 14pt; font-weight: bold; color: #00f0ff; padding-right: 15px;")
        self.lbl_real_p.setStyleSheet("font-size: 14pt; font-weight: bold; color: #00ff66;")
        
        row1_layout.addWidget(self.lbl_real_v)
        row1_layout.addWidget(self.lbl_real_i)
        row1_layout.addWidget(self.lbl_real_p)
        controls_layout.addLayout(row1_layout)

        # 第二行：离线数据加载、分析开关与配置按钮等
        row2_layout = QtWidgets.QHBoxLayout()
        self.btn_open_csv = QtWidgets.QPushButton("打开 CSV 文件")
        self.btn_open_csv.clicked.connect(self.open_offline_csv)
        self.btn_open_csv.setStyleSheet("background-color: #1a1a2e; border: 1px solid #00f0ff; color: #00f0ff;")
        
        # 事件分析总开关
        self.chk_enable_analysis = QtWidgets.QCheckBox("启用事件分析")
        self.chk_enable_analysis.setChecked(True)
        self.chk_enable_analysis.stateChanged.connect(self.toggle_analysis)
        self.chk_enable_analysis.setStyleSheet("color: #ffa500; font-weight: bold;")

        # 显示原始电流
        self.chk_show_current = QtWidgets.QCheckBox("显示电流")
        self.chk_show_current.setChecked(True)
        self.chk_show_current.stateChanged.connect(self.toggle_current_curve)
        self.chk_show_current.setStyleSheet("color: #00f0ff; font-weight: bold;")

        self.btn_config = QtWidgets.QPushButton("配置事件类型")
        self.btn_config.clicked.connect(self.open_event_config_dialog)
        self.btn_config.setStyleSheet("background-color: #222230; border: 1px solid #7d7d8e; color: #e0e0e0;")

        self.btn_reanalyze = QtWidgets.QPushButton("重新分析")
        self.btn_reanalyze.clicked.connect(self.reanalyze_offline_data)
        self.btn_reanalyze.setStyleSheet("background-color: #2b2b3e; border: 1px solid #ffa500; color: #ffa500;")

        self.spin_avg_count = QtWidgets.QSpinBox()
        self.spin_avg_count.setRange(1, 1000000)
        self.spin_avg_count.setValue(2000)       
        self.spin_avg_count.setSingleStep(1000)
        self.spin_avg_count.setSuffix(" 次平均")
        self.spin_avg_count.setMinimumWidth(110)

        # 🎯 去皮和清皮按钮 (新增)
        self.btn_tare = QtWidgets.QPushButton("去皮")
        self.btn_tare.clicked.connect(self.apply_tare)
        self.btn_tare.setStyleSheet("background-color: #2b2b3e; border: 1px solid #00f0ff; color: #00f0ff;")
        self.btn_tare.setToolTip("以当前平均电流为基准，将后续测量实时偏移归零")
        
    

        # Y轴最小显示量程限制输入框
        self.spin_min_yrange = QtWidgets.QDoubleSpinBox()
        self.spin_min_yrange.setRange(0.01, 100.0)  
        self.spin_min_yrange.setValue(1.0)           # 默认 1.0 mA 量程下限
        self.spin_min_yrange.setDecimals(2)
        self.spin_min_yrange.setSuffix(" mA 量程限制")
        self.spin_min_yrange.setMinimumWidth(140)
        self.spin_min_yrange.valueChanged.connect(self.update_y_limits)

        # 硬件恒定采样间隔配置输入框 (单位：微秒 us)
        self.spin_sample_interval = QtWidgets.QSpinBox()
        self.spin_sample_interval.setRange(0, 1000000)
        self.spin_sample_interval.setValue(0)
        self.spin_sample_interval.setSuffix(" us 采样间隔")
        self.spin_sample_interval.setMinimumWidth(160)
        self.spin_sample_interval.setToolTip("设置硬件恒定的单包采样间隔(微秒)。输入0表示启用基于时钟的自校准，若输入非0硬件实测值，将严格按恒定步长生成时轴。")
        self.spin_sample_interval.valueChanged.connect(self.update_sample_interval)

        row2_layout.addWidget(self.btn_open_csv)
        row2_layout.addSpacing(15)
        row2_layout.addWidget(self.chk_enable_analysis)
        row2_layout.addSpacing(10)
        row2_layout.addWidget(self.chk_show_current)  
        row2_layout.addSpacing(10)
        row2_layout.addWidget(self.btn_config)         
        row2_layout.addWidget(self.btn_reanalyze)
        row2_layout.addSpacing(15)
        row2_layout.addWidget(QtWidgets.QLabel("实时均值:"))
        row2_layout.addWidget(self.spin_avg_count)
        row2_layout.addSpacing(5)
        row2_layout.addWidget(self.btn_tare)        
        row2_layout.addSpacing(10)
        row2_layout.addWidget(self.spin_min_yrange)  
        row2_layout.addSpacing(10)
        row2_layout.addWidget(self.spin_sample_interval)  
        row2_layout.addStretch()
        controls_layout.addLayout(row2_layout)

        main_layout.addLayout(controls_layout)

        # ================= 图表区 =================
        self.plot_layout = pg.GraphicsLayoutWidget()
        self.plot_layout.setBackground('#0d0d12')
        main_layout.addWidget(self.plot_layout)

        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        self.region.setBrush((0, 240, 255, 45))  
        self.region.hide()
        self.region.sigRegionChangeFinished.connect(self.on_region_changed)

        self.axis_bottom_i = HumanTimeAxisItem(orientation='bottom')
        self.vb_i = ROIDragViewBox(self)
        self.p_i = self.plot_layout.addPlot(row=0, col=0, viewBox=self.vb_i, axisItems={'bottom': self.axis_bottom_i})
        self.p_i.showGrid(x=True, y=True, alpha=0.3)
        self.p_i.setLabel('left', '电流', units='A', color='#00f0ff')
        
        self.curve_i = self.p_i.plot(pen=pg.mkPen('#00f0ff', width=1.0), clipToView=True)
        
        # 指示线 (WebGL加速实线 + connect="finite")
        self.curve_state = self.p_i.plot(
            pen=pg.mkPen(QtGui.QColor(255, 130, 0, 255), width=3.0), 
            clipToView=True,
            connect="finite"
        )
        self.curve_state.hide()

        self.p_i.addItem(self.region)
        
        self.axis_bottom_v = HumanTimeAxisItem(orientation='bottom')
        self.p_v = self.plot_layout.addPlot(row=1, col=0, axisItems={'bottom': self.axis_bottom_v})
        self.p_v.showGrid(x=True, y=True, alpha=0.3)
        self.p_v.setLabel('left', '电压', units='V', color='#ff007f')
        self.curve_v = self.p_v.plot(pen=pg.mkPen('#ff007f', width=1.0), clipToView=True)

        self.p_v.setXLink(self.p_i)
        self.p_i.setDownsampling(auto=False)
        self.p_v.setDownsampling(auto=False)
        self.p_i.getViewBox().setLimits(minXRange=0.0005)
        self.p_v.getViewBox().setLimits(minXRange=0.0005)

        self.p_i.sigXRangeChanged.connect(self.on_x_range_changed)

        self.chk_voltage.stateChanged.connect(self.toggle_voltage_view)
        self.toggle_voltage_view(QtCore.Qt.Unchecked)

        self.chk_save_csv.setChecked(True)  
        self.chk_limit_span.setChecked(True)  
        self.chk_second_clock.setChecked(False)
        self.update_time_axis_labels()  

        # ================= 悬浮分析面板 =================
        self.stats_popup = QtWidgets.QFrame(self.plot_layout)
        self.stats_popup.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 28, 230);
                border-radius: 8px;
                border: 1px solid #4a4a5a;
            }
            QLabel { font-size: 11pt; font-weight: bold; color: #ffffff; background: transparent; border: none; }
        """)
        self.stats_popup.setMinimumWidth(1180) # 进一步微调悬浮窗宽度，自适应12列布局
        
        popup_layout = QtWidgets.QGridLayout(self.stats_popup)
        popup_layout.setContentsMargins(15, 10, 15, 10)
        popup_layout.setSpacing(15) 

        self.lbl_ana_duration = QtWidgets.QLabel("区间时长: --")
        self.lbl_ana_avg_v = QtWidgets.QLabel("平均电压: -- V")
        self.lbl_ana_avg_i = QtWidgets.QLabel("平均电流: -- A")
        self.lbl_ana_avg_p = QtWidgets.QLabel("平均功率: -- W")
        self.lbl_ana_max_i = QtWidgets.QLabel("最大电流: -- A")
        self.lbl_ana_min_i = QtWidgets.QLabel("最小电流: -- A")
        self.lbl_ana_mah = QtWidgets.QLabel("累计电量: -- mAh")
        self.lbl_ana_mwh = QtWidgets.QLabel("累计能量: -- mWh")
        
        self.lbl_ana_event_count = QtWidgets.QLabel("事件统计: --")
        self.lbl_ana_event_count.setStyleSheet("color: #ffa500;")

        self.btn_auto_align = QtWidgets.QPushButton("🎯 自动对齐此事件")
        self.btn_auto_align.clicked.connect(self.align_to_single_event)
        self.btn_auto_align.setStyleSheet("""
            QPushButton {
                background-color: #ffa500; color: #0d0d12; border: 1px solid #ff8c00; 
                padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 10pt;
            }
            QPushButton:hover { background-color: #ffb833; }
            QPushButton:pressed { background-color: #cc7a00; }
        """)
        self.btn_auto_align.hide()

        self.btn_detail_analysis = QtWidgets.QPushButton("📊 占比详细分析")
        self.btn_detail_analysis.clicked.connect(self.toggle_drawer_expansion)
        self.btn_detail_analysis.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: #00f0ff; border: 1px solid #00f0ff; 
                padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 10pt;
            }
            QPushButton:hover { background-color: #004d61; }
            QPushButton:pressed { background-color: #1a1a2e; }
        """)
        self.btn_detail_analysis.hide()

        self.btn_toggle_battery = QtWidgets.QPushButton("🔋 电池评估")
        self.btn_toggle_battery.setCheckable(True)
        self.btn_toggle_battery.setChecked(False)
        self.btn_toggle_battery.clicked.connect(self.toggle_battery_panel)
        self.btn_toggle_battery.setStyleSheet("""
            QPushButton {
                background-color: #1a1a2e; color: #00ff66; border: 1px solid #00aa44; 
                padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 10pt;
            }
            QPushButton:hover { background-color: #004d26; }
            QPushButton:checked { background-color: #006633; color: #ffffff; border: 1px solid #00ff66; }
            QPushButton:pressed { background-color: #00331a; }
        """)

        self.lbl_ana_avg_i.setStyleSheet("color: #00f0ff;")
        self.lbl_ana_mah.setStyleSheet("color: #00ff66;")

        popup_layout.addWidget(self.lbl_ana_duration, 0, 0)
        popup_layout.addWidget(self.lbl_ana_avg_v, 0, 1)
        popup_layout.addWidget(self.lbl_ana_avg_i, 0, 2)
        popup_layout.addWidget(self.lbl_ana_avg_p, 0, 3)
        popup_layout.addWidget(self.lbl_ana_max_i, 1, 0)
        popup_layout.addWidget(self.lbl_ana_min_i, 1, 1)
        popup_layout.addWidget(self.lbl_ana_mah, 1, 2)
        popup_layout.addWidget(self.lbl_ana_mwh, 1, 3)
        
        # Row 2: 左侧事件统计标签，右侧操作按钮栏（一键对齐、精细分析、电池评估）
        popup_layout.addWidget(self.lbl_ana_event_count, 2, 0, 1, 2)

        popup_btn_layout = QtWidgets.QHBoxLayout()
        popup_btn_layout.setSpacing(8)
        popup_btn_layout.addStretch()
        popup_btn_layout.addWidget(self.btn_toggle_battery)
        popup_btn_layout.addWidget(self.btn_auto_align)
        popup_btn_layout.addWidget(self.btn_detail_analysis)
        popup_layout.addLayout(popup_btn_layout, 2, 2, 1, 2)

        # ===== 电池寿命估算面板 (可折叠独立组件，不挤占原本统计与波形) =====
        self.battery_frame = QtWidgets.QFrame()
        self.battery_frame.setStyleSheet("""
            QFrame {
                background-color: #14141c;
                border-top: 1px solid #2d2d3a;
                border-radius: 4px;
            }
            QLabel {
                font-size: 10pt;
                color: #b0b0bc;
                font-weight: normal;
            }
            QDoubleSpinBox {
                background-color: #1a1a24;
                color: #00f0ff;
                border: 1px solid #3d3d52;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 10pt;
                font-weight: bold;
            }
            QDoubleSpinBox:hover {
                border: 1px solid #00f0ff;
            }
        """)
        battery_frame_layout = QtWidgets.QVBoxLayout(self.battery_frame)
        battery_frame_layout.setContentsMargins(10, 8, 10, 8)
        battery_frame_layout.setSpacing(6)

        battery_params = QtWidgets.QHBoxLayout()
        battery_params.setSpacing(6)

        self.spin_battery_capacity = QtWidgets.QDoubleSpinBox()
        self.spin_battery_capacity.setRange(1.0, 1000000.0)
        self.spin_battery_capacity.setValue(220.0)
        self.spin_battery_capacity.setDecimals(0)
        self.spin_battery_capacity.setSuffix(" mAh")
        self.spin_battery_capacity.setFixedWidth(105)
        self.spin_battery_capacity.setToolTip("被测设备电池的标称额定容量")

        self.spin_battery_dod = QtWidgets.QDoubleSpinBox()
        self.spin_battery_dod.setRange(1.0, 100.0)
        self.spin_battery_dod.setValue(85.0)
        self.spin_battery_dod.setDecimals(0)
        self.spin_battery_dod.setSuffix(" %")
        self.spin_battery_dod.setFixedWidth(75)
        self.spin_battery_dod.setToolTip("放电深度 (DoD)：电池实际可用的容量百分比，剩余电量保留以防过放关机")

        self.spin_battery_eff = QtWidgets.QDoubleSpinBox()
        self.spin_battery_eff.setRange(1.0, 1000.0)
        self.spin_battery_eff.setValue(100.0)
        self.spin_battery_eff.setDecimals(1)
        self.spin_battery_eff.setSuffix(" %")
        self.spin_battery_eff.setFixedWidth(85)
        self.spin_battery_eff.setToolTip(
            "等效电流利用率（电荷利用率）：\n"
            "• 直通直驱 / 分析仪替代电池整机供电：设为 100%（无电压变换或变换损耗已测入，直连=100%）；\n"
            "• 降压 DCDC 测低压侧负载（如3.7V转1.8V）：等效效率 = (V电池/V负载)×能量效率，>100%（如 185%）；\n"
            "• 升压 Boost 测高压侧负载（如1.5V升3.3V）：等效效率 = (V电池/V负载)×能量效率，<100%（如 41%）。\n"
            "折算公式：电池端电流 = 负载平均电流 ÷ 效率。"
        )

        self.spin_battery_self_discharge = QtWidgets.QDoubleSpinBox()
        self.spin_battery_self_discharge.setRange(0.0, 100.0)
        self.spin_battery_self_discharge.setValue(0.1)
        self.spin_battery_self_discharge.setDecimals(2)
        self.spin_battery_self_discharge.setSuffix(" %/月")
        self.spin_battery_self_discharge.setFixedWidth(95)
        self.spin_battery_self_discharge.setToolTip("电池月自放电率，按每月损耗折算为等效放电漏电流")

        for sp in (self.spin_battery_capacity, self.spin_battery_dod,
                   self.spin_battery_eff, self.spin_battery_self_discharge):
            sp.valueChanged.connect(self.on_battery_param_changed)

        battery_params.addWidget(QtWidgets.QLabel("电池容量:"))
        battery_params.addWidget(self.spin_battery_capacity)
        battery_params.addSpacing(10)
        battery_params.addWidget(QtWidgets.QLabel("DoD:"))
        battery_params.addWidget(self.spin_battery_dod)
        battery_params.addSpacing(10)
        battery_params.addWidget(QtWidgets.QLabel("转换效率:"))
        battery_params.addWidget(self.spin_battery_eff)
        battery_params.addSpacing(10)
        battery_params.addWidget(QtWidgets.QLabel("自放电率:"))
        battery_params.addWidget(self.spin_battery_self_discharge)
        battery_params.addSpacing(15)

        battery_params.addWidget(QtWidgets.QLabel("电池预置:"))
        self.combo_battery_preset = QtWidgets.QComboBox()
        self.combo_battery_preset.setFixedWidth(330)
        self.combo_battery_preset.setStyleSheet("""
            QComboBox {
                background-color: #1a1a2e;
                color: #00ff66;
                border: 1px solid #3d3d52;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 10pt;
                font-weight: bold;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #3d3d52;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a2e;
                color: #ffffff;
                selection-background-color: #2a3a5e;
                selection-color: #00ff66;
            }
        """)
        self.combo_battery_preset.currentIndexChanged.connect(self.on_battery_preset_selected)
        battery_params.addWidget(self.combo_battery_preset)

        battery_params.addSpacing(6)
        self.btn_config_battery = QtWidgets.QPushButton("⚙️ 电池参数配置")
        self.btn_config_battery.setFixedHeight(26)
        self.btn_config_battery.setStyleSheet("""
            QPushButton {
                background-color: #222230;
                border: 1px solid #555566;
                border-radius: 3px;
                color: #00f0ff;
                padding: 3px 12px;
                font-size: 10pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c2c40;
                border: 1px solid #00f0ff;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #1a1a24;
            }
        """)
        self.btn_config_battery.clicked.connect(self.open_battery_config_dialog)
        battery_params.addWidget(self.btn_config_battery)
        battery_params.addStretch()
        battery_frame_layout.addLayout(battery_params)

        self.lbl_battery_life = QtWidgets.QLabel("预估电池寿命: --")
        battery_life_font = QtGui.QFont()
        battery_life_font.setBold(True)
        battery_life_font.setPointSize(11)
        self.lbl_battery_life.setFont(battery_life_font)
        self.lbl_battery_life.setStyleSheet("color: #00ff66; padding-top: 2px;")
        self.lbl_battery_life.setToolTip(
            "可用容量 = 容量 × DoD；电池端电流 = 负载平均电流 ÷ 效率 + 自放电等效电流；\n"
            "寿命 = 可用容量 ÷ 电池端总电流。负载平均电流 = 累计电量 × 3600 ÷ 区间时长"
        )
        battery_frame_layout.addWidget(self.lbl_battery_life)

        self.update_battery_preset_combo()

        self.battery_frame.hide()
        popup_layout.addWidget(self.battery_frame, 3, 0, 1, 4)

        # ===== 重构：一表化折叠抽屉面板组件 =====
        self.drawer_frame = QtWidgets.QFrame()
        self.drawer_frame.setStyleSheet("""
            QFrame {
                background-color: #14141c;
                border-top: 1px solid #3d3d52;
                border-radius: 0px;
            }
        """)
        drawer_layout = QtWidgets.QVBoxLayout(self.drawer_frame)
        drawer_layout.setContentsMargins(10, 10, 10, 10)
        drawer_layout.setSpacing(5)

        # 抽屉详情表扩展至 12 列以集成“次数”列指标
        self.drawer_table = CopyableTableWidget(0, 12)
        self.drawer_table.setHorizontalHeaderLabels(["状态", "次数", "时长", "时长占比", "单次时长", "平均电流", "最小电流", "最大电流", "累计电量", "电量占比", "单次耗电", "汇总"])
        self.drawer_table.verticalHeader().setVisible(False)  
        self.drawer_table.setMinimumHeight(240)
        self.drawer_table.setMaximumHeight(300)
        self.drawer_table.setStyleSheet("""
            QTableWidget { 
                background-color: #111118; 
                gridline-color: #2d2d3a; 
                color: white; 
                font-size: 10pt; 
            }
            QTableWidget::item {
                padding-left: 10px;   
                padding-right: 10px;
            }
            QHeaderView::section { 
                background-color: #20202c; 
                color: #00f0ff; 
                border: 1px solid #2d2d3a; 
                padding: 5px; 
                font-size: 10pt; 
            }
        """)

        self.drawer_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        self.drawer_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in range(1, 12):
            self.drawer_table.horizontalHeader().setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)

        drawer_layout.addWidget(self.drawer_table)
        self.drawer_frame.hide()
        popup_layout.addWidget(self.drawer_frame, 4, 0, 1, 4)

        self.lbl_ana_event_count.hide()
        self.stats_popup.hide()

        self.update_y_limits()

    # ================= 降采样与性能算法 =================

    def get_peak_downsample_indices(self, i, max_points=15000):
        n = len(i)
        if n <= max_points:
            return np.arange(n)

        num_bins = max_points // 2
        chunk = n // num_bins
        if chunk < 2:
            return np.arange(n)

        remainder = n % num_bins
        if remainder > 0:
            pad_size = num_bins - remainder
            i_padded = np.append(i, [i[-1]] * pad_size)
            n_padded = len(i_padded)
        else:
            i_padded = i
            n_padded = n

        chunk_padded = n_padded // num_bins
        i_reshape = i_padded.reshape(-1, chunk_padded)

        max_idx = np.argmax(i_reshape, axis=1)
        min_idx = np.argmin(i_reshape, axis=1)

        offsets = np.arange(0, n_padded, chunk_padded)
        max_idx_abs = max_idx + offsets
        min_idx_abs = min_idx + offsets

        keep_idx = np.concatenate([max_idx_abs, min_idx_abs])
        keep_idx = np.clip(keep_idx, 0, n - 1)
        keep_idx = np.unique(keep_idx)

        if keep_idx[-1] != n - 1:
            keep_idx = np.append(keep_idx, n - 1)

        keep_idx.sort()
        return keep_idx

    def get_peak_downsample(self, t, v, i, max_points=15000):
        keep_idx = self.get_peak_downsample_indices(i, max_points)
        return t[keep_idx], v[keep_idx], i[keep_idx]

    def render_waveforms(self, t_slice, v_slice, i_slice, s_slice=None, max_points=15000):
        keep_idx = self.get_peak_downsample_indices(i_slice, max_points=max_points)
        disp_t = t_slice[keep_idx]
        disp_v = v_slice[keep_idx]
        disp_i = i_slice[keep_idx]
        
        self.curve_v.setData(disp_t, disp_v)
        self.curve_i.setData(disp_t, disp_i)
        
        if self.chk_show_current.isChecked():
            self.curve_i.show()
        else:
            self.curve_i.hide()
        
        if s_slice is not None:
            disp_s = s_slice[keep_idx]
            self.curve_state.setData(disp_t, disp_s)
            self.curve_state.show()
        else:
            self.curve_state.hide()

    def on_x_range_changed(self, _, range_x):
        if self.is_running:
            val_ma = self.spin_min_yrange.value()
            val_a = val_ma * 1e-3
            self.p_i.getViewBox().setLimits(yMin=0, minYRange=val_a)
        else:
            self.p_i.getViewBox().setLimits(yMin=None, yMax=None, minYRange=None, maxYRange=None)

        if self.ptr == 0:
            return

        min_x, max_x = range_x
        pad = (max_x - min_x) * 0.1
        min_x_padded = min_x - pad
        max_x_padded = max_x + pad

        valid_t = self.t_buffer[:self.pause_ptr]
        start_idx = np.searchsorted(valid_t, min_x_padded)
        end_idx = np.searchsorted(valid_t, max_x_padded)
        raw_pts_in_view = end_idx - start_idx

        # 1. 电流与电压折线渲染
        if not self.is_running:
            if raw_pts_in_view > 100000 and self.t_overview is not None:
                start_ov = np.searchsorted(self.t_overview, min_x_padded)
                end_ov = np.searchsorted(self.t_overview, max_x_padded)
                t_slice = self.t_overview[start_ov:end_ov]
                v_slice = self.v_overview[start_ov:end_ov]
                i_slice = self.i_overview[start_ov:end_ov]
            else:
                t_slice = valid_t[start_idx:end_idx]
                v_slice = self.v_buffer[start_idx:end_idx]
                i_slice = self.i_buffer[start_idx:end_idx]
                
            self.render_waveforms(t_slice, v_slice, i_slice, None, max_points=15000)
            
            # 2. 全分辨率状态边界动态投影
            if self.chk_enable_analysis.isChecked() and self.parsed_events:
                visible_evs = [ev for ev in self.parsed_events if ev['end_time'] >= min_x_padded and ev['start_time'] <= max_x_padded]
                
                t_list = []
                s_list = []
                n_total = len(self.t_buffer)
                
                for ev in visible_evs:
                    s_idx = ev['start_idx']
                    e_idx = ev['end_idx']
                    level = self.state_buffer[s_idx]
                    
                    if s_idx > 0:
                        t_list.append(self.t_buffer[s_idx - 1])
                        s_list.append(0.0)
                        
                    t_list.append(self.t_buffer[s_idx])
                    s_list.append(level)
                    
                    t_list.append(self.t_buffer[e_idx])
                    s_list.append(level)
                    
                    if e_idx + 1 < n_total:
                        t_list.append(self.t_buffer[e_idx + 1])
                        s_list.append(0.0)
                        
                    t_list.append(self.t_buffer[e_idx + 1] if e_idx + 1 < n_total else self.t_buffer[e_idx])
                    s_list.append(np.nan)
                    
                self.curve_state.setData(t_list, s_list)
                self.curve_state.show()
            else:
                self.curve_state.hide()

    # ================= 配置与分析开关模块 =================

    def open_event_config_dialog(self):
        """
        弹出大配置界面，保存时一键重算同步主界面
        """
        dialog = EventConfigDialog(
            self, 
            self.event_configs, 
            active_boundary_ma=self.active_boundary_ma,
            gap_tolerance_ms=self.gap_tolerance_ms
        )
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.event_configs = dialog.configs
            self.active_boundary_ma = dialog.active_boundary_ma
            self.gap_tolerance_ms = dialog.gap_tolerance_ms
            
            print(f"全局配置更新 -> 门限: {self.active_boundary_ma}mA, 合并时间: {self.gap_tolerance_ms}ms")
            self.save_settings()
            
            if not self.is_running and self.ptr > 0:
                self.reanalyze_offline_data()

    def toggle_analysis(self, state):
        """
        联动开关事件分析功能：不开启时完全隐藏按钮和橙色指示线
        """
        is_checked = (state == QtCore.Qt.Checked)
        self.btn_config.setVisible(is_checked)
        self.btn_reanalyze.setVisible(is_checked)
        
        if is_checked:
            if not self.is_running and self.ptr > 0:
                self.reanalyze_offline_data()
        else:
            self.curve_state.hide()
            self.lbl_ana_event_count.hide()
            self.btn_auto_align.hide()
            self.btn_detail_analysis.hide()
            self.drawer_frame.hide()
            self.parsed_events = []
            
            self.state_buffer.fill(np.nan)
            if self.s_overview is not None:
                self.s_overview.fill(np.nan)
            if not self.is_running and self.ptr > 0:
                self.on_x_range_changed(None, self.p_i.viewRange()[0])

    def toggle_current_curve(self, state):
        is_checked = (state == QtCore.Qt.Checked)
        if is_checked:
            self.curve_i.show()
        else:
            self.curve_i.hide()
            
        if not self.is_running and self.ptr > 0:
            self.on_x_range_changed(None, self.p_i.viewRange()[0])

    def update_y_limits(self):
        val_ma = self.spin_min_yrange.value()
        val_a = val_ma * 1e-3  
        if self.is_running:
            self.p_i.getViewBox().setLimits(yMin=0, minYRange=val_a)
        else:
            self.p_i.getViewBox().setLimits(yMin=None, yMax=None, minYRange=None, maxYRange=None)

    def update_sample_interval(self):
        """
        动态修改采样间隔机制
        """
        val_us = self.spin_sample_interval.value()
        if val_us > 0:
            self.dt = val_us * 1e-6
            self.sample_rate = 1.0 / self.dt
        else:
            self.sample_rate = 7092
            self.dt = 1.0 / self.sample_rate

    # ================= 🎯 去皮计算相关功能 =================
    
    def apply_tare(self):
        """
        触发去皮，将当前正在呈现的平均电流添加到总去皮基准中。
        """
        if not self.is_running:
            QtWidgets.QMessageBox.warning(self, "提示", "请在实时刷新状态下进行去皮操作！")
            return
            
        self.tare_offset_i += self.current_avg_i
        self.current_avg_i = 0.0
        
        # 强制清空一下当前的均值累计，确保下一帧界面显示的均值是纯去皮后的全新数据
        self.rt_v_sum = 0.0
        self.rt_i_sum = 0.0
        self.rt_p_sum = 0.0
        self.rt_accum_count = 0
        
        print(f"-> 执行去皮，当前累计电流偏置基准为: {self.tare_offset_i * 1000:.4f} mA")


    # ================= 🎯 路径计算与默认命名算法 =================

    def get_app_dir(self):
        """
        获取程序所在的物理文件夹路径，避免打包后引用临时释放路径
        """
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            try:
                return os.path.dirname(os.path.abspath(sys.argv[0]))
            except Exception:
                return os.getcwd()

    def get_config_path(self):
        """
        配置文件的物理存放路径
        """
        return os.path.join(self.get_app_dir(), "config.json")

    def get_default_csv_filename(self, base_dir):
        """
        生成默认文件名，若当前分钟存在多个则递增 X
        """
        now = datetime.datetime.now()
        time_str = now.strftime("%Y_%m_%d_%H_%M")
        counter = 1
        while True:
            candidate = f"power_log_{time_str}_{counter}.csv.gz"
            full_path = os.path.join(base_dir, candidate)
            if not os.path.exists(full_path):
                return full_path
            counter += 1

    def save_settings(self):
        """
        将当前配置保存到本地 config.json
        """
        if self.is_loading_config:
            return

        path = self.get_config_path()
        port_text = self.combo_port.currentText()
        
        if not port_text or port_text == "未找到串口":
            return

        try:
            cfg = {
                "port": port_text,  
                "active_boundary_ma": self.active_boundary_ma,
                "gap_tolerance_ms": self.gap_tolerance_ms,
                "event_configs": self.event_configs,
                "baud": self.txt_baud.text(),
                "avg_count": self.spin_avg_count.value(),
                "min_yrange": self.spin_min_yrange.value(),
                "sample_interval_us": self.spin_sample_interval.value(),  
                "battery_presets": self.battery_presets,
                "selected_battery_preset_index": self.combo_battery_preset.currentIndex() if hasattr(self, 'combo_battery_preset') else 0,
                "battery_capacity_mah": self.spin_battery_capacity.value(),
                "battery_dod_pct": self.spin_battery_dod.value(),
                "battery_eff_pct": self.spin_battery_eff.value(),
                "battery_self_discharge_pct": self.spin_battery_self_discharge.value(),
                "show_battery_panel": self.btn_toggle_battery.isChecked(),
                "chk_voltage": self.chk_voltage.isChecked(),
                "chk_save_csv": self.chk_save_csv.isChecked(),
                "chk_limit_span": self.chk_limit_span.isChecked(),
                "chk_second_clock": self.chk_second_clock.isChecked(),
                "chk_enable_analysis": self.chk_enable_analysis.isChecked(),
                "chk_show_current": self.chk_show_current.isChecked()
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"写入 config.json 失败: {e}")

    def load_settings(self):
        """
        启动时加载本地配置
        """
        path = self.get_config_path()
        if not os.path.exists(path):
            return
        
        self.is_loading_config = True
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            
            self.active_boundary_ma = cfg.get("active_boundary_ma", 0.5)
            self.gap_tolerance_ms = cfg.get("gap_tolerance_ms", 300)
            self.event_configs = cfg.get("event_configs", self.event_configs)
            
            if "port" in cfg:
                saved_port = str(cfg["port"])
                index = self.combo_port.findText(saved_port)
                if index >= 0:
                    self.combo_port.setCurrentIndex(index)
                else:
                    self.combo_port.addItem(saved_port)
                    self.combo_port.setCurrentText(saved_port)

            if "baud" in cfg:
                self.txt_baud.setText(str(cfg["baud"]))
            if "avg_count" in cfg:
                self.spin_avg_count.setValue(int(cfg["avg_count"]))
            if "min_yrange" in cfg:
                self.spin_min_yrange.setValue(float(cfg["min_yrange"]))
            if "sample_interval_us" in cfg:
                self.spin_sample_interval.setValue(int(cfg["sample_interval_us"]))  
                
            if "battery_presets" in cfg and isinstance(cfg["battery_presets"], list) and len(cfg["battery_presets"]) > 0:
                self.battery_presets = cfg["battery_presets"]
            self.update_battery_preset_combo()

            if "battery_capacity_mah" in cfg:
                self.spin_battery_capacity.setValue(float(cfg["battery_capacity_mah"]))
            if "battery_dod_pct" in cfg:
                self.spin_battery_dod.setValue(float(cfg["battery_dod_pct"]))
            if "battery_eff_pct" in cfg:
                self.spin_battery_eff.setValue(float(cfg["battery_eff_pct"]))
            if "battery_self_discharge_pct" in cfg:
                self.spin_battery_self_discharge.setValue(float(cfg["battery_self_discharge_pct"]))
            if "selected_battery_preset_index" in cfg and hasattr(self, 'combo_battery_preset'):
                idx = int(cfg["selected_battery_preset_index"])
                if 0 <= idx < self.combo_battery_preset.count():
                    self.combo_battery_preset.blockSignals(True)
                    self.combo_battery_preset.setCurrentIndex(idx)
                    self.combo_battery_preset.blockSignals(False)
            if "show_battery_panel" in cfg:
                is_show = bool(cfg["show_battery_panel"])
                self.btn_toggle_battery.setChecked(is_show)
                self.battery_frame.setVisible(is_show)

            if "chk_voltage" in cfg:
                self.chk_voltage.setChecked(cfg["chk_voltage"])
            if "chk_save_csv" in cfg:
                self.chk_save_csv.setChecked(cfg["chk_save_csv"])
            if "chk_limit_span" in cfg:
                self.chk_limit_span.setChecked(cfg["chk_limit_span"])
            if "chk_second_clock" in cfg:
                self.chk_second_clock.setChecked(cfg["chk_second_clock"])
            if "chk_enable_analysis" in cfg:
                self.chk_enable_analysis.setChecked(cfg["chk_enable_analysis"])
            if "chk_show_current" in cfg:
                self.chk_show_current.setChecked(cfg["chk_show_current"])
                
            self.update_time_axis_labels()
            self.update_sample_interval()
            print(f"-> 本地配置加载成功，系统已全面恢复状态。")
        except Exception as e:
            print(f"加载 config.json 失败: {e}")
        finally:
            self.is_loading_config = False

    # ================= 离线数据导入 =================

    def open_offline_csv(self):
        """
        载入离线 CSV 数据并自动运行精准状态切割
        """
        if self.serial_thread and self.serial_thread.isRunning():
            self.stop_thread()
            self.btn_connect.setText("连接设备")
            self.btn_connect.setStyleSheet("")

        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 
            "打开功耗 CSV/GZ 数据文件", 
            "", 
            "Power Log Files (*.csv *.csv.gz);;CSV Files (*.csv);;Gzip CSV Files (*.csv.gz)"
        )
        if not file_path:
            return

        print(f"正在读取离线数据: {file_path}")
        try:
            df = pd.read_csv(file_path)
            df.columns = df.columns.str.strip()
            
            n = len(df)
            if n < 2:
                QtWidgets.QMessageBox.warning(self, "数据错误", "CSV 文件内容不足！")
                return
            
            self.max_len = n
            self.t_buffer = df['Time(s)'].to_numpy(dtype=np.float64).copy()
            self.v_buffer = df['Voltage(V)'].to_numpy(dtype=np.float32).copy()
            self.i_buffer = df['Current(A)'].to_numpy(dtype=np.float32).copy()
            
            self.dt = (self.t_buffer[-1] - self.t_buffer[0]) / (n - 1)
            print(f"-> 离线采样特征解析完成: 动态测得采样频率 = {1.0/self.dt:.3f} Hz, dt = {self.dt*1e6:.3f} us")
            
            self.state_buffer = np.full(n, np.nan, dtype=np.float32)
            
            self.ptr = n
            self.pause_ptr = n
            self.total_count = n
            self.is_offline_loaded = True  
            
            self.is_running = False
            self.btn_run_pause.setText("开始刷新")
            self.btn_run_pause.setStyleSheet("background-color: #1e3a2f; border: 1px solid #2e5a3f;")
            self.region.hide()
            self.stats_popup.hide()

            self.run_offline_analysis()

            self.t_overview, self.v_overview, self.i_overview = self.get_peak_downsample(
                self.t_buffer, self.v_buffer, self.i_buffer, max_points=100000
            )
            overview_indices = self.get_peak_downsample_indices(self.i_buffer, max_points=100000)
            self.s_overview = self.state_buffer[overview_indices]

            self.p_i.setXRange(self.t_buffer[0], self.t_buffer[-1], padding=0.02)
            self.on_x_range_changed(None, self.p_i.viewRange()[0])

            QtWidgets.QMessageBox.information(self, "导入成功", f"成功读取离线数据 {n} 行，并已完成功耗事件切片！")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "读取失败", f"CSV 文件导入失败: {str(e)}")

    def run_offline_analysis(self):
        """
        核心分段切割算法
        """
        self.parsed_events = []
        self.state_buffer.fill(np.nan)

        if not self.chk_enable_analysis.isChecked():
            return

        active_boundary = self.active_boundary_ma * 1e-3  
        gap_tolerance = self.gap_tolerance_ms * 1e-3      

        raw_time = self.t_buffer[:self.pause_ptr]
        raw_current = self.i_buffer[:self.pause_ptr]
        n = len(raw_current)

        active_indices = np.where(raw_current > active_boundary)[0]
        
        events = []
        if len(active_indices) > 0:
            curr_start_idx = active_indices[0]
            curr_end_idx = active_indices[0]
            
            for idx in active_indices[1:]:
                time_gap = raw_time[idx] - raw_time[curr_end_idx]
                if time_gap <= gap_tolerance:
                    curr_end_idx = idx
                else:
                    events.append((curr_start_idx, curr_end_idx))
                    curr_start_idx = idx
                    curr_end_idx = idx
            events.append((curr_start_idx, curr_end_idx))

        min_rule_ms = min([cfg["min_ms"] for cfg in self.event_configs]) if self.event_configs else 1.0
        adaptive_noise_limit_s = max(0.0002, (min_rule_ms * 0.8) * 1e-3)

        for idx, (s_idx, e_idx) in enumerate(events):
            duration = raw_time[e_idx] - raw_time[s_idx]
            if duration < adaptive_noise_limit_s:  
                continue

            slice_curr = raw_current[s_idx:e_idx+1]
            duration_ms = duration * 1000.0
            max_curr_ma = np.max(slice_curr) * 1000.0

            event_type = "Unknown_Active"
            visual_level_ma = 1.0  
            matched = False

            for cfg in self.event_configs:
                min_peak_required = cfg.get("min_peak_ma", 0.0)
                max_peak_limit = cfg.get("max_peak_ma", 9999.0)  
                
                x_match = cfg["min_ms"] <= duration_ms < cfg["max_ms"]
                y_match = min_peak_required <= max_curr_ma <= max_peak_limit
                
                if x_match and y_match:
                    event_type = cfg["name"]
                    visual_level_ma = cfg["level_ma"]
                    matched = True
                    break

            if s_idx > 0:
                self.state_buffer[s_idx - 1] = 0.0
                
            self.state_buffer[s_idx:e_idx+1] = visual_level_ma * 1e-3
            
            if e_idx + 1 < n:
                self.state_buffer[e_idx + 1] = 0.0

            self.parsed_events.append({
                'start_idx': s_idx,
                'end_idx': e_idx,
                'start_time': raw_time[s_idx],
                'end_time': raw_time[e_idx],
                'duration_ms': duration_ms,
                'max_peak_ma': max_curr_ma,
                'type': event_type
            })

        print(f"多维双向联合切割完成，共识别出 {len(self.parsed_events)} 个活跃区间。")

    def reanalyze_offline_data(self):
        if self.is_running or self.ptr == 0:
            QtWidgets.QMessageBox.warning(self, "警告", "请先暂停刷新并载入有效的离线数据！")
            return

        self.run_offline_analysis()

        overview_indices = self.get_peak_downsample_indices(self.i_buffer[:self.pause_ptr], max_points=100000)
        self.s_overview = self.state_buffer[overview_indices]

        self.on_x_range_changed(None, self.p_i.viewRange()[0])
        if self.region.isVisible():
            self.on_region_changed()

        QtWidgets.QMessageBox.information(self, "成功", "重新分析完毕！")

    # ================= 🎯 一键对齐单个事件算法 =================

    def align_to_single_event(self):
        if self.last_single_event is not None:
            t_start = self.last_single_event['start_time']
            t_end = self.last_single_event['end_time']
            
            self.region.blockSignals(True)
            self.region.setRegion([t_start, t_end])
            self.region.blockSignals(False)
            
            self.on_region_changed()

    # ================= 🎯 占比详细数据计算抽屉 =================

    def toggle_drawer_expansion(self):
        is_visible = self.drawer_frame.isVisible()
        self.drawer_frame.setVisible(not is_visible)
        
        if not is_visible:
            self.populate_drawer_table()
            
        self.stats_popup.adjustSize()
        self.update_popup_position()

    def populate_drawer_table(self):
        active_ptr = self.ptr if self.is_running else self.pause_ptr
        if active_ptr == 0 or not self.region.isVisible():
            return

        min_x, max_x = self.region.getRegion()
        valid_t = self.t_buffer[:active_ptr]
        
        start_idx = np.searchsorted(valid_t, min_x)
        end_idx = np.searchsorted(valid_t, max_x)
        if start_idx >= end_idx:
            return

        sel_n = end_idx - start_idx
        t_selected = sel_n * self.dt  
        if t_selected <= 0:
            return

        is_event_mask = np.zeros(sel_n, dtype=bool)

        cat_indices = {cfg["name"]: [] for cfg in self.event_configs}
        cat_indices["Unknown_Active"] = []

        # 1. 物理触发计数器统计
        counts = {cfg["name"]: 0 for cfg in self.event_configs}
        counts["Unknown_Active"] = 0
        counts["待机"] = 0

        for ev in self.parsed_events:
            clamped_s = max(start_idx, ev['start_idx'])
            clamped_e = min(end_idx - 1, ev['end_idx'])

            if clamped_s <= clamped_e:
                is_event_mask[clamped_s - start_idx : clamped_e + 1 - start_idx] = True
                t_type = ev['type']
                if t_type not in cat_indices:
                    t_type = "Unknown_Active"
                cat_indices[t_type].extend(range(clamped_s, clamped_e + 1))

            # 仅统计起始落在已选区间内的物理事件次数
            if min_x <= ev['start_time'] <= max_x:
                ev_t = ev['type']
                if ev_t in counts:
                    counts[ev_t] += 1
                else:
                    counts["Unknown_Active"] += 1

        sleep_indices = np.where(~is_event_mask)[0] + start_idx

        rows_to_process = []
        rows_to_process.append({
            "name": "待机",
            "indices": sleep_indices,
            "count": 0
        })
        for cfg in self.event_configs:
            rows_to_process.append({
                "name": cfg["name"],
                "indices": cat_indices[cfg["name"]],
                "count": counts[cfg["name"]]
            })
        rows_to_process.append({
            "name": "未知事件",
            "indices": cat_indices["Unknown_Active"],
            "count": counts["Unknown_Active"]
        })

        raw_slice_currents = self.i_buffer[start_idx:end_idx]
        total_selected_charge_ah = np.sum(raw_slice_currents) * (self.dt / 3600.0)

        self.drawer_table.blockSignals(True)  
        self.drawer_table.setRowCount(0)
        
        self.row_stats = []  
        num_categories = len(rows_to_process)
        
        self.drawer_table.setRowCount(num_categories + 2)

        for r, row_cfg in enumerate(rows_to_process):
            idx_list = row_cfg["indices"]
            name = row_cfg["name"]
            trigger_count = row_cfg["count"]

            if len(idx_list) == 0:
                stats = {
                    'duration': 0.0,
                    'ratio': 0.0,
                    'avg_duration_per_trigger': 0.0,
                    'charge_ratio': 0.0,
                    'avg_i': 0.0,
                    'min_i': 0.0,
                    'max_i': 0.0,
                    'charge_ah': 0.0,
                    'count': 0,
                    'avg_charge_per_trigger': 0.0
                }
            else:
                p_current = self.i_buffer[idx_list]
                duration = len(idx_list) * self.dt
                ratio = (duration / t_selected) * 100.0  
                max_i = np.max(p_current)
                min_i = np.min(p_current)
                avg_i = p_current.mean()
                charge_ah = np.sum(p_current) * (self.dt / 3600.0)
                
                charge_ratio = (charge_ah / total_selected_charge_ah * 100.0) if total_selected_charge_ah > 0 else 0.0
                
                # 计算单次耗电
                avg_charge_per_trigger = (charge_ah / trigger_count) if trigger_count > 0 else 0.0
                # 计算单次时长
                avg_duration_per_trigger = (duration / trigger_count) if trigger_count > 0 else 0.0

                stats = {
                    'duration': duration,
                    'ratio': ratio,
                    'avg_duration_per_trigger': avg_duration_per_trigger,
                    'charge_ratio': charge_ratio,
                    'avg_i': avg_i,
                    'min_i': min_i,
                    'max_i': max_i,
                    'charge_ah': charge_ah,
                    'count': trigger_count,
                    'avg_charge_per_trigger': avg_charge_per_trigger
                }

            self.row_stats.append(stats)

            # 单次时长与单次耗电文本占位处理
            use_second = self.chk_second_clock.isChecked() if hasattr(self, 'chk_second_clock') else False
            if name == "待机" or trigger_count == 0:
                single_duration_str = "--"
                single_charge_str = "--"
            else:
                single_duration_str = f"{stats['avg_duration_per_trigger']:.4f} s" if use_second else format_human_duration(stats['avg_duration_per_trigger'])
                single_charge_str = format_capacity(stats['avg_charge_per_trigger'])

            duration_str = f"{stats['duration']:.4f} s" if use_second else format_human_duration(stats['duration'])

            # 填充表格行元素 (12列布局，次数插入到状态和时长之间) [2]
            self.table_item_readonly(r, 0, name, QtGui.QColor(255, 255, 255))               
            self.table_item_readonly(r, 1, str(trigger_count), QtGui.QColor(255, 255, 255)) # Col 1 为次数 [2]
            self.table_item_readonly(r, 2, duration_str, QtGui.QColor(255, 255, 255)) # Col 2 顺延为时长 [2]
            self.table_item_readonly(r, 3, f"{stats['ratio']:.2f}%", QtGui.QColor(255, 255, 255))     # Col 3 顺延为比例 [2]
            self.table_item_readonly(r, 4, single_duration_str, QtGui.QColor(255, 165, 0)) # Col 4 顺延为单次时长 [2]
            self.table_item_readonly(r, 5, format_current(stats['avg_i']), QtGui.QColor(0, 240, 255)) 
            self.table_item_readonly(r, 6, format_current(stats['min_i']), QtGui.QColor(255, 255, 255)) 
            self.table_item_readonly(r, 7, format_current(stats['max_i']), QtGui.QColor(255, 255, 255)) 
            self.table_item_readonly(r, 8, format_capacity(stats['charge_ah']), QtGui.QColor(0, 255, 102)) 
            self.table_item_readonly(r, 9, f"{stats['charge_ratio']:.2f}%", QtGui.QColor(0, 255, 102)) 
            self.table_item_readonly(r, 10, single_charge_str, QtGui.QColor(255, 215, 0)) 
            
            # 汇总复选框移动至 Col 11
            chk_widget = CenteredCheckBox(self)
            chk_widget.state_changed.connect(self.update_drawer_summary)  
            self.drawer_table.setCellWidget(r, 11, chk_widget)

        spacer_row_idx = num_categories
        self.drawer_table.setRowHeight(spacer_row_idx, 20)  
        for col in range(12):
            item = QtWidgets.QTableWidgetItem("")
            item.setFlags(QtCore.Qt.NoItemFlags)  
            item.setBackground(QtGui.QColor(20, 20, 28))  
            self.drawer_table.setItem(spacer_row_idx, col, item)

        summary_row_idx = num_categories + 1
        self.drawer_table.setRowHeight(summary_row_idx, 35)

        self.drawer_table.blockSignals(False)  
        self.update_drawer_summary()

    def table_item_readonly(self, row, col, text, color):
        item = QtWidgets.QTableWidgetItem(text)
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        item.setForeground(QtGui.QColor(color))
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        self.drawer_table.setItem(row, col, item)

    def update_drawer_summary(self):
        if not hasattr(self, 'row_stats') or len(self.row_stats) == 0:
            return

        total_duration = 0.0
        total_ratio = 0.0
        total_charge_ratio = 0.0
        total_charge_ah = 0.0
        max_current = -float('inf')
        min_current = float('inf')

        # 汇总行的物理触发次数与累计物理参数（剔除待机）
        total_active_triggers = 0
        total_active_duration = 0.0
        total_active_charge_ah = 0.0

        any_checked = False
        num_categories = len(self.row_stats)

        for r in range(num_categories):
            chk_widget = self.drawer_table.cellWidget(r, 11)
            if chk_widget and chk_widget.isChecked():
                any_checked = True
                stats = self.row_stats[r]

                total_duration += stats['duration']
                total_ratio += stats['ratio']
                total_charge_ratio += stats['charge_ratio']
                total_charge_ah += stats['charge_ah']
                
                # 累加非待机行触发参数
                if r > 0: 
                    total_active_triggers += stats['count']
                    total_active_duration += stats['duration']
                    total_active_charge_ah += stats['charge_ah']

                if stats['duration'] > 0:
                    if stats['max_i'] > max_current:
                        max_current = stats['max_i']
                    if stats['min_i'] < min_current:
                        min_current = stats['min_i']

        summary_row_idx = num_categories + 1
        self.drawer_table.blockSignals(True)

        green_color = QtGui.QColor(0, 255, 102)

        use_second = self.chk_second_clock.isChecked() if hasattr(self, 'chk_second_clock') else False
        def fmt_dur(sec):
            if use_second:
                return f"{sec:.4f} s"
            return format_human_duration(sec)

        if any_checked:
            avg_current = (total_charge_ah * 3600.0 / total_duration) if total_duration > 0 else 0.0
            
            if max_current == -float('inf'): max_current = 0.0
            if min_current == float('inf'): min_current = 0.0

            # 汇总行单值加权计算
            if total_active_triggers > 0:
                summary_avg_duration_str = fmt_dur(total_active_duration / total_active_triggers)
                summary_avg_charge_str = format_capacity(total_active_charge_ah / total_active_triggers)
            else:
                summary_avg_duration_str = "--"
                summary_avg_charge_str = "--"

            self.write_summary_cell(summary_row_idx, 0, "已选汇总", green_color)
            self.write_summary_cell(summary_row_idx, 1, str(total_active_triggers), green_color) # Col 1: 汇总次数 [2]
            self.write_summary_cell(summary_row_idx, 2, fmt_dur(total_duration), green_color)
            self.write_summary_cell(summary_row_idx, 3, f"{total_ratio:.2f}%", green_color)
            self.write_summary_cell(summary_row_idx, 4, summary_avg_duration_str, green_color)
            self.write_summary_cell(summary_row_idx, 5, format_current(avg_current), green_color)
            self.write_summary_cell(summary_row_idx, 6, format_current(min_current), green_color)
            self.write_summary_cell(summary_row_idx, 7, format_current(max_current), green_color)
            self.write_summary_cell(summary_row_idx, 8, format_capacity(total_charge_ah), green_color)
            self.write_summary_cell(summary_row_idx, 9, f"{total_charge_ratio:.2f}%", green_color)
            self.write_summary_cell(summary_row_idx, 10, summary_avg_charge_str, green_color)
            self.write_summary_cell(summary_row_idx, 11, "", green_color)
        else:
            self.write_summary_cell(summary_row_idx, 0, "已选汇总", green_color)
            self.write_summary_cell(summary_row_idx, 1, "0", green_color)
            self.write_summary_cell(summary_row_idx, 2, "0.0000 s" if use_second else "0 秒", green_color)
            self.write_summary_cell(summary_row_idx, 3, "0.00%", green_color)
            self.write_summary_cell(summary_row_idx, 4, "--", green_color)
            self.write_summary_cell(summary_row_idx, 5, "0.00 nA", green_color)
            self.write_summary_cell(summary_row_idx, 6, "0.00 nA", green_color)
            self.write_summary_cell(summary_row_idx, 7, "0.00 nA", green_color)
            self.write_summary_cell(summary_row_idx, 8, "0.000 nAh", green_color)
            self.write_summary_cell(summary_row_idx, 9, "0.00%", green_color)
            self.write_summary_cell(summary_row_idx, 10, "--", green_color)
            self.write_summary_cell(summary_row_idx, 11, "", green_color)

        self.drawer_table.blockSignals(False)

    def write_summary_cell(self, row, col, text, color):
        item = QtWidgets.QTableWidgetItem(text)
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        item.setForeground(color)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        
        font = QtGui.QFont()
        font.setBold(True)
        item.setFont(font)
        
        self.drawer_table.setItem(row, col, item)

    # ================= 交互控制逻辑 =================

    def select_all_data(self):
        active_ptr = self.ptr if self.is_running else self.pause_ptr
        if active_ptr < 2:
            return  

        start_t = self.t_buffer[0]
        end_t = self.t_buffer[active_ptr - 1]

        self.region.blockSignals(True)
        self.region.setRegion([start_t, end_t])
        self.region.blockSignals(False)

        self.region.show()
        self.on_region_changed()

    def update_popup_position(self):
        if hasattr(self, 'stats_popup') and self.stats_popup is not None:
            if self.stats_popup.isVisible():
                self.stats_popup.layout().activate()
                self.stats_popup.adjustSize()
                pw = self.stats_popup.width()
                ph = self.stats_popup.height()
                x = (self.plot_layout.width() - pw) // 2
                y = 20
                self.stats_popup.setGeometry(x, y, pw, ph)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_popup_position()

    def update_time_axis_labels(self):
        """同步时间轴模式及底部标签显示（秒制 vs 人类习惯时钟）"""
        use_second = self.chk_second_clock.isChecked() if hasattr(self, 'chk_second_clock') else False
        if hasattr(self, 'axis_bottom_i'):
            self.axis_bottom_i.set_second_clock(use_second)
        if hasattr(self, 'axis_bottom_v'):
            self.axis_bottom_v.set_second_clock(use_second)
        
        unit_str = 's' if use_second else ''
        label_text = '时间'
        
        # 当显示电压时，p_v在底部显示时轴标签，p_i隐藏底部标签；当隐藏电压时，p_i显示时轴标签
        if hasattr(self, 'chk_voltage') and self.chk_voltage.isChecked():
            self.p_i.setLabel('bottom', '')
            self.p_v.setLabel('bottom', label_text, units=unit_str)
        else:
            self.p_v.setLabel('bottom', '')
            self.p_i.setLabel('bottom', label_text, units=unit_str)

    def toggle_second_clock(self):
        """切换秒制时钟 / 人类习惯单位模式"""
        self.update_time_axis_labels()
        # 刷新选区统计面板时长文本
        if hasattr(self, 'region') and self.region.isVisible():
            self.on_region_changed()
            if hasattr(self, 'drawer_frame') and self.drawer_frame.isVisible():
                self.populate_drawer_table()

    def toggle_voltage_view(self, state):
        if state == QtCore.Qt.Checked:
            self.p_v.show()
        else:
            self.p_v.hide()
        self.update_time_axis_labels() 

    def toggle_connection(self):
        if self.serial_thread and self.serial_thread.isRunning():
            self.stop_thread()
            self.btn_connect.setText("连接设备")
            self.btn_connect.setStyleSheet("")
        else:
            self.start_thread()
            self.btn_connect.setText("断开设备")
            self.btn_connect.setStyleSheet("background-color: #1e3a2f; border: 1px solid #2e5a3f;")

    def toggle_run_pause(self):
        self.is_running = not self.is_running
        if self.is_running:
            self.btn_run_pause.setText("暂停刷新")
            self.btn_run_pause.setStyleSheet("background-color: #6a1b29; border: 1px solid #8a2b3c;")
            self.curve_state.hide()  
        else:
            self.btn_run_pause.setText("开始刷新")
            self.btn_run_pause.setStyleSheet("background-color: #1e3a2f; border: 1px solid #2e5a3f;")
            self.pause_ptr = self.ptr
            
            self.t_overview, self.v_overview, self.i_overview = self.get_peak_downsample(
                self.t_buffer[:self.pause_ptr],
                self.v_buffer[:self.pause_ptr],
                self.i_buffer[:self.pause_ptr],
                max_points=100000
            )
            overview_indices = self.get_peak_downsample_indices(self.i_buffer[:self.pause_ptr], max_points=100000)
            self.s_overview = self.state_buffer[overview_indices]
            
            self.on_x_range_changed(None, self.p_i.viewRange()[0])

    def start_thread(self):
        """
        连接串口并重置运行缓冲
        """
        self.max_len = 36000000
        self.v_buffer = np.zeros(self.max_len, dtype=np.float32)
        self.i_buffer = np.zeros(self.max_len, dtype=np.float32)
        self.t_buffer = np.zeros(self.max_len, dtype=np.float64)
        self.state_buffer = np.full(self.max_len, np.nan, dtype=np.float32)
        
        self.ptr = 0
        self.pause_ptr = 0
        self.total_count = 0
        self.parsed_events = []
        self.last_single_event = None
        self.is_offline_loaded = False
        
        self.btn_run_pause.setEnabled(True)
        self.btn_run_pause.setText("暂停刷新")
        self.btn_run_pause.setStyleSheet("background-color: #6a1b29; border: 1px solid #8a2b3c;")

        self.is_running = True
        self.region.hide()
        self.stats_popup.hide()
        self.lbl_ana_event_count.hide()
        self.btn_auto_align.hide()
        self.btn_detail_analysis.hide()
        self.drawer_frame.hide()
        self.curve_state.hide()

        self.rt_v_sum = 0.0
        self.rt_i_sum = 0.0
        self.rt_p_sum = 0.0
        self.rt_accum_count = 0
        
        # 强制复位均值，避免继承了未接通时的老数据被意外当成去皮数据
        self.current_avg_i = 0.0

        self.start_wall_time = time.time()

        self.t_overview = None
        self.v_overview = None
        self.i_overview = None
        self.s_overview = None

        self.update_sample_interval()

        if self.chk_save_csv.isChecked():
            base_dir = self.get_app_dir()
            default_file_path = self.get_default_csv_filename(base_dir)

            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "选择保存功耗 CSV.GZ 文件位置",
                default_file_path,
                "Gzip CSV Files (*.csv.gz);;All Files (*)"
            )

            if not file_path or file_path.strip() == "":
                file_path = default_file_path
            else:
                if not file_path.lower().endswith(".csv.gz"):
                    if file_path.lower().endswith(".csv"):
                        file_path = file_path + ".gz"
                    else:
                        file_path = file_path + ".csv.gz"

            try:
                self.csv_file = gzip.open(file_path, "wt", compresslevel=1, encoding="utf-8")
                self.csv_file.write("Time(s),Voltage(V),Current(A)\n")
                print(f"数据实时Gzip压缩存档已激活，物理路径: {os.path.abspath(file_path)}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "存储错误", f"无法创建 CSV.GZ 压缩存档文件: {str(e)}")
                self.csv_file = None
        else:
            self.csv_file = None

        self.serial_thread = SerialReaderThread(self.combo_port.currentText(), int(self.txt_baud.text()))
        self.serial_thread.data_received.connect(self.handle_new_data)
        self.serial_thread.error_occurred.connect(self.handle_error)
        self.serial_thread.start()

    def stop_thread(self):
        """
        关闭串口并保存数据。
        """
        if not self.is_running and self.ptr > self.pause_ptr:
            print(f"-> 正在将暂停后额外接收到的数据 ({self.ptr - self.pause_ptr} 行) 刷写入分析区...")
            self.pause_ptr = self.ptr
            self.t_overview, self.v_overview, self.i_overview = self.get_peak_downsample(
                self.t_buffer[:self.pause_ptr],
                self.v_buffer[:self.pause_ptr],
                self.i_buffer[:self.pause_ptr],
                max_points=100000
            )
            self.run_offline_analysis()
            if self.chk_enable_analysis.isChecked():
                overview_indices = self.get_peak_downsample_indices(self.i_buffer[:self.pause_ptr], max_points=100000)
                self.s_overview = self.state_buffer[overview_indices]
            
            self.on_x_range_changed(None, self.p_i.viewRange()[0])

        elif self.is_running:
            self.is_running = False
            self.pause_ptr = self.ptr
            self.t_overview, self.v_overview, self.i_overview = self.get_peak_downsample(
                self.t_buffer[:self.pause_ptr],
                self.v_buffer[:self.pause_ptr],
                self.i_buffer[:self.pause_ptr],
                max_points=100000
            )
            self.run_offline_analysis()
            if self.chk_enable_analysis.isChecked():
                overview_indices = self.get_peak_downsample_indices(self.i_buffer[:self.pause_ptr], max_points=100000)
                self.s_overview = self.state_buffer[overview_indices]
            self.on_x_range_changed(None, self.p_i.viewRange()[0])

        self.btn_run_pause.setEnabled(False)
        self.btn_run_pause.setText("开始刷新")
        self.btn_run_pause.setStyleSheet("background-color: #1a1a24; color: #4a4a5a; border: 1px solid #2d2d3a;")

        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        
        if hasattr(self, 'csv_file') and self.csv_file:
            self.csv_file.flush()
            self.csv_file.close()
            self.csv_file = None

    def handle_error(self, msg):
        QtWidgets.QMessageBox.warning(self, "连接警告", msg)
        self.btn_connect.setText("连接设备")
        self.btn_connect.setStyleSheet("")
        self.stop_thread()

    def handle_new_data(self, v_arr, i_arr):
        n = len(v_arr)
        if n == 0: return
        
        # [核心插入] 强制执行最新累计去皮偏置减法计算，再进行一切后续保存与绘制推流
        if self.tare_offset_i != 0.0:
            i_arr = (i_arr - self.tare_offset_i).astype(np.float32)

        start_t = self.total_count * self.dt
        t_arr = start_t + np.arange(n) * self.dt

        if self.csv_file:
            try:
                lines = "".join(f"{t:.6f},{v:.4f},{i:.9f}\n" for t, v, i in zip(t_arr, v_arr, i_arr))
                self.csv_file.write(lines)
            except Exception as e:
                print(f"写入 CSV.GZ 失败: {str(e)}")

        if self.ptr + n >= self.max_len:
            shift = int(self.max_len * 0.2)
            self.v_buffer[:-shift] = self.v_buffer[shift:]
            self.i_buffer[:-shift] = self.i_buffer[shift:]
            self.t_buffer[:-shift] = self.t_buffer[shift:]
            self.state_buffer[:-shift] = self.state_buffer[shift:]
            self.ptr -= shift
            
            self.pause_ptr -= shift
            if self.pause_ptr < 0:
                self.pause_ptr = 0

        self.v_buffer[self.ptr:self.ptr+n] = v_arr
        self.i_buffer[self.ptr:self.ptr+n] = i_arr
        self.t_buffer[self.ptr:self.ptr+n] = t_arr
        self.ptr += n
        self.total_count += n

        if self.is_running and self.spin_sample_interval.value() == 0:
            elapsed = time.time() - self.start_wall_time
            if 2.0 < elapsed < 15.0:
                measured_rate = self.total_count / elapsed
                self.sample_rate = measured_rate
                self.dt = 1.0 / self.sample_rate
                self.t_buffer[:self.ptr] = np.arange(self.ptr) * self.dt

        if not self.is_running:
            return

        p_arr = v_arr * i_arr
        self.rt_v_sum += np.sum(v_arr)
        self.rt_i_sum += np.sum(i_arr)
        self.rt_p_sum += np.sum(p_arr)
        self.rt_accum_count += n

        target_avg = self.spin_avg_count.value()
        if self.rt_accum_count >= target_avg:
            avg_v = self.rt_v_sum / self.rt_accum_count
            avg_i = self.rt_i_sum / self.rt_accum_count
            avg_p = self.rt_p_sum / self.rt_accum_count
            
            # 时刻同步并暂存当前的展示均值，等待用户一键将其设置为最新的偏置基准
            self.current_avg_i = avg_i

            self.lbl_real_v.setText(f"电压: {format_voltage(avg_v)}")
            self.lbl_real_i.setText(f"电流: {format_current(avg_i)}")
            self.lbl_real_p.setText(f"功率: {format_power(avg_p)}")

            self.rt_v_sum = 0.0
            self.rt_i_sum = 0.0
            self.rt_p_sum = 0.0
            self.rt_accum_count = 0

        valid_t, valid_v, valid_i = self.t_buffer[:self.ptr], self.v_buffer[:self.ptr], self.i_buffer[:self.ptr]
        
        if self.chk_limit_span.isChecked():
            display_limit = 50000  
            if self.ptr > display_limit:
                disp_t = self.t_buffer[self.ptr - display_limit : self.ptr]
                disp_v = self.v_buffer[self.ptr - display_limit : self.ptr]
                disp_i = self.i_buffer[self.ptr - display_limit : self.ptr]
            else:
                disp_t = valid_t
                disp_v = valid_v
                disp_i = valid_i
        else:
            disp_t = valid_t
            disp_v = valid_v
            disp_i = valid_i

        self.render_waveforms(disp_t, disp_v, disp_i, None, max_points=50000)

    def on_region_changed(self):
        active_ptr = self.ptr if self.is_running else self.pause_ptr
        if active_ptr == 0 or not self.region.isVisible():
            return
            
        min_x, max_x = self.region.getRegion()
        valid_t = self.t_buffer[:active_ptr]
        start_idx, end_idx = np.searchsorted(valid_t, min_x), np.searchsorted(valid_t, max_x)
        if start_idx >= end_idx: return

        v_slice = self.v_buffer[start_idx:end_idx]
        i_slice = self.i_buffer[start_idx:end_idx]
        t_slice = self.t_buffer[start_idx:end_idx]
        
        duration = max_x - min_x
        avg_v, avg_i = np.mean(v_slice), np.mean(i_slice)
        p_slice = v_slice * i_slice                 
        avg_p, max_i, min_i = np.mean(p_slice), np.max(i_slice), np.min(i_slice)

        ah = np_trapz(i_slice, t_slice) / 3600.0
        wh = np_trapz(p_slice, t_slice) / 3600.0

        # 缓存本次统计结果，供电池寿命估算使用
        self.last_region_duration_s = duration
        self.last_region_charge_ah = ah
        self.last_region_avg_i = avg_i

        if hasattr(self, 'chk_second_clock') and self.chk_second_clock.isChecked():
            self.lbl_ana_duration.setText(f"区间时长: {duration:.4f} s")
        else:
            self.lbl_ana_duration.setText(f"区间时长: {format_human_duration(duration)}")
        self.lbl_ana_avg_v.setText(f"平均电压: {format_voltage(avg_v)}")
        self.lbl_ana_avg_i.setText(f"平均电流: {format_current(avg_i)}")
        self.lbl_ana_avg_p.setText(f"平均功率: {format_power(avg_p)}")
        self.lbl_ana_max_i.setText(f"最大电流: {format_current(max_i)}")
        self.lbl_ana_min_i.setText(f"最小电流: {format_current(min_i)}")
        self.lbl_ana_mah.setText(f"累计电量: {format_capacity(ah)}")
        self.lbl_ana_mwh.setText(f"累计能量: {format_energy(wh)}")

        if self.chk_enable_analysis.isChecked() and self.parsed_events:
            counts = {cfg["name"]: 0 for cfg in self.event_configs}
            counts["Unknown_Active"] = 0
            
            total_active_count = 0
            single_evt_ref = None

            for ev in self.parsed_events:
                if min_x <= ev['start_time'] <= max_x:
                    t_type = ev['type']
                    if t_type in counts:
                        counts[t_type] += 1
                    else:
                        counts["Unknown_Active"] += 1
                    
                    total_active_count += 1
                    single_evt_ref = ev

            stat_parts = []
            for cfg in self.event_configs:
                name = cfg["name"]
                if counts[name] > 0:
                    stat_parts.append(f"{name}: {counts[name]}次")
            if counts["Unknown_Active"] > 0:
                stat_parts.append(f"未知活跃事件: {counts['Unknown_Active']}次")

            stat_text = "  |  ".join(stat_parts) if stat_parts else "未框选到事件"
            self.lbl_ana_event_count.setText(f"区间事件统计:  {stat_text}")
            self.lbl_ana_event_count.show()

            if total_active_count == 1:
                self.last_single_event = single_evt_ref
                self.btn_auto_align.show()
                self.btn_detail_analysis.hide()
                if self.drawer_frame.isVisible():
                    self.drawer_frame.hide()
                    self.stats_popup.adjustSize()
                    self.update_popup_position()
            elif total_active_count > 1:
                self.last_single_event = None
                self.btn_auto_align.hide()
                self.btn_detail_analysis.show()
                if self.drawer_frame.isVisible():
                    self.populate_drawer_table()
            else:
                self.last_single_event = None
                self.btn_auto_align.hide()
                self.btn_detail_analysis.hide()
                if self.drawer_frame.isVisible():
                    self.drawer_frame.hide()
                    self.stats_popup.adjustSize()
                    self.update_popup_position()
        else:
            self.lbl_ana_event_count.hide()
            self.btn_auto_align.hide()
            self.btn_detail_analysis.hide()
            if self.drawer_frame.isVisible():
                self.drawer_frame.hide()
                self.stats_popup.adjustSize()
                self.update_popup_position()

        if self.btn_toggle_battery.isChecked():
            self.update_battery_life_label()

        self.stats_popup.show()
        self.update_popup_position()

    def toggle_battery_panel(self):
        """
        折叠/展开电池寿命推演面板，支持记忆状态与自适应居中对齐
        """
        is_visible = self.btn_toggle_battery.isChecked()
        self.battery_frame.setVisible(is_visible)
        if is_visible:
            self.update_battery_life_label()
        self.stats_popup.layout().activate()
        self.stats_popup.adjustSize()
        self.update_popup_position()
        self.save_settings()

    def update_battery_preset_combo(self):
        """
        刷新电池预置下拉框内容
        """
        if not hasattr(self, 'combo_battery_preset'):
            return
        self.combo_battery_preset.blockSignals(True)
        curr_idx = self.combo_battery_preset.currentIndex()
        self.combo_battery_preset.clear()
        for p in self.battery_presets:
            name = p.get("name", "未命名电池")
            cap = float(p.get("capacity_mah", 220.0))
            dod = float(p.get("dod_pct", 85.0))
            eff = float(p.get("eff_pct", 100.0))
            sd = float(p.get("self_discharge_pct", 0.1))
            item_text = f"{name} ({cap:.0f}mAh | DoD:{dod:.0f}% | 效:{eff:.0f}% | {sd:.2f}%/月)"
            self.combo_battery_preset.addItem(item_text)
        self.combo_battery_preset.addItem("✏️ 自定义参数 / 手动微调")
        
        if 0 <= curr_idx < len(self.battery_presets):
            self.combo_battery_preset.setCurrentIndex(curr_idx)
        else:
            self.combo_battery_preset.setCurrentIndex(0)
        self.combo_battery_preset.blockSignals(False)

    def on_battery_preset_selected(self, index):
        """
        用户在下拉框中选择电池预置型号时，一键同步更新4个参数SpinBox
        """
        if getattr(self, 'is_applying_battery_preset', False) or index < 0:
            return
        if index < len(self.battery_presets):
            preset = self.battery_presets[index]
            self.is_applying_battery_preset = True
            try:
                self.spin_battery_capacity.setValue(float(preset.get("capacity_mah", 220.0)))
                self.spin_battery_dod.setValue(float(preset.get("dod_pct", 85.0)))
                self.spin_battery_eff.setValue(float(preset.get("eff_pct", 100.0)))
                self.spin_battery_self_discharge.setValue(float(preset.get("self_discharge_pct", 0.1)))
            finally:
                self.is_applying_battery_preset = False
            self.on_battery_param_changed()

    def open_battery_config_dialog(self):
        """
        打开电池预置参数库管理弹窗，支持添加、修改、删除和恢复默认预置
        """
        dlg = BatteryConfigDialog(self, self.battery_presets)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.battery_presets = dlg.presets
            self.update_battery_preset_combo()
            idx = self.combo_battery_preset.currentIndex()
            if 0 <= idx < len(self.battery_presets):
                self.on_battery_preset_selected(idx)
            self.save_settings()

    def on_battery_param_changed(self):
        """
        电池参数发生修改时触发重新计算与保存，并同步下拉框选中状态
        """
        if not getattr(self, 'is_applying_battery_preset', False) and hasattr(self, 'combo_battery_preset'):
            matched_idx = -1
            c_val = self.spin_battery_capacity.value()
            d_val = self.spin_battery_dod.value()
            e_val = self.spin_battery_eff.value()
            s_val = self.spin_battery_self_discharge.value()
            for idx, p in enumerate(self.battery_presets):
                if (abs(float(p.get("capacity_mah", 0.0)) - c_val) < 0.05 and
                    abs(float(p.get("dod_pct", 0.0)) - d_val) < 0.05 and
                    abs(float(p.get("eff_pct", 0.0)) - e_val) < 0.05 and
                    abs(float(p.get("self_discharge_pct", 0.0)) - s_val) < 0.005):
                    matched_idx = idx
                    break
            
            self.combo_battery_preset.blockSignals(True)
            if matched_idx >= 0:
                self.combo_battery_preset.setCurrentIndex(matched_idx)
            else:
                self.combo_battery_preset.setCurrentIndex(self.combo_battery_preset.count() - 1)
            self.combo_battery_preset.blockSignals(False)

        if hasattr(self, 'btn_toggle_battery') and self.btn_toggle_battery.isChecked():
            self.update_battery_life_label()
        if not getattr(self, 'is_loading_config', False):
            self.save_settings()

    def update_battery_life_label(self):
        """
        根据所选区间的累计电量、区间时长，结合电池参数估算电池寿命
        具备极值保护、防除零、负电流保护与年/天级别自动单位换算
        """
        if not hasattr(self, 'spin_battery_capacity'):
            return

        cap_mah = self.spin_battery_capacity.value()
        dod_pct = self.spin_battery_dod.value()
        eff_pct = self.spin_battery_eff.value()
        self_discharge_pct = self.spin_battery_self_discharge.value()

        if (cap_mah <= 0.0 or dod_pct <= 0.0 or eff_pct <= 0.0
                or self.last_region_duration_s <= 0.0001
                or not self.region.isVisible()):
            self.lbl_battery_life.setText("预估电池寿命: --")
            return

        # 负载端平均电流(A)：优先直接采用与上方统计面板完全一致的“平均电流”，彻底杜绝数据不一致
        if hasattr(self, 'last_region_avg_i') and self.last_region_avg_i > 0:
            avg_load_i = self.last_region_avg_i
        elif self.last_region_duration_s > 0:
            avg_load_i = (self.last_region_charge_ah * 3600.0) / self.last_region_duration_s
        else:
            avg_load_i = 0.0

        if avg_load_i <= 0.0:
            self.lbl_battery_life.setText("预估电池寿命: -- (负载电流 <= 0)")
            return

        # 标称容量(Ah)
        cap_ah = cap_mah / 1000.0
        # 可用容量 = 标称容量 × 放电深度
        usable_ah = cap_ah * (dod_pct / 100.0)
        # 电池端电流 = 负载端平均电流 ÷ 转换效率 (防御除零)
        eff_ratio = max(0.01, eff_pct / 100.0)
        batt_i = avg_load_i / eff_ratio
        # 自放电等效电流 = 标称容量 × 月自放电率 ÷ 730.5小时/月
        self_discharge_i = (cap_ah * (self_discharge_pct / 100.0)) / 730.5
        total_i = batt_i + self_discharge_i

        if total_i <= 1e-9:
            self.lbl_battery_life.setText("预估电池寿命: > 100 年 (超微功耗)")
            return

        # 电池寿命(小时) = 可用容量 ÷ 电池端总电流
        lifetime_hours = usable_ah / total_i
        
        # 格式化负载电流便于辅助核对
        i_display = format_current(avg_load_i)
        life_display = format_lifetime_hours(lifetime_hours)
        self.lbl_battery_life.setText(f"预估电池寿命: {life_display}  (平均负载: {i_display})")
        
        if hasattr(self, 'stats_popup') and self.stats_popup.isVisible():
            self.stats_popup.layout().activate()
            self.stats_popup.adjustSize()
            self.update_popup_position()

    def closeEvent(self, event):
        self.save_settings()
        self.stop_thread()
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(13, 13, 18))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(10, 10, 20))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(26, 26, 36))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(42, 42, 56))
    palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    app.setPalette(palette)
    
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())
