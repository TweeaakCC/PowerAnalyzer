#include "oled.h"
#include "font.h"

// 全局静态变量：全屏仅占用这 128 字节
static uint8_t OLED_Page_Buffer[128];
static uint8_t current_render_page = 0;  // 当前正在渲染哪一页 (0-7)

// 记录当前的翻转状态
static uint8_t screen_flipped = 0;

/**
 * @brief  配置 I2C1_TX 的 DMA 通道 (Channel 6)
 */
static void OLED_DMA_Init (void) {
    DMA_InitTypeDef DMA_InitStructure = {0};
    RCC_AHBPeriphClockCmd (RCC_AHBPeriph_DMA1, ENABLE);

    DMA_DeInit (DMA1_Channel6);
    DMA_InitStructure.DMA_PeripheralBaseAddr = (uint32_t)&I2C1->DATAR;
    DMA_InitStructure.DMA_MemoryBaseAddr = (uint32_t)OLED_Page_Buffer;
    DMA_InitStructure.DMA_DIR = DMA_DIR_PeripheralDST;
    DMA_InitStructure.DMA_BufferSize = 128;
    DMA_InitStructure.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    DMA_InitStructure.DMA_MemoryInc = DMA_MemoryInc_Enable;
    DMA_InitStructure.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    DMA_InitStructure.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    DMA_InitStructure.DMA_Mode = DMA_Mode_Normal;
    DMA_InitStructure.DMA_Priority = DMA_Priority_VeryHigh;
    DMA_InitStructure.DMA_M2M = DMA_M2M_Disable;
    DMA_Init (DMA1_Channel6, &DMA_InitStructure);
}

/**
 * @brief  内部函数：将当前 Page_Buffer 通过 DMA 轰炸到屏幕
 */
static void OLED_Send_Page_DMA (void) {
    while (I2C_GetFlagStatus (I2C1, I2C_FLAG_BUSY) != RESET);
    I2C_GenerateSTART (I2C1, ENABLE);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_MODE_SELECT));
    I2C_Send7bitAddress (I2C1, OLED_ADDR, I2C_Direction_Transmitter);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED));

    I2C_SendData (I2C1, 0x40);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTING));

    DMA_Cmd (DMA1_Channel6, DISABLE);
    DMA1_Channel6->CNTR = 128;
    I2C_DMACmd (I2C1, ENABLE);  
    DMA_Cmd (DMA1_Channel6, ENABLE);

    while (DMA_GetFlagStatus (DMA1_FLAG_TC6) == RESET);
    DMA_ClearFlag (DMA1_FLAG_TC6);

    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED));
    I2C_GenerateSTOP (I2C1, ENABLE);
}

/**
 * @brief  画点函数 (带自动裁剪逻辑)
 */
void OLED_DrawPixel (uint8_t x, uint8_t y, uint8_t color) {
    if (x > 127 || y > 63)
        return;

    if (y / 8 == current_render_page) {
        if (color)
            OLED_Page_Buffer[x] |= (1 << (y % 8));
        else
            OLED_Page_Buffer[x] &= ~(1 << (y % 8));
    }
}

/**
 * @brief  现代化的刷新引擎
 */
void OLED_Update (void (*ui_func) (void)) {
    for (current_render_page = 0; current_render_page < 8; current_render_page++) {
        // 1. 清空当前页缓冲区
        for (uint8_t i = 0; i < 128; i++) OLED_Page_Buffer[i] = 0;

        // 2. 运行 UI 逻辑
        ui_func();

        // 3. 设置屏幕硬件页地址
        IIC_Write_Byte (OLED_ADDR, 0x00, 0xB0 + current_render_page);  
        IIC_Write_Byte (OLED_ADDR, 0x00, 0x00);                        
        IIC_Write_Byte (OLED_ADDR, 0x00, 0x10);                        

        // 4. 发送数据
        OLED_Send_Page_DMA();
    }
}

/**
 * @brief  初始化 OLED
 */
void OLED_Init (void) {
    IIC_Init();       
    OLED_DMA_Init();  

    Delay_Ms (100);   

    IIC_Write_Byte (OLED_ADDR, 0x00, 0xAE);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xD5);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x80);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xA8);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x3F);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xD3);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x00);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x40);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x8D);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x14);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x20);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x02);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xA1);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xC8);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xDA);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x12);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x81);  
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xCF);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xAF);  
}

