#include "key.h"
#include "iic.h"

// ==========================================================
// 按键物理引脚定义
// SW1 = 引脚 8 (PD1) - 原 SWDIO
// SW2 = 引脚 1 (PD6) - 原 TX
// ==========================================================
#define PORT_SW1   GPIOD
#define PIN_SW1    GPIO_Pin_1

#define PORT_SW2   GPIOD
#define PIN_SW2    GPIO_Pin_6

#define LONG_PRESS_TIME  5

extern uint8_t pc_link_active; // 引入业务层的标志位

/**
 * @brief  初始化按键引脚
 * @note   包含高危操作：解除 SWD 和重置 TX
 */
void Key_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStructure = {0};

    // 开启 GPIOD 和复用功能 (AFIO) 的时钟
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOD | RCC_APB2Periph_AFIO, ENABLE);

    // ==========================================
    // 1. 初始化 SW1 (引脚8 / PD1)
    // ==========================================
    // 警告：执行此句后，调试器将断开连接！
    // 必须确保 main 开头有 Delay_Ms(2000); 逃生延时
    GPIO_PinRemapConfig(GPIO_Remap_SDI_Disable, ENABLE);

    GPIO_InitStructure.GPIO_Pin = PIN_SW1;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU; // 上拉输入 (按下为低电平)
    GPIO_Init(PORT_SW1, &GPIO_InitStructure);

    // ==========================================
    // 2. 根据宏定义初始化 SW2 (引脚1 / PD6)
    // ==========================================
#if (SYSTEM_DEBUG_MODE == 0)
    // // 发布模式：PD6 作为普通上拉输入按键
    // GPIO_InitStructure.GPIO_Pin = PIN_SW2;
    // GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU; 
    // GPIO_Init(PORT_SW2, &GPIO_InitStructure);
#else
    // 调试模式：PD6 已经在 USART_Printf_Init 中被配置为 TX 了
    // 这里什么都不做，保护串口功能
#endif
}

/**
 * @brief  非阻塞按键状态机扫描
 * @note   必须在主循环中以固定的时间间隔（如 10ms）调用
 * @return 发生的按键事件 (KEY_EVENT_NONE 表示无事发生)
 */
Key_Event_t Key_Scan(void)
{
    static uint8_t  state = 0;
    static uint16_t timer = 0;
    static uint8_t  latched_keys = 0; 
    Key_Event_t event = KEY_EVENT_NONE;

    uint8_t L = (GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_1) == Bit_RESET);

    uint8_t R = 0;

    // 只有在非 PC 模式下才去读取引脚 6 的状态
    if (!pc_link_active) {
        R = (GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_6) == Bit_RESET); // 删掉前面的 uint8_t
    }


    switch (state)
    {
        case 0: // 空闲态
            if (L || R) {
                // --- 核心优化点：取消消抖状态，直接进入压持判定 ---
                state = 2; 
                timer = 0;
                latched_keys = 0;
                if (L) latched_keys |= 0x01;
                if (R) latched_keys |= 0x02;
            }
            break;

        case 2: // 压持判断 (这里不阻塞，每轮循环 timer + 1)
            if (L || R) {
                timer++;
                if (L) latched_keys |= 0x01;
                if (R) latched_keys |= 0x02;

                // 立即判定长按
                if (timer >= LONG_PRESS_TIME) {
                    if ((latched_keys & 0x03) == 0x03) event = KEY_BOTH_LONG;
                    else if (latched_keys & 0x01) event = KEY_L_LONG;
                    else if (latched_keys & 0x02) event = KEY_R_LONG;
                    state = 3; // 进入等待释放
                }
            } else {
                // --- 抬手判定短按：只要发生过按下，就给事件 ---
                if (timer < LONG_PRESS_TIME) {
                    if ((latched_keys & 0x03) == 0x03) event = KEY_BOTH_SHORT;
                    else if (latched_keys & 0x01) event = KEY_L_SHORT;
                    else if (latched_keys & 0x02) event = KEY_R_SHORT;
                }
                state = 0;
            }
            break;

        case 3: // 等待全部释放态
            if (!L && !R) state = 0;
            break;
    }
    return event;
}

extern uint8_t pc_buf[12]; 

void UART1_DMA_Init(void) {
    DMA_InitTypeDef DMA_InitStructure = {0};
    
    // 1. 开启时钟
    RCC_AHBPeriphClockCmd(RCC_AHBPeriph_DMA1, ENABLE);

    // 2. 彻底复位 Channel 4 (USART1_TX)
    DMA_DeInit(DMA1_Channel4);

    // 3. 配置目的地：串口数据寄存器
    DMA_InitStructure.DMA_PeripheralBaseAddr = (uint32_t)&USART1->DATAR;
    // 4. 配置源：我们的 12 字节缓冲区
    DMA_InitStructure.DMA_MemoryBaseAddr = (uint32_t)pc_buf;
    // 5. 方向：内存 -> 外设 (Peripheral Destination)
    DMA_InitStructure.DMA_DIR = DMA_DIR_PeripheralDST;
    // 6. 长度：12 字节
    DMA_InitStructure.DMA_BufferSize = 12;
    // 7. 配置增量：外设不加，内存自增
    DMA_InitStructure.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    DMA_InitStructure.DMA_MemoryInc = DMA_MemoryInc_Enable;
    // 8. 数据宽度：全是 Byte
    DMA_InitStructure.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    DMA_InitStructure.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    // 9. 模式：正常模式 (发一次停一次，方便我们手动触发)
    DMA_InitStructure.DMA_Mode = DMA_Mode_Normal;
    DMA_InitStructure.DMA_Priority = DMA_Priority_VeryHigh;
    DMA_InitStructure.DMA_M2M = DMA_M2M_Disable;
    
    DMA_Init(DMA1_Channel4, &DMA_InitStructure);
    
    // --- 核心修复：必须通知 USART1 开启 DMA 传送能力 ---
    USART1->CTLR3 |= USART_DMAReq_Tx; 
}

/**
 * @brief  进入上位机模式：关闭 PD6 按键，开启高速串口
 */
void PC_Link_Start(void)
{
    // 强制复位串口
    RCC_APB2PeriphResetCmd(RCC_APB2Periph_USART1, ENABLE);
    RCC_APB2PeriphResetCmd(RCC_APB2Periph_USART1, DISABLE);

    USART_Printf_Init(1500000); 
    
    // 确保此时发送端是关着的
    USART1->CTLR3 &= ~USART_DMAReq_Tx;
    
    UART1_DMA_Init();
    
    // 最后开启串口的 DMA 请求
    USART1->CTLR3 |= USART_DMAReq_Tx; 
}

/**
 * @brief  退出上位机模式：关闭串口物理连接，恢复 PD6 为上拉输入按键
 */
void PC_Link_Stop(void)
{
    // 彻底杀掉所有状态
    DMA_Cmd(DMA1_Channel4, DISABLE);
    USART_Cmd(USART1, DISABLE);
    USART1->CTLR3 &= ~USART_DMAReq_Tx;
    DMA_ClearFlag(DMA1_FLAG_GL4);

    GPIO_InitTypeDef GPIO_InitStructure = {0};
    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_6;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IPU; 
    GPIO_Init(GPIOD, &GPIO_InitStructure);
    IIC_Init(); 
}