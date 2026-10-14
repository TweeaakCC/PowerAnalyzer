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
// ����ȫ�ֺ������ֵ
volatile uint32_t sys_tick_ms = 0;
extern uint8_t pc_link_active;  // ����ҵ���ı�־λ

void TIM2_Init_1ms (void) {
    TIM_TimeBaseInitTypeDef TIM_TimeBaseStructure = {0};
    NVIC_InitTypeDef NVIC_InitStructure = {0};

    // 1. ���� TIM2 ʱ��
    RCC_APB1PeriphClockCmd (RCC_APB1Periph_TIM2, ENABLE);

    // 2. ���ö�ʱ������
    // ������Ƶ�� 48MHz��
    // Ƶ�� = 48MHz / (Prescaler + 1) / (Period + 1)
    // �趨 1ms ����һ�Σ�48MHz / 48 / 1000 = 1000Hz (1ms)
    TIM_TimeBaseStructure.TIM_Period = 1000 - 1;   // �Զ���װ��ֵ
    TIM_TimeBaseStructure.TIM_Prescaler = 48 - 1;  // Ԥ��Ƶ
    TIM_TimeBaseStructure.TIM_ClockDivision = TIM_CKD_DIV1;
    TIM_TimeBaseStructure.TIM_CounterMode = TIM_CounterMode_Up;
    TIM_TimeBaseInit (TIM2, &TIM_TimeBaseStructure);

    // 3. ���������ж�
    TIM_ITConfig (TIM2, TIM_IT_Update, ENABLE);

    // 4. ���� NVIC �ж����ȼ�
    NVIC_InitStructure.NVIC_IRQChannel = TIM2_IRQn;
    NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 1;  // ���ȼ��Ե��� ALERT �ж�
    NVIC_InitStructure.NVIC_IRQChannelSubPriority = 1;
    NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init (&NVIC_InitStructure);

    // 5. ������ʱ��
    TIM_Cmd (TIM2, ENABLE);
}
// �������������������
uint8_t Check_Left_Button_Simple(void) {
    if (GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_1) == Bit_RESET) {
        Delay_Ms(20); // Ӳ����
        if (GPIO_ReadInputDataBit(GPIOD, GPIO_Pin_1) == Bit_RESET) {
            // �ȴ����֣���ֹ����
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
    
    // 1. �ȿ�����
    USART_Printf_Init(2000000); //2000000 
    
    // 2. ��ʼ��Ӳ��
    // OLED_Init();
    IIC_Init();       // �ײ�Ӳ�� I2C ��ʼ��
    INA226_Init();
    INA226_Set_Rate(0);

    
    Key_Init(); // ʹ��������� PD6 �İ汾

    printf("Calibration Mode Ready\r\n");

    while(1) {
        if (Check_Left_Button_Simple()) {
            INA226_Set_Shunt(current_shunt_mode == INA226_SHUNT_10mR ? INA226_SHUNT_100R : INA226_SHUNT_10mR);
            printf("Shunt Switched to: %s\r\n", current_shunt_mode == INA226_SHUNT_10mR ? "10mR" : "100R");
        }
            App_Calibration_Update(); // ���� V, S, Mode
    }
}