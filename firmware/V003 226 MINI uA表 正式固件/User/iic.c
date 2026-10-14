#include "iic.h"
#include "ina226.h"

// 定义一个 2 字节的 DMA 专用 I2C 缓冲区
uint8_t i2c_rx_buf[2];

void IIC_DMA_Init(void) {
    DMA_InitTypeDef DMA_InitStructure = {0};
    RCC_AHBPeriphClockCmd(RCC_AHBPeriph_DMA1, ENABLE);
    
    DMA_DeInit(DMA1_Channel7);
    DMA_InitStructure.DMA_PeripheralBaseAddr = (uint32_t)&I2C1->DATAR;
    DMA_InitStructure.DMA_MemoryBaseAddr = (uint32_t)i2c_rx_buf;
    DMA_InitStructure.DMA_DIR = DMA_DIR_PeripheralSRC; // 外设 -> 内存
    DMA_InitStructure.DMA_BufferSize = 2;
    DMA_InitStructure.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    DMA_InitStructure.DMA_MemoryInc = DMA_MemoryInc_Enable;
    DMA_InitStructure.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    DMA_InitStructure.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    DMA_InitStructure.DMA_Mode = DMA_Mode_Normal;
    DMA_InitStructure.DMA_Priority = DMA_Priority_VeryHigh;
    DMA_Init(DMA1_Channel7, &DMA_InitStructure);
    
    // 开启 I2C 的 DMA 接收使能
    I2C1->CTLR2 |= I2C_CTLR2_DMAEN;
}

/**
 * @brief  初始化 I2C1 模块
 * @note   使用 PC1(SDA) 和 PC2(SCL)，开启 400kHz 快速模式
 */
void IIC_Init (void) {
    GPIO_InitTypeDef GPIO_InitStructure = {0};
    I2C_InitTypeDef I2C_InitTSturcture = {0};

    // 1. 开启时钟：GPIOC (外设) 和 I2C1 (硬件控制器)
    // AFIO 是复用功能时钟，PC1/PC2 使用硬件 I2C 功能必须开启它
    RCC_APB2PeriphClockCmd (RCC_APB2Periph_GPIOC | RCC_APB2Periph_AFIO, ENABLE);
    RCC_APB1PeriphClockCmd (RCC_APB1Periph_I2C1, ENABLE);

    // 2. 配置引脚：PC1(SDA) 和 PC2(SCL)
    // 必须配置为复用开漏输出 (AF_OD)，由外部上拉电阻提供高电平
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_1 | GPIO_Pin_2;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_AF_OD;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init (GPIOC, &GPIO_InitStructure);

    // 3. 硬件 I2C 参数配置
    I2C_InitTSturcture.I2C_ClockSpeed = I2C_SPEED;          // 400kHz
    I2C_InitTSturcture.I2C_Mode = I2C_Mode_I2C;             // I2C 模式
    I2C_InitTSturcture.I2C_DutyCycle = I2C_DutyCycle_16_9;  // 快速模式下推荐 16:9 占空比，时序更稳
    I2C_InitTSturcture.I2C_OwnAddress1 = 0x00;              // 作为主机，地址设为 0
    I2C_InitTSturcture.I2C_Ack = I2C_Ack_Enable;            // 允许应答信号
    I2C_InitTSturcture.I2C_AcknowledgedAddress = I2C_AcknowledgedAddress_7bit;

    I2C_Init (I2C1, &I2C_InitTSturcture);

    // 4. 使能 I2C1
    I2C_Cmd (I2C1, ENABLE);
}

/**
 * @brief  向 I2C 设备写入一个字节
 * @param  dev_addr: 设备 8 位地址 (如 OLED 为 0x78)
 * @param  reg_addr: 寄存器地址或控制字 (如 OLED 指令为 0x00)
 * @param  data: 写入的数据
 */
void IIC_Write_Byte (uint8_t dev_addr, uint8_t reg_addr, uint8_t data) {
    // 等待总线空闲
    while (I2C_GetFlagStatus (I2C1, I2C_FLAG_BUSY) != RESET);

    // 发送起始信号 (Start)
    I2C_GenerateSTART (I2C1, ENABLE);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_MODE_SELECT));

    // 发送设备地址 (Transmit 模式)
    I2C_Send7bitAddress (I2C1, dev_addr, I2C_Direction_Transmitter);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED));

    // 发送寄存器地址/控制字
    I2C_SendData (I2C1, reg_addr);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTING));

    // 发送真实数据
    I2C_SendData (I2C1, data);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED));

    // 发送停止信号 (Stop)
    I2C_GenerateSTOP (I2C1, ENABLE);
}

