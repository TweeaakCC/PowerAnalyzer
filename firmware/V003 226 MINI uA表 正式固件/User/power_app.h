#ifndef __POWER_APP_H
#define __POWER_APP_H

#include "ch32v00x.h"

extern volatile uint32_t sys_tick_ms;

// 页面枚举
typedef enum {
    UI_PAGE_STANDARD = 0, // 1. 标准：V, A, W (实时)
    UI_PAGE_CURVE    = 1, // 2. 分析仪：实时曲线 + Peek峰值
    UI_PAGE_STATS    = 2, // 3. 容量计：时间, Ah, Wh, 平均电流
} UI_Page_t;

// 导出业务数据，谁想显示谁就拿
extern int32_t v_mv, i_ua, p_mw;
extern UI_Page_t current_page;


void App_Measure_Update(void); // 数据处理中心
void App_UI_Refresh(void);    // UI 调度中心
void App_UI_Dispatcher(void); 
void App_User_Tare(void);

// 增加这个业务层的交互调度器
void App_Key_Handler(void);
void Boot_Into_PCLink_Mode(void);
uint64_t Get_System_us(void);



#endif