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
    // 1. I2C 握手：产生 START 和发送从机地址 (DMA 无法处理这部分)
    while (I2C_GetFlagStatus (I2C1, I2C_FLAG_BUSY) != RESET);
    I2C_GenerateSTART (I2C1, ENABLE);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_MODE_SELECT));
    I2C_Send7bitAddress (I2C1, OLED_ADDR, I2C_Direction_Transmitter);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_TRANSMITTER_MODE_SELECTED));

    // 2. 发送控制字节 0x40 (代表接下来是数据流)
    I2C_SendData (I2C1, 0x40);
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTING));

    // 3. 配置并开启 DMA 发送 128 字节数据
    DMA_Cmd (DMA1_Channel6, DISABLE);
    DMA1_Channel6->CNTR = 128;
    I2C_DMACmd (I2C1, ENABLE);  // 开启 I2C 的 DMA 请求
    DMA_Cmd (DMA1_Channel6, ENABLE);

    // 4. 等待 DMA 搬运完成 (TC: Transfer Complete)
    while (DMA_GetFlagStatus (DMA1_FLAG_TC6) == RESET);
    DMA_ClearFlag (DMA1_FLAG_TC6);

    // 5. 确保 I2C 最后一个字节也发完了
    while (!I2C_CheckEvent (I2C1, I2C_EVENT_MASTER_BYTE_TRANSMITTED));
    I2C_GenerateSTOP (I2C1, ENABLE);
}

/**
 * @brief  画点函数 (带自动裁剪逻辑)
 * @note   这是所有绘图的基础，它决定了哪些像素能进入当前的 Page_Buffer
 */
void OLED_DrawPixel (uint8_t x, uint8_t y, uint8_t color) {
    if (x > 127 || y > 63)
        return;

    // 关键逻辑：判断该点的 Y 坐标是否落在当前正在渲染的这一页 (8像素高度) 内
    if (y / 8 == current_render_page) {
        if (color)
            OLED_Page_Buffer[x] |= (1 << (y % 8));
        else
            OLED_Page_Buffer[x] &= ~(1 << (y % 8));
    }
}

/**
 * @brief  现代化的刷新引擎：用户只需关心“画什么”，底层处理“怎么刷”
 * @param  ui_func: 指向绘图逻辑函数的指针
 */
void OLED_Update (void (*ui_func) (void)) {
    // 循环渲染 8 个页面，完成一帧更新
    for (current_render_page = 0; current_render_page < 8; current_render_page++) {
        // 1. 清空当前页缓冲区 (页擦除)
        for (uint8_t i = 0; i < 128; i++) OLED_Page_Buffer[i] = 0;

        // 2. 运行 UI 逻辑
        // 注意：ui_func 里的所有绘图指令都会被执行，但只有坐标匹配当前页的才会写入 Buffer
        ui_func();

        // 3. 设置屏幕硬件坐标 (页寻址)
        IIC_Write_Byte (OLED_ADDR, 0x00, 0xB0 + current_render_page);  // 设置页地址
        IIC_Write_Byte (OLED_ADDR, 0x00, 0x00);                        // 设置列低位
        IIC_Write_Byte (OLED_ADDR, 0x00, 0x10);                        // 设置列高位

        // 4. 发送数据
        OLED_Send_Page_DMA();
    }
}

/**
 * @brief  初始化 OLED
 */
void OLED_Init (void) {
    IIC_Init();       // 底层硬件 I2C 初始化
    OLED_DMA_Init();  // DMA 通道初始化

    Delay_Ms (100);   // 等待屏幕稳定

    // SSD1306 标准初始化序列
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xAE);  // 关显示
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xD5);  // 时钟分频
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x80);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xA8);  // 复用率
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x3F);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xD3);  // 偏移
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x00);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x40);  // 起始行
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x8D);  // 电荷泵
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x14);  // 开启
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x20);  // 内存寻址
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x02);  // 页模式
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xA1);  // 左右反转
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xC8);  // 上下反转
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xDA);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x12);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0x81);  // 对比度
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xCF);
    IIC_Write_Byte (OLED_ADDR, 0x00, 0xAF);  // 开显示
}

// ================= 应用层绘图函数 =================

/**
 * @brief  极其精简的数字转字符串工具
 * @param  buf: 存储结果的缓冲区
 * @param  num: 待转数字
 * @param  width: 固定宽度（如果不够则补'0'）
 */
void fast_itoa (char *buf, int32_t num, uint8_t width) {
    // 从后往前填充
    for (int8_t i = width - 1; i >= 0; i--) {
        buf[i] = (num % 10) + '0';
        num /= 10;
    }
    buf[width] = '\0';
}

