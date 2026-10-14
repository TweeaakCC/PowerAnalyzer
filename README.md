# ⚡ 十元微安表 / 低功耗分析仪 (PowerAnalyzer)

> **基于 CH32V003J4M6 + INA226 的超高性价比微安级低功耗电流分析仪与全套自动化校准工具链**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Hardware](https://img.shields.io/badge/OSHWHub-立创开源硬件平台-blue)](https://oshwhub.com/tweeaakc/project_hsmgdfeo)
[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC_BY--NC--SA_4.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

---

## 📌 项目背景与开仓说明

本项目硬件设计与原理图最初开源于 **立创开源硬件平台（第11届立创电赛参赛项目）**：  
👉 **[点击访问立创开源广场工程主页：#第11届立创电赛#十元微安表(低功耗分析仪)](https://oshwhub.com/tweeaakc/project_hsmgdfeo)**

### 为什么在 GitHub 建立此仓库？
1. **规避附件大小限制与发布分发**：立创开源广场对工程附件有 **50MB** 的严格单文件限制，而基于 Python 打包的桌面上位机可执行文件（`.exe`）体积通常较大。通过 GitHub **[Releases](../../releases)** 页面可以便捷发布免安装独立运行包，方便无需 Python 环境的普通用户即开即用。
2. **社区协作与持续 Bug 修复**：上位机（PyQt5 + PyQtGraph）与自动化校准工具链功能在持续演进。设立 GitHub 仓库旨在方便广大软硬件开发者提交 **Issue** 反馈问题、发起 **Pull Request (PR)** 参与代码优化与功能拓展。
3. **标准化工程版本控制**：告别过去以文件名区分版本的繁琐方式，全面采用 Git 分支与 Tag 进行标准版本追踪。

---

## 🚀 核心硬件与性能指标

- **核心主控**：WCH 沁恒 `CH32V003J4M6` (青稞 32 位 RISC-V 内核)
- **采样前端**：TI / 国产兼容 `INA226` 高精度双向电流/功率监控芯片
- **电流分辨率**：最小可达 **0.1 μA**
- **母线电压范围**：**3.3 V ~ 36 V**
- **实时采样率**：最高 **7 kHz+** 实时流式连续采样
- **高速串口通信**：**1.5 Mbps** (1500000 波特率) 高速 USB-CDC / 串口传输
- **核心上位机特性**：
  - 基于 PyQt5 + PyQtGraph 极速绘图引擎，支持百万级数据点峰值降采样与毫秒级缩放平移；
  - 动态去皮偏置、实时电量积分 (mAh / Ah)；
  - 自动化事件切片分析、状态机电流波形识别；
  - 预置纽扣电池/锂电池寿命精准建模估算；
  - 实时 `.csv.gz` 无损高压缩率数据流后台静默归档。

---

## 📂 仓库目录结构

```text
PowerAnalyzer/
├── firmware/                         # 下位机固件源码 (MounRiver Studio 工程)
│   ├── V003 226 MINI uA表 校准固件/  # MINI版专用校准固件
│   ├── V003 226 MINI uA表 正式固件/  # MINI版日常测量固件
│   ├── V003 226 uA表 校准固件/       # 标准版专用校准固件
│   └── V003 226 uA表 正式固件/       # 标准版日常测量固件
├── tools/                            # 0~7 号流水线工具与上位机
│   ├── 0.采样电阻计算器.html         # 网页端采样量程与电阻选型计算器
│   ├── 1.电压校准.py                 # 电压基准自动化标定脚本
│   ├── 2.电流零点校准.py              # 电流零点偏置校准脚本
│   ├── 3.电阻阻值校准.py              # 实际分流电阻精确值校准 (支持 OCR 自动读表)
│   ├── 4.精度测试与预测.py            # 测量精度评估与理论误差预测
│   ├── 5.降档阈值计算器.html         # 自动量程切换阈值计算器
│   ├── 6.有效采样率.py               # 硬件通信有效采样率压测工具
│   ├── 7.上位机.py                   # 核心分析仪上位机程序 (实时波形与功耗分析)
│   └── config.json                   # 上位机运行配置与电池预置库
├── requirements.txt                  # Python 依赖清单 (推荐 Python 3.11)
├── .gitignore                        # 编译中间文件、可执行文件与系统缓存忽略规则
└── README.md                         # 项目使用说明文档
```

> [!NOTE]
> **关于固件编译的说明**：  
> 每一台自制微安表的实际采样电阻阻值和硬件容差均不同（非通用固定固件）。使用者需要先运行 `tools/` 中的校准脚本标定各自板卡的专属参数，并将校准得到的参数修改至固件源码 `User/main.c` 对应宏定义中，随后在 **MounRiver Studio** 中编译并烧录至 MCU。因此本仓库不收录中间编译产物（`.hex` / `.obj`）。

---

## 🛠️ 上位机运行与环境配置

> **推荐环境**：**Python 3.11**（暂不建议使用 Python 3.13，以避免部分科学计算包与 PyQt 依赖兼容问题）。

### 1. 安装依赖包
```bash
pip install -r requirements.txt
```
*(注意：请确保安装的是 `pyserial`，不要安装名为 `serial` 的包)*

### 2. 运行上位机
```bash
python tools/7.上位机.py
```

### 3. 免环境版可执行程序 (.exe)
如果您无需修改上位机源码，可直接前往本仓库右侧的 **[Releases](../../releases)** 页面下载最新发布的打包运行包，解压后双击即可运行。

---

## 🤝 参与贡献与交流

非常欢迎大家共同参与此项目的完善：
- 遇到了问题或有功能改进建议？欢迎提交 **[Issues](../../issues)**！
- 优化了代码或修复了 Bug？欢迎发起 **[Pull Request](../../pulls)**！
- 硬件 PCB 制板文件、BOM 清单及详细组装焊接指南，请前往 **[立创开源广场项目主页](https://oshwhub.com/tweeaakc/project_hsmgdfeo)** 查阅。

---

## 📄 开源许可证 (License)

本项目遵循 **[CC BY-NC-SA 4.0 (知识共享 署名-非商业性使用-相同方式共享 4.0 国际许可协议)](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)**：
- **署名 (Attribution)**：必须保留原作者署名，并提供协议链接；
- **非商业性使用 (NonCommercial)**：不得将本项目的软硬件及衍生品用于商业营利目的；
- **相同方式共享 (ShareAlike)**：若对本项目进行修改或二次创作，衍生作品必须采用完全相同的许可协议进行分发。