/**
 * @brief  向 I2C 设备连续写入多个字节 (利用 SSD1306 的自动增量特性)
 * @param  dev_addr: 设备地址
 * @param  reg_addr: 控制字 (如像素数据为 0x40)
 * @param  pBuffer: 数据缓冲区首地址
 * @param  length: 发送字节长度
 */
void IIC_Write_Buffer (uint8_t dev_addr, uint8_t reg_addr, uint8_t *pBuffer, uint16_t length) {
    // 等待总线空闲
    while (I2C_GetFlagStatus (I2C1, I2C_FLAG_BUSY) != RESET);

    // 发送 START
    I2C_GenerateSTART (I2C1, ENABLE);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_MODE_SELECT));

    // 发送从机地址
    I2C_Send7bitAddress (I2C1, dev_addr, I2C_Direction_Transmitter);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED));

    // 发送控制字节 (例如 0x40 代表接下来全都是显示数据)
    I2C_SendData (I2C1, reg_addr);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTING));

    // 循环发送缓冲区数据
    for (uint16_t i = 0; i < length; i++) {
        I2C_SendData (I2C1, pBuffer[i]);
        // 每发一个字节，等待 TXE (发送寄存器空) 标志位，准备塞下一个
        while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTING));
    }

    // 等待最后一个字节发送彻底完成
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED));

    // 发送 STOP
    I2C_GenerateSTOP (I2C1, ENABLE);
}

/**
 * @brief  向 I2C 设备的 8位寄存器 写入 16位数据
 */
void IIC_Write_Reg16 (uint8_t dev_addr, uint8_t reg_addr, uint16_t data) {
    uint32_t timeout;

    // 1. 等待总线空闲
    timeout = 10000;
    while (I2C_GetFlagStatus (I2C1, I2C_FLAG_BUSY) != RESET && timeout--);

    // 2. 发送 START 信号
    I2C_GenerateSTART (I2C1, ENABLE);
    timeout = 10000;
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_MODE_SELECT) && timeout--);

    // 3. 发送设备地址 (写方向)
    I2C_Send7bitAddress (I2C1, dev_addr, I2C_Direction_Transmitter);
    timeout = 10000;
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED) && timeout--);

    // 4. 发送寄存器地址
    I2C_SendData (I2C1, reg_addr);
    // 【核心修复】：必须等它彻底发送完毕 (BTF = 1)
    timeout = 10000;
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED) && timeout--);

    // 5. 发送数据高 8 位 (MSB)
    I2C_SendData (I2C1, (uint8_t)(data >> 8));
    // 【核心修复】：必须等它彻底发送完毕
    timeout = 10000;
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED) && timeout--);

    // 6. 发送数据低 8 位 (LSB)
    I2C_SendData (I2C1, (uint8_t)data);
    // 【核心修复】：等待最后一个字节彻底完成
    timeout = 10000;
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED) && timeout--);

    // 7. 发送 STOP 信号
    I2C_GenerateSTOP (I2C1, ENABLE);
}

/**
 * @brief  从 I?C 设备的 8 位寄存器读取 16 位数据（适配 TPA626）
 * @param  dev_addr : 7 位设备地址（例如 0x40）
 * @param  reg_addr : 8 位寄存器地址
 * @return 16 位读出值，通信失败返回 0
 */