// 1. 变长整数转换 (比如 123 -> "123", 0 -> "0")
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

// 2. 固定宽度补零转换 (比如 5 转换成 3位宽度 -> "005")
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

    // --- 核心映射逻辑 ---
    // 在索引字符串中查找当前字符 c 的位置
    for (uint16_t i = 0; idx_ptr[i] != '\0'; i++) {
        if (idx_ptr[i] == c) {
            char_pos = i;
            break;
        }
    }

    // 如果没取这个模，直接返回（或者画个空格）
    if (char_pos == -1)
        return;

    // --- 后面的渲染逻辑完全不变，只是数组索引换成了 char_pos ---
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

// 别忘了同步修改 ShowString 调用
void OLED_ShowString (uint8_t x, uint8_t y, char *str) {
    while (*str) {
        OLED_ShowChar_9x18 (x, y, *str);
        x += 9;  // 字体宽 9 像素
        str++;
    }
}

/**
 * @brief  轻量级定点数转字符串函数（避开复杂的 %f）
 */
void OLED_ShowFixedNum (uint8_t x, uint8_t y, int32_t val, uint8_t decimal_pos, char *unit) {
    char buf[32];
    uint8_t p = 0;
    int32_t abs_val = (val < 0) ? -val : val;

    // 1. 处理负号
    if (val < 0)
        buf[p++] = '-';

    // 2. 实现缩放逻辑
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

        // 转换整数部分
        p += int_to_str (&buf[p], abs_val / div);
        // 插入小数点
        buf[p++] = '.';
        // 转换并补全小数部分 (确保 0.005 不会变成 0.5)
        int_to_str_fixed (&buf[p], abs_val % div, decimal_pos);
        p += decimal_pos;
    } else {
        // 纯整数模式 (decimal_pos == 0)
        p += int_to_str (&buf[p], abs_val);
    }

    // 3. 拼接空格和单位 (完全复刻原本的显示效果)
    buf[p++] = ' ';
    char *u = unit;
    while (*u) buf[p++] = *u++;
    buf[p] = '\0';

    // 4. 清行并刷新
    OLED_ShowString (x, y, "                ");
    OLED_ShowString (x, y, buf);
}

/**
 * @brief  向 OLED 发送一条指令
 */
void OLED_Write_Cmd (uint8_t cmd) {
    IIC_Write_Byte (OLED_ADDR, 0x00, cmd);
}

/**
 * @brief  设置屏幕翻转
 * @param  flipped: 0 = 正常模式, 1 = 180度翻转
 */
void OLED_SetRotation (uint8_t flipped) {
    screen_flipped = flipped;
    if (flipped) {
        OLED_Write_Cmd (0xA0);  // 段重定向：从引脚0开始 (镜像)
        OLED_Write_Cmd (0xC0);  // COM扫描方向：从0到N-1 (镜像)
    } else {
        OLED_Write_Cmd (0xA1);  // 段重定向：正常 (0xA1)
        OLED_Write_Cmd (0xC8);  // COM扫描方向：正常 (0xC8)
    }
}

// 零 Flash 占用的 Hex 打印机
void UART_SendHex (uint16_t val) {
    const char hex[] = "0123456789ABCDEF";
    // 依次发送 4 个十六进制位
    uint8_t data[4] = {hex[(val >> 12) & 0xF], hex[(val >> 8) & 0xF], hex[(val >> 4) & 0xF], hex[val & 0xF]};
    for (uint8_t i = 0; i < 4; i++) {
        while (USART_GetFlagStatus (USART1, USART_FLAG_TC) == RESET);
        USART_SendData (USART1, data[i]);
    }
    while (USART_GetFlagStatus (USART1, USART_FLAG_TC) == RESET);
    USART_SendData (USART1, ' ');  // 发个空格隔开
}

/**
 * @brief  彻底清空 OLED 屏幕上的所有像素 (硬件清除)
 */
void OLED_Clear (void) {
    uint8_t i, n;
    for (i = 0; i < 8; i++) {
        OLED_Write_Cmd (0xB0 + i);  // 设置页地址
        OLED_Write_Cmd (0x00);      // 设置起始列低 4 位
        OLED_Write_Cmd (0x10);      // 设置起始列高 4 位

        // 连续发送 128 个 0x00，清空这一页
        for (n = 0; n < 128; n++) {
            IIC_Write_Byte (OLED_ADDR, 0x40, 0x00);
        }
    }
}
