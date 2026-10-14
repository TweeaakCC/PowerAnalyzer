# 十元微安表 / 低功耗分析仪 (PowerAnalyzer)

> 基于 CH32V003J4M6 与 INA226，双档自动量程，0.1μA 分辨率，3.3V–36V，7kHz+，1.5Mbps上位机，多工具脚本开源。

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Hardware](https://img.shields.io/badge/OSHWHub-立创开源硬件平台-blue)](https://oshwhub.com/tweeaakc/project_hsmgdfeo)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC_BY--NC--SA_4.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## 📌 项目说明

本项目硬件与最初设计开源于立创开源硬件平台：  
👉 [立创开源广场工程主页：#第11届立创电赛#十元微安表(低功耗分析仪)](https://oshwhub.com/tweeaakc/project_hsmgdfeo)

### 为什么建立此 GitHub 仓库
1. **发布可执行文件**：立创开源广场附件有 50MB 大小限制，在此通过 GitHub Releases 分发打包好的上位机 `.exe` 文件。
2. **协作与 Bug 修复**：方便大家提交 Issue 反馈问题以及提交 PR 参与修复和改进。

---

## 🚀 主要参数

- **主控芯片**：CH32V003J4M6
- **采样芯片**：INA226（不支持国产兼容型号）
- **分辨率**：0.1 μA
- **母线电压**：3.3 V ~ 36 V
- **采样率**：7 kHz+
- **通信速率**：1.5 Mbps 串口

---

## 📂 目录结构

```text
PowerAnalyzer/
├── firmware/                         # 固件源码 (MounRiver Studio 工程)
│   ├── V003 226 MINI uA表 校准固件/  # MINI版校准固件
│   ├── V003 226 MINI uA表 正式固件/  # MINI版正式固件
│   ├── V003 226 uA表 校准固件/       # 标准版校准固件
│   └── V003 226 uA表 正式固件/       # 标准版正式固件
├── tools/                            # 工具与上位机
│   ├── 0.采样电阻计算器.html         # 采样量程与电阻计算
│   ├── 1.电压校准.py                 # 电压校准
│   ├── 2.电流零点校准.py              # 电流零点校准
│   ├── 3.电阻阻值校准.py              # 分流电阻阻值校准
│   ├── 4.精度测试与预测.py            # 精度测试与预测
│   ├── 5.降档阈值计算器.html         # 降档阈值计算
│   ├── 6.有效采样率.py               # 有效采样率测试
│   ├── 7.上位机.py                   # 上位机程序
│   └── config.json                   # 上位机配置文件
├── requirements.txt                  # Python 依赖
├── .gitignore                        # Git 忽略配置
├── LICENSE                           # CC BY-NC-SA 4.0 协议
└── README.md                         # 说明文档
```

> **注意**：各板卡采样电阻与元器件存在容差，固件非通用固件。需使用 `tools/` 中的校准脚本获取参数后，修改固件源码（`User/main.c`），再自行使用 MounRiver Studio 编译烧录。

---

## 🛠️ 上位机运行

环境要求：**Python 3.11**

### 1. 安装依赖
```bash
pip install -r requirements.txt
```
*(注意：串口库使用 `pyserial`，请勿安装 `serial`)*

### 2. 运行
```bash
python tools/7.上位机.py
```

免 Python 环境用户可直接在 [Releases](../../releases) 页面下载打包好的 `.exe` 运行。

---

## 📄 开源许可证

本项目遵循 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans) 开源协议（署名-非商业性使用-相同方式共享）。
