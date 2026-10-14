#ifndef __OLED_H
#define __OLED_H

#include "iic.h"

// OLED 常量定义
#define OLED_ADDR 0x78

// 函数声明
void OLED_Init(void);
void OLED_Update(void (*ui_func)(void)); // 核心刷新引擎

// 高级绘图函数 (应用层调用)
uint8_t int_to_str(char *buf, uint32_t val);
void fast_itoa(char* buf, int32_t num, uint8_t width);
void int_to_str_fixed(char *buf, uint32_t val, uint8_t width);
void OLED_DrawPixel(uint8_t x, uint8_t y, uint8_t color);
void OLED_ShowChar_9x18(uint8_t x, uint8_t y, char c);
void OLED_ShowString(uint8_t x, uint8_t y, char *str);
void OLED_ShowNum_9x18(uint8_t x, uint8_t y, uint32_t num, uint8_t len);

void OLED_ShowFixedNum(uint8_t x, uint8_t y, int32_t val, uint8_t decimal_pos, char *unit);

void OLED_Write_Cmd(uint8_t cmd);

void OLED_SetRotation(uint8_t flipped);

void UART_SendHex(uint16_t val);
void OLED_Clear(void);
#endif