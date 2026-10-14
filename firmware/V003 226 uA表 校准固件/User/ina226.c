#include "ina226.h"
#include <stdio.h>
#include "power_app.h"

// --- 保护参数配置---

#define INA226_ALERT_PERCENT    99.9  // 报警点设为满量程
#define INA226_ALERT_VAL        ((32767 * INA226_ALERT_PERCENT) / 100)


// 影子变量，用来保存当前的配置状态，方便位操作
 uint16_t _config_reg = 0x4127; // 复位默认值

// 2. 新增一个全局变量，记录当前的速率状态
INA226_Rate_t current_rate_mode = INA226_RATE_STANDARD;

volatile uint8_t shunt_is_dirty = 0;// 1 = 刚刚发生过切档，当前寄存器数据是脏的

volatile INA226_Shunt_t current_shunt_mode = INA226_SHUNT_10mR; // 状态全局变量

/**
 * @brief 初始化 INA226
 */

void INA226_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStructure = {0};
    EXTI_InitTypeDef EXTI_InitStructure = {0};
    NVIC_InitTypeDef NVIC_InitStructure = {0};

    // 1. GPIO 初始化
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_4;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_Out_PP;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOC, &GPIO_InitStructure);
    GPIOC->BSHR = GPIO_Pin_4; // 默认 10mR 档位

    // --- 【关键1】: 强制软件复位 INA226 芯片 ---
    // 写 00h 寄存器的最高位(Bit15)为 1，会让 INA226 恢复出厂状态，清除一切卡死
    IIC_Write_Reg16(INA226_ADDR, INA226_REG_CONFIG, 0x8000); 
    Delay_Ms(10); // 等它喘口气

    // 3. 重新设置影子变量初始值 (Reset 之后 Bit 14 默认就是 1，Bit 9-11 也有默认值)
    _config_reg = 0x0FF8; // 这是芯片上电默认值
    
    // 5. INA226 内部寄存器配置
    // 设置采样率 (标准模式)
    INA226_Set_Rate(3);
    INA226_Set_Measure_Mode(INA226_MODE_ALL);//A+V
    // 5. 设置报警阈值 (使用百分比宏计算出的 0x7D00 级别数值)
    IIC_Write_Reg16(INA226_ADDR, INA226_REG_ALERTL, (uint16_t)INA226_ALERT_VAL);
    // 6. 配置报警模式 (SOL + Latch)
    IIC_Write_Reg16(INA226_ADDR, INA226_REG_MASK, 0x8001);


    // 1. 修改引脚 3 (PA2) 初始化
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_AFIO, ENABLE);
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_2; // 物理引脚 3 是 PA2
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU; 
    GPIO_Init(GPIOA, &GPIO_InitStructure);

    // 2. 修改 EXTI 映射：从 PD5 改为 PA2
    GPIO_EXTILineConfig(GPIO_PortSourceGPIOA, GPIO_PinSource2);
    EXTI_InitStructure.EXTI_Line = EXTI_Line2; // 注意这里是 Line 2
    EXTI_InitStructure.EXTI_Mode = EXTI_Mode_Interrupt;
    EXTI_InitStructure.EXTI_Trigger = EXTI_Trigger_Falling;
    EXTI_InitStructure.EXTI_LineCmd = ENABLE;
    EXTI_Init(&EXTI_InitStructure);

    // 3. 清除 Line 2 的标志位
    EXTI_ClearITPendingBit(EXTI_Line2);

    // 6. 开启 NVIC
    NVIC_InitStructure.NVIC_IRQChannel = EXTI7_0_IRQn;
    NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 0;
    NVIC_InitStructure.NVIC_IRQChannelSubPriority = 0;
    NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&NVIC_InitStructure);
}

/**
 * @brief 读取芯片制造商 ID，用于验证通讯
 * @return 必须返回 0x5449 才是正常的 INA226
 */
uint16_t INA226_Read_ID(void)
{
    return IIC_Read_Reg16(INA226_ADDR, INA226_REG_MANUF_ID);
}


/**
 * @brief  获取原始分流电压 (LSB = 2.5uV)
 */
int16_t INA226_Get_Raw_ShuntV(void)
{
    return (int16_t)IIC_Read_Reg16(INA226_ADDR, INA226_REG_SHUNTV);
}

/**
 * @brief  获取原始总线电压 (LSB = 1.25mV)
 */
uint16_t INA226_Get_Raw_BusV(void)
{
    return IIC_Read_Reg16(INA226_ADDR, INA226_REG_BUSV);
}

/**
 * @brief  切换采样率 (修改 AVG 和 时钟位)
 */
void INA226_Set_Rate(INA226_Rate_t rate)
{
    // 1. 更新影子变量的 CT 位 (Bit 10-8 和 Bit 7-5)
    // 清除 AVG2..0, VBUSCT2..0, VSHCT2..0 (bits 11:3)
    _config_reg &= ~(0x0FF8);  // 0x0FF8 = 0000 1111 1111 1000

    // 设置平均次数 = 1 (AVG=000)
    // AVG2..0 已清零，无需再置位

    // 设置 VBUSCT 和 VSHCT 为 rate
    _config_reg |= (uint16_t)(rate << 6); // VBUSCT 在 bit8:6
    _config_reg |= (uint16_t)(rate << 3); // VSHCT 在 bit5:3
    
    // 写入硬件
    IIC_Write_Reg16(INA226_ADDR, INA226_REG_CONFIG, _config_reg);

    // ★ 绝对不要用 IIC_Write_Byte 写数据！改用纯指针设定
    I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV);

    // 4. 同步更新业务层的速率状态
    // 如果是 0 (140us)，设定为 FAST 模式；否则设定为 STANDARD 模式（走 CVRF 等待逻辑）
    if (rate == 0) {
        current_rate_mode = INA226_RATE_FAST;
    } else {
        current_rate_mode = INA226_RATE_STANDARD;
    }

    // 5. 标记数据已脏，强制触发主循环的等待/致盲逻辑
    shunt_is_dirty = 1;
}

/**
 * @brief  设置测量模式 (Bit 2-0)
 */
void INA226_Set_Measure_Mode(INA226_Measure_t mode)
{
    // 清除 MODE 位 (D2:0) 并写入新值
    _config_reg &= ~0x0007;
    _config_reg |= (mode & 0x07);
    IIC_Write_Reg16(INA226_ADDR, INA226_REG_CONFIG, _config_reg);
    // 不需要再设指针，因为此时只是改模式，数据尚未更新
    // 但为了安全，可以再调用一次指针设定或留待主循环处理
    shunt_is_dirty = 1;  // 强制下一次读取时同步
}

/**
 * @brief  物理拨动电阻控制脚
 */
volatile uint64_t last_switch_us = 0;

void INA226_Set_Shunt(INA226_Shunt_t shunt)
{
    if (current_shunt_mode == shunt) return;

    if (shunt == INA226_SHUNT_10mR) GPIOC->BSHR = GPIO_Pin_4;
    else                            GPIOC->BCR  = GPIO_Pin_4;

    current_shunt_mode = shunt;
    shunt_is_dirty = 1;
    
    // 关键：记录下切档发生的微秒时刻
    last_switch_us = Get_System_us(); 
}