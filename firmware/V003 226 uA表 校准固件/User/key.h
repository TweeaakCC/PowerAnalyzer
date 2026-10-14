#ifndef __KEY_H
#define __KEY_H

#include "ch32v00x.h"

// ==========================================================
// 核心配置宏：控制系统是否处于调试模式
// ==========================================================
// 1 = 开启串口，禁用 SW2 (引脚1) 按键功能
// 0 = 禁用串口，启用 SW2 (引脚1) 按键功能
#define SYSTEM_DEBUG_MODE  0


// 定义按键事件枚举
typedef enum {
    KEY_EVENT_NONE = 0,
    KEY_L_SHORT, KEY_L_LONG,    // 左键 (SW1)
    KEY_R_SHORT, KEY_R_LONG,    // 右键 (SW2)
    KEY_BOTH_SHORT, KEY_BOTH_LONG // 双键组合
} Key_Event_t;

// 函数声明
void Key_Init(void);
Key_Event_t Key_Scan(void); // 放在主循环里

/**
 * @brief  进入上位机模式：关闭 PD6 按键，开启串口
 */
void PC_Link_Start(void);

/**
 * @brief  退出上位机模式：关闭串口物理连接，恢复 PD6 为上拉输入按键
 */
void PC_Link_Stop(void);

#endif