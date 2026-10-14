#ifndef __INA226_H
#define __INA226_H

#include "iic.h"

// 从你扫描结果可知，7位地址是0x44，8位写地址就是 0x88
#define INA226_ADDR             0x80

// INA226 核心寄存器地址
#define INA226_REG_CONFIG       0x00 // 配置寄存器
#define INA226_REG_SHUNTV       0x01 // 分流电压 (用来算电流)
#define INA226_REG_BUSV         0x02 // 总线电压
#define INA226_REG_POWER        0x03 // 功率 (我们不用)
#define INA226_REG_CURRENT      0x04 // 电流 (我们不用内部的)
#define INA226_REG_CALIB        0x05 // 校准寄存器
#define INA226_REG_MASK         0x06 // 报警屏蔽/使能
#define INA226_REG_ALERTL       0x07 // 报警阈值
#define INA226_REG_MANUF_ID     0xFE // 制造商 ID (固定为 0x5449)
#define INA226_REG_DIE_ID       0xFF // 芯片 ID (固定为 0x2260)

// 1. 采样率模式枚举
// 参考手册：VBUSCT和VSHCT决定采样时间，AVG决定平均次数
typedef enum {
    // 标准模式：1.1ms采样 + 16次平均 = 每 17.6ms 更新一次 (约 56Hz)
    // 非常平滑，适合日常观察数值
    INA226_RATE_STANDARD = 7, 
    
    // 快速模式：140us采样 + 1次平均 = 每 280us 更新一次 (约 3.5kHz)
    // 极速狂飙，适合捕捉峰值 (PEEK) 和画高速波形
    INA226_RATE_FAST     = 0  
} INA226_Rate_t;

// 2. 采样电阻档位枚举
typedef enum {
    INA226_SHUNT_10mR   = 0, // 10毫欧，用于大电流 (最大 8A)
    INA226_SHUNT_100R   = 1  // 100欧姆，用于微小电流 (1uA 级别)
} INA226_Shunt_t;

// 3. 测量模式枚举 (控制 Bit 2-0)
typedef enum {
    INA226_MODE_POWER_DOWN = 0, // 掉电模式，极其省电
    INA226_MODE_VOLT_ONLY  = 6, // 仅测总线电压
    INA226_MODE_CURR_ONLY  = 5, // 仅测电流 (分流电压)
    INA226_MODE_ALL        = 7  // 电压电流全开 (默认)
} INA226_Measure_t;


uint16_t INA226_Read_ID(void); // 基础测试：读 ID

// 函数接口
void INA226_Init(void);
void INA226_Set_Shunt(INA226_Shunt_t shunt);
void INA226_Set_Rate(INA226_Rate_t rate);
void INA226_Set_Measure_Mode(INA226_Measure_t mode);

// 原始值读取函数
int16_t  INA226_Get_Raw_ShuntV(void); // 读寄存器 01h
uint16_t INA226_Get_Raw_BusV(void);   // 读寄存器 02h


// 导出校准偏移变量，让 main.c 可以读取
extern volatile INA226_Shunt_t current_shunt_mode; // 导出当前档位状态

extern uint16_t _config_reg;
extern INA226_Rate_t current_rate_mode;

// 1 = 刚刚发生过切档，当前寄存器数据是脏的
extern volatile uint8_t shunt_is_dirty;

// 修改为 64 位 us 时间戳
extern volatile uint64_t last_switch_us;


#endif