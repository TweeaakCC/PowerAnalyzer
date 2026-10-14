/********************************** (C) COPYRIGHT *******************************
 * File Name          : ch32v00x_it.c
 * Author             : WCH
 * Version            : V1.0.0
 * Date               : 2023/12/25
 * Description        : Main Interrupt Service Routines.
*********************************************************************************
* Copyright (c) 2021 Nanjing Qinheng Microelectronics Co., Ltd.
* Attention: This software (modified or not) and binary are used for 
* microcontroller manufactured by Nanjing Qinheng Microelectronics.
*******************************************************************************/
#include <ch32v00x_it.h>
#include "ina226.h" // 引入为了操作引脚
#include "power_app.h"

// extern 刚才那个 Set_Shunt 函数，让中断能调用它
extern void INA226_Set_Shunt(INA226_Shunt_t shunt);

extern volatile uint32_t sys_tick_ms; // 声明 main.c 里的变量
void TIM2_IRQHandler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
void NMI_Handler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
void HardFault_Handler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
void TIM2_IRQHandler(void)
{
    if (TIM_GetITStatus(TIM2, TIM_IT_Update) != RESET)
    {
        sys_tick_ms++; // 毫秒累加
        TIM_ClearITPendingBit(TIM2, TIM_IT_Update); // 清除标志位
    }
}
/**
 * @brief  外部中断服务函数 (0-7线共用)
 */
void EXTI7_0_IRQHandler(void) __attribute__((interrupt("WCH-Interrupt-fast")));

void EXTI7_0_IRQHandler(void)
{
    // 检查是否是 Line 2 (PA2) 触发
    if (EXTI_GetITStatus(EXTI_Line2) != RESET)
    {
        // 1. 物理切挡 (最快速度保命)
        GPIOC->BSHR = GPIO_Pin_4; 
        
        // 2. ！！！立起脏数据标记 ！！！
        shunt_is_dirty = 1;
        current_shunt_mode = INA226_SHUNT_10mR;

        EXTI_ClearITPendingBit(EXTI_Line2);
    }
}


/*********************************************************************
 * @fn      NMI_Handler
 *
 * @brief   This function handles NMI exception.
 *
 * @return  none
 */
void NMI_Handler(void)
{
  while (1)
  {
  }
}

/*********************************************************************
 * @fn      HardFault_Handler
 *
 * @brief   This function handles Hard Fault exception.
 *
 * @return  none
 */
void HardFault_Handler(void)
{
  NVIC_SystemReset();
  while (1)
  {
  }
}


