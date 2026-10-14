/********************************** (C) COPYRIGHT *******************************
 * File Name          : main.c
 * Author             : WCH
 * Version            : V1.0.0
 * Date               : 2023/12/25
 * Description        : Main program body.
 *********************************************************************************
 * Copyright (c) 2021 Nanjing Qinheng Microelectronics Co., Ltd.
 * Attention: This software (modified or not) and binary are used for
 * microcontroller manufactured by Nanjing Qinheng Microelectronics.
 *******************************************************************************/

/*
 *@Note
 *USART Print debugging routine:
 *USART1_Tx(PD6).
 *This example demonstrates the use of USART1(PD6) as a print debug port output.
 *
 */

#include "debug.h"
#include "iic.h"
#include "oled.h"
#include "ina226.h"
#include "power_app.h"
#include "key.h"
#include <stdio.h>

/* Global typedef */

/* Global define */

/* Global Variable */
// 定义全局毫秒计数值
volatile uint32_t sys_tick_ms = 0;
extern uint8_t pc_link_active;  // 引入业务层的标志位

void TIM2_Init_1ms (void) {
    TIM_TimeBaseInitTypeDef TIM_TimeBaseStructure = {0};
    NVIC_InitTypeDef NVIC_InitStructure = {0};

    // 1. 开启 TIM2 时钟
    RCC_APB1PeriphClockCmd (RCC_APB1Periph_TIM2, ENABLE);

    // 2. 配置定时器参数
    // 我们主频是 48MHz。
    // 频率 = 48MHz / (Prescaler + 1) / (Period + 1)
    // 设定 1ms 触发一次：48MHz / 48 / 1000 = 1000Hz (1ms)
    TIM_TimeBaseStructure.TIM_Period = 1000 - 1;   // 自动重装载值
    TIM_TimeBaseStructure.TIM_Prescaler = 48 - 1;  // 预分频
    TIM_TimeBaseStructure.TIM_ClockDivision = TIM_CKD_DIV1;
    TIM_TimeBaseStructure.TIM_CounterMode = TIM_CounterMode_Up;
    TIM_TimeBaseInit (TIM2, &TIM_TimeBaseStructure);

    // 3. 开启更新中断
    TIM_ITConfig (TIM2, TIM_IT_Update, ENABLE);

    // 4. 配置 NVIC 中断优先级
    NVIC_InitStructure.NVIC_IRQChannel = TIM2_IRQn;
    NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 1;  // 优先级略低于 ALERT 中断
    NVIC_InitStructure.NVIC_IRQChannelSubPriority = 1;
    NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init (&NVIC_InitStructure);

    // 5. 启动定时器
    TIM_Cmd (TIM2, ENABLE);
}

/*********************************************************************
 * @fn      main
 *
 * @brief   Main program.
 *
 * @return  none
 */
int main (void) {
    NVIC_PriorityGroupConfig (NVIC_PriorityGroup_1);
    SystemCoreClockUpdate();
    Delay_Init();
    TIM2_Init_1ms(); 
    Delay_Ms (2000);


    // 2. 硬件外设初始化

    // OLED_Init();
    IIC_Init();    
    INA226_Init();  
    Key_Init();     // 必须在最后调用，因为会锁死 SWD
    Boot_Into_PCLink_Mode();

    while (1) {
        // --- 任务 1：数据采集 (全速) ---
        App_Measure_Update();
        // 2. 按键与交互处理 (内部功能分配)
        static uint32_t last_key_ms = 0;
        if (sys_tick_ms - last_key_ms >= 10) {
            App_Key_Handler();
            last_key_ms = sys_tick_ms;
        }

    }
}