uint16_t IIC_Read_Reg16(uint8_t dev_addr, uint8_t reg_addr) {
    uint16_t val = 0;
    uint32_t timeout;

    /* ---- 等待总线空闲 ---- */
    timeout = 100000;
    while (I2C_GetFlagStatus(I2C1, I2C_FLAG_BUSY) != RESET && timeout--);

    /* ---- 1. 发送寄存器地址 ---- */
    I2C_GenerateSTART(I2C1, ENABLE);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_MODE_SELECT) && timeout--);

    I2C_Send7bitAddress(I2C1, dev_addr, I2C_Direction_Transmitter);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED) && timeout--);

    I2C_SendData(I2C1, reg_addr);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED) && timeout--);

    /* ---- 2. 重复起始 + 进入接收模式 ---- */
    I2C_GenerateSTART(I2C1, ENABLE);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_MODE_SELECT) && timeout--);

    I2C_Send7bitAddress(I2C1, dev_addr, I2C_Direction_Receiver);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_RECEIVER_MODE_SELECTED) && timeout--);

    /* ---- 3. 接收第一个字节（高位 MSB）---- */
    I2C_AcknowledgeConfig(I2C1, ENABLE);   // 需要继续读，应答 ACK
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_BYTE_RECEIVED) && timeout--);
    val = (uint16_t)I2C_ReceiveData(I2C1) << 8;

    /* ---- 4. 接收最后一个字节（低位 LSB）---- */
    // 关 ACK 并发送 STOP，告诉 TPA626 这是最后一字节
    I2C_AcknowledgeConfig(I2C1, DISABLE);
    I2C_GenerateSTOP(I2C1, ENABLE);

    // ★ 关键修改：只等待 RXNE 标志，不再等待 MSL/BUSY 复合事件
    timeout = 100000;
    while (!I2C_GetFlagStatus(I2C1, I2C_FLAG_RXNE) && timeout--);
    val |= I2C_ReceiveData(I2C1);

    /* ---- 5. 等待 STOP 真正发送完成，释放总线 ---- */
    timeout = 100000;
    while (I2C_GetFlagStatus(I2C1, I2C_FLAG_BUSY) != RESET && timeout--);

    /* ---- 6. 恢复默认 ACK 设置 ---- */
    I2C_AcknowledgeConfig(I2C1, ENABLE);

    return val;
}

/**
 * @brief  仅发送寄存器指针，不写入任何数据。用于 TPA626 的指针预置。
 * @param  dev_addr : 7位设备地址
 * @param  reg_addr : 8位寄存器地址
 */
void I2C_Set_Reg_Pointer(uint8_t dev_addr, uint8_t reg_addr) {
    uint32_t timeout;

    // 等待总线空闲
    timeout = 100000;
    while (I2C_GetFlagStatus(I2C1, I2C_FLAG_BUSY) != RESET && timeout--);

    // 发送 START
    I2C_GenerateSTART(I2C1, ENABLE);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_MODE_SELECT) && timeout--);

    // 发送设备地址 + 写方向
    I2C_Send7bitAddress(I2C1, dev_addr, I2C_Direction_Transmitter);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED) && timeout--);

    // 发送寄存器地址
    I2C_SendData(I2C1, reg_addr);
    timeout = 100000;
    while (!I2C_CheckEvent(I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED) && timeout--);

    // 立即发送 STOP，不跟数据
    I2C_GenerateSTOP(I2C1, ENABLE);
    timeout = 100000;
    while (I2C_GetFlagStatus(I2C1, I2C_FLAG_BUSY) != RESET && timeout--);
}

/**
 * @brief  PC模式专用：跳过地址发送，直接拽取当前指针处的 2 字节
 * 耗时：约 80us (400kHz I2C 物理极限)
 */
uint16_t IIC_Read_PC_Fast_V2(void)
{
    uint16_t val = 0;
    uint32_t t = 5000; // 设一个很短的超时，大约 100us

    I2C1->CTLR1 |= 0x0100; // START
    while(!(I2C1->STAR1 & 0x0001) && t--);
    if(t == 0) goto i2c_fail;

 // 【核心修改】：自动将宏定义的写地址转换为读地址
    // 如果 INA226_ADDR 是 0x88, 结果是 0x89
    // 如果 INA226_ADDR 是 0x80, 结果是 0x81
    I2C1->DATAR = (uint8_t)(INA226_ADDR | 0x01); 
    t = 5000;
    while(!(I2C1->STAR1 & 0x0002) && t--);
    if(t == 0) goto i2c_fail;
    (void)I2C1->STAR2;
    
    t = 5000;
    while(!(I2C1->STAR1 & 0x0040) && t--);
    if(t == 0) goto i2c_fail;
    val = I2C1->DATAR << 8;
    
    I2C1->CTLR1 &= ~0x0400; // ACK Disable
    I2C1->CTLR1 |= 0x0200;  // STOP
    
    t = 5000;
    while(!(I2C1->STAR1 & 0x0040) && t--);
    if(t == 0) goto i2c_fail;
    val |= I2C1->DATAR;
    
    I2C1->CTLR1 |= 0x0400;  // ACK Enable
    return val;

i2c_fail:
    I2C1->CTLR1 |= 0x0200; // 强制发送 STOP 尝试回收总线
    return 0; // 失败返回 0
}