// ================= 应用层绘图函数 =================

// 1. 变长整数转换
uint8_t int_to_str (char *buf, uint32_t val) {
    if (val == 0) {
        buf[0] = '0';
        return 1;
    }
    uint8_t len = 0;
    char temp[11];
    while (val > 0) {
        temp[len++] = (val % 10) + '0';
        val /= 10;
    }
    for (uint8_t i = 0; i < len; i++) buf[i] = temp[len - 1 - i];
    return len;
}

// 2. 固定宽度补零转换
void int_to_str_fixed (char *buf, uint32_t val, uint8_t width) {
    for (int8_t i = width - 1; i >= 0; i--) {
        buf[i] = (val % 10) + '0';
        val /= 10;
    }
}

void OLED_ShowChar_9x18 (uint8_t x, uint8_t y, char c) {
    uint8_t col, row_byte, bit, data;
    int16_t char_pos = -1;
    const char *idx_ptr = FONT_INDEX_STR;

    for (uint16_t i = 0; idx_ptr[i] != '\0'; i++) {
        if (idx_ptr[i] == c) {
            char_pos = i;
            break;
        }
    }

    if (char_pos == -1)
        return;

    for (col = 0; col < 9; col++) {
        for (row_byte = 0; row_byte < 3; row_byte++) {
            data = ascii_9x18[char_pos][col * 3 + row_byte];
            for (bit = 0; bit < 8; bit++) {
                if (data & (0x80 >> bit)) {
                    if ((row_byte * 8 + bit) < 18) {
                        OLED_DrawPixel (x + col, y + row_byte * 8 + bit, 1);
                    }
                }
            }
        }
    }
}

void OLED_ShowString (uint8_t x, uint8_t y, char *str) {
    while (*str) {
        OLED_ShowChar_9x18 (x, y, *str);
        x += 9;  
        str++;
    }
}

void OLED_ShowFixedNum (uint8_t x, uint8_t y, int32_t val, uint8_t decimal_pos, char *unit) {
    char buf[32];
    uint8_t p = 0;
    int32_t abs_val = (val < 0) ? -val : val;

    if (val < 0)
        buf[p++] = '-';

    if (decimal_pos > 0) {
        uint32_t div = 1;
        if (decimal_pos == 4)
            div = 10000;
        else if (decimal_pos == 3)
            div = 1000;
        else if (decimal_pos == 2)
            div = 100;
        else if (decimal_pos == 1)
            div = 10;

        p += int_to_str (&buf[p], abs_val / div);
        buf[p++] = '.';
        int_to_str_fixed (&buf[p], abs_val % div, decimal_pos);
        p += decimal_pos;
    } else {
        p += int_to_str (&buf[p], abs_val);
    }

    buf[p++] = ' ';
    char *u = unit;
    while (*u) buf[p++] = *u++;
    buf[p] = '\0';

    OLED_ShowString (x, y, "                ");
    OLED_ShowString (x, y, buf);
}

void OLED_Write_Cmd (uint8_t cmd) {
    IIC_Write_Byte (OLED_ADDR, 0x00, cmd);
}

void OLED_SetRotation (uint8_t flipped) {
    screen_flipped = flipped;
    if (flipped) {
        OLED_Write_Cmd (0xA0);  
        OLED_Write_Cmd (0xC0);  
    } else {
        OLED_Write_Cmd (0xA1);  
        OLED_Write_Cmd (0xC8);  
    }
}

void UART_SendHex (uint16_t val) {
    const char hex[] = "0123456789ABCDEF";
    uint8_t data[4] = {hex[(val >> 12) & 0xF], hex[(val >> 8) & 0xF], hex[(val >> 4) & 0xF], hex[val & 0xF]};
    for (uint8_t i = 0; i < 4; i++) {
        while (USART_GetFlagStatus (USART1, USART_FLAG_TC) == RESET);
        USART_SendData (USART1, data[i]);
    }
    while (USART_GetFlagStatus (USART1, USART_FLAG_TC) == RESET);
    USART_SendData (USART1, ' ');  
}