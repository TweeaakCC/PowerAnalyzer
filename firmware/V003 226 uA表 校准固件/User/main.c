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
// 极简阻塞消抖按键检测
uint8_t Check_Left_Button_Simple(void) {
    if (GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_1) == Bit_RESET) {
        Delay_Ms(20); // 硬消抖
        if (GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_1) == Bit_RESET) {
            // 等待松手，防止连按
            while(GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_1) == Bit_RESET);
            return 1; 
        }
    }
    return 0;
}
/*********************************************************************
 * @fn      main
 *
 * @brief   Main program.
 *
 * @return  none
 */
int main(void) {
    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_1);
    SystemCoreClockUpdate();
    Delay_Init();
    TIM2_Init_1ms();
    
    // 1. 先开串口
    USART_Printf_Init(2000000); //2000000 
    
    // 2. 初始化硬件
    OLED_Init();
    INA226_Init();
    INA226_Set_Rate(0);

    
    Key_Init(); // 使用这个保护 PD6 的版本

    printf("Calibration Mode Ready\r\n");

    while(1) {
        if (Check_Left_Button_Simple()) {
            INA226_Set_Shunt(current_shunt_mode == INA226_SHUNT_10mR ? INA226_SHUNT_100R : INA226_SHUNT_10mR);
            printf("Shunt Switched to: %s\r\n", current_shunt_mode == INA226_SHUNT_10mR ? "10mR" : "100R");
        }

            App_Calibration_Update(); // 发送 V, S, Mode


        // --- 3. UI 刷新 (低频，防止卡死按键) ---
        static uint16_t ui_cnt = 0;
        if (ui_cnt++ > 2000) {
            ui_cnt = 0;
            OLED_Update(App_UI_Calib_Dispatcher); 
        }
        
        // 【核心】：这里绝对不能有任何 Delay_Ms，让循环全速跑去抓按键
    }
}