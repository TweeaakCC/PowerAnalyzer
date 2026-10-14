#ifndef __IIC_H
#define __IIC_H

#include "ch32v00x.h"
#include <stdio.h>

// I2C 速度配置：400000 代表 400kHz 快速模式
#define I2C_SPEED            400000

// 函数声明
void IIC_Init(void);
void IIC_Write_Byte(uint8_t dev_addr, uint8_t reg_addr, uint8_t data);
void IIC_Write_Buffer(uint8_t dev_addr, uint8_t reg_addr, uint8_t *pBuffer, uint16_t length);

/**
 * @brief  仅发送寄存器指针，不写入任何数据。用于 TPA626 的指针预置。
 * @param  dev_addr : 7位设备地址
 * @param  reg_addr : 8位寄存器地址
 */
void I2C_Set_Reg_Pointer(uint8_t dev_addr, uint8_t reg_addr) ;
/**
 * @brief  向 I2C 设备的 8位寄存器 写入 16位数据
 */
void IIC_Write_Reg16(uint8_t dev_addr, uint8_t reg_addr, uint16_t data);

/**
 * @brief  从 I2C 设备的 8位寄存器 读取 16位数据
 */
uint16_t IIC_Read_Reg16(uint8_t dev_addr, uint8_t reg_addr);

uint16_t IIC_Read_PC_Fast_V2(void);

void IIC_DMA_Init(void);
#endif