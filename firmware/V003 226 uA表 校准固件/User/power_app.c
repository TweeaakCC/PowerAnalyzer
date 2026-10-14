#include "power_app.h"
#include "ina226.h"
#include "oled.h"
#include <stdio.h>
#include "key.h"

//-----------------------------------------用户修改项---------------------------------//

// --- 1.电压线性校准参数 ---
// 理论值为 1250000 nV (1.25mV)
// 根据实测比例计算出的校准值为 1189000 nV
uint32_t cal_v_lsb_nv = 1188788;

//--- 2.多点位零点线性校准参数 ---
typedef struct {
    uint32_t volt_mv;
    int16_t offset;
} CalPoint_t;

// 100R (uA) 档位的地图
const CalPoint_t table_100r[] = {
    {2500,  292 },
    {3000,  340 },
    {3300,  383 },
    {3600,  444 },
    {30000, 1565},
    {36000, 1833}
};

// 10mR (A) 档位的地图
const CalPoint_t table_10mr[] = {
    {2500,  14},
    {3300,  10},
    {3600,  12},
    {5000,  9 },
    {17000, 7 },
    {36000, 9 }
};

//--- 3.阻值校准参数 --- (10mR档单位: uOhm, 100R档单位: mOhm)
#define CAL_RES_10MR       8460        // 8.460 mR
#define CAL_RES_100R       82700       // 82.700 R

//--- 4. 二极管非线性补偿常数 ---
// 值越小，补偿力度越大；值为 0 则关闭补偿
// 计算公式：补偿量 = (S_RAW^2) / diode_k_100r
#define DIODE_K_100R       3400000     // 二极管补偿
#define DIODE_K_10MR       0     // 二极管补偿

//----5. 切档
#define BACK_TO_UA_THRESHOLD 9000         // 低于此值切回ua档，单位
static uint16_t low_current_counter = 0;  // 用于计数，防止毛刺触发回切


//-----6. 上位机 PC 模式配置
#define PC_LINK_FAST_RATE 1  // 1: 使用 140us 极速采样, 0: 使用 8.24ms 高精采样
#define PC_LINK_WITH_VOLT 0  // 1: 同时采样电压和电流, 0: 只采样电流 (采样率翻倍)
#define MEASURE_LOOP_DELAY  20         // INA226匹配延时 (us)
//---------------------------------修改项截止----------------------------------//
// 放在 power_app.c 顶部，主循环直接减这两个数
int32_t running_offset_10mr = 0;
int32_t running_offset_100r = 0;

// --- 自动计算的常量系数 (编译器会在编译时算出结果，不占 CPU) ---
#define I_10MR_FACTOR      (25000000 / CAL_RES_10MR)       // 结果是 2955
#define I_100R_FACTOR      ((25000LL << 16) / CAL_RES_100R) // 定点数比例

// 0 = 使用动态零点表校准, 1 = 已手动去皮，锁定绝对零点
uint8_t user_tare_active = 0;

// 业务数据
int32_t v_mv = 0, i_ua = 0, p_mw = 0;
UI_Page_t current_page = UI_PAGE_STANDARD;

// 全局用户手动去皮变量
int32_t user_tare_offset_100r = 0;
int32_t user_tare_offset_10mr = 0;


// 内部页面处理函数原型
void Handle_Standard_Input (Key_Event_t e);
void Handle_Curve_Input (Key_Event_t e);

// 定义全局翻转标志(第一页)
uint8_t global_screen_flipped = 0;
static uint8_t tare_action_done = 0;  // 去皮动作锁
static uint8_t tare_progress = 0;     // 0-100，左键去皮进度
static uint8_t tare_flash_timer = 0;  // 成功后的“大Z”闪烁

// 在 power_app.c 顶部
static int32_t last_safe_instant_ua = 0;  // 记录最近一次有效的电流值，用于切挡致盲期填充

static int32_t i_ua_raw = 0;              // 瞬时电流 (0.1uA单位)，用于捕捉峰值
// i_ua 依然作为全局平滑电流使用

uint8_t pc_link_active = 0;

//----------------------------------------第二页开始------------------------------------//
// --- 曲线页业务变量(第二页)
typedef enum { CURVE_V = 0,
               CURVE_A,
               CURVE_W } Curve_Mode_t;

static Curve_Mode_t curve_view = CURVE_A;  // 默认看电流

// 采样历史缓冲区 (128个点 * 4字节 = 512字节，RAM 的 1/4，可以接受)
static int32_t wave_buffer[128];
static uint8_t wave_ptr = 0;

// --- 第二页页子状态 ---
typedef enum { SUB_NONE = 0,
               SUB_SET_TRIGGER } UI_SubPage_t;

// --- 第二页核心变量 ---
static uint16_t sample_counter = 0;    // 速率控制变量
static int32_t global_peek_raw = 0;    // 全局最高峰值 (140us 原始值)
static uint8_t scroll_level = 1;       // 0=快(40), 1=中(100), 2=慢(300)
static uint16_t scroll_steps[] = {300, 80, 30};
static int32_t last_raw_sample = 0;    // 记录上一次的采样点
static uint8_t valid_wave_points = 0;  // 记录缓冲区内有效数据点数
void App_Curve_Record (void);          // 第二页主声明

//----------------------------------------第三页开始------------------------------------//
// --- 统计页业务变量 ---
static uint32_t total_runtime_sec = 0;  // 总运行秒数

static int64_t energy_uas_acc = 0;      // 累积电量：单位 0.1uA * ms
static int64_t energy_mws_acc = 0;      // 累积能量：单位 mW * ms

// 转换后的结果
uint32_t stats_mah = 0;
uint32_t stats_mwh = 0;

// 2. 统计页专用变量
static uint8_t stats_running = 1;  // 1: 运行, 0: 暂停


void Handle_Stats_Input (Key_Event_t e);


static uint8_t stats_clear_progress = 0;  // 统计清零进度
static uint8_t stats_clear_done = 0;      // 清零动作锁
static uint8_t stats_clear_flash = 0;     // 清零成功反馈计时

// 定义一个静态缓冲区供 DMA 使用
uint8_t pc_buf[12];

/**
 * @brief  校准模式：串口阻塞发送 (12 字节标准 JustFloat)
 */
void App_Calibration_Update(void) {
    float f_v = (float)INA226_Get_Raw_BusV();
    float f_s = (float)INA226_Get_Raw_ShuntV();
    float f_m = (float)current_shunt_mode;

    float data[3] = {f_v, f_s, f_m};
    uint8_t *p = (uint8_t*)data;
    
    // 发送 12 字节数据
    for (uint8_t i = 0; i < 12; i++) {
        while (!(USART1->STATR & USART_FLAG_TXE));
        USART1->DATAR = p[i];
    }
    // 发送 4 字节帧尾 (00 00 80 7F)
    uint32_t tail = 0x7F800000;
    uint8_t *pt = (uint8_t*)&tail;
    for (uint8_t i = 0; i < 4; i++) {
        while (!(USART1->STATR & USART_FLAG_TXE));
        USART1->DATAR = pt[i];
    }
}

/**
 * @brief  校准模式的 UI 分发器 (供 OLED_Update 调用)
 */
void App_UI_Calib_Dispatcher(void) {
    uint16_t v_raw = INA226_Get_Raw_BusV();
    int16_t  s_raw = INA226_Get_Raw_ShuntV();

    
    // 显示档位
    if (current_shunt_mode == INA226_SHUNT_10mR) 
        OLED_ShowString(0, 0, "RES: 10mR");
    else
        OLED_ShowString(0, 0, "RES: 100R");

    // 显示原始值
    char buf[16];
    uint8_t p;
    
    OLED_ShowString(0, 20, "V_R:");
    p = int_to_str(buf, v_raw); buf[p] = '\0';
    OLED_ShowString(40, 20, buf);

    OLED_ShowString(0, 40, "S_R:");
    if (s_raw < 0) {
        buf[0] = '-';
        p = int_to_str(&buf[1], -s_raw) + 1;
    } else {
        p = int_to_str(buf, s_raw);
    }
    buf[p] = '\0';
    OLED_ShowString(40, 40, buf);
}

/**
 * @brief  校准模式：按键处理
 * 左键/右键 均可切换档位
 */
void App_Calibration_Key(void) {
    Key_Event_t e = Key_Scan();
    if (e == KEY_L_SHORT || e == KEY_R_SHORT) {
        // 物理切档
        INA226_Set_Shunt(current_shunt_mode == INA226_SHUNT_10mR ? INA226_SHUNT_100R : INA226_SHUNT_10mR);
    }
}
void App_Send_PC_DMA (int32_t v, int32_t i) {
    // 1. 状态维护
    static uint8_t pc_last_state = 0;
    if (pc_link_active && !pc_last_state) {
        pc_last_state = 1;
        DMA_Cmd (DMA1_Channel4, DISABLE);
        DMA_ClearFlag (DMA1_FLAG_TC4);
    }
    if (!pc_link_active) {
        pc_last_state = 0;
        return;
    }

    // 如果 DMA 还在搬运 (EN位为1且TC为0) 或者 串口移位寄存器还没空 (TC位为0)
    // 我们直接 return，放弃这一帧，而不是 DISABLE 它。
    if ((DMA1_Channel4->CFGR & 0x01)) {
        if (DMA_GetFlagStatus (DMA1_FLAG_TC4) == RESET)
            return;
        if (USART_GetFlagStatus (USART1, USART_FLAG_TC) == RESET)
            return;
    }

    // 2. 准备数据
    float data[2] = {(float)v, (float)i};
    uint8_t *p = (uint8_t *)data;
    for (uint8_t b = 0; b < 8; b++) pc_buf[b] = p[b];
    pc_buf[8] = 0x00;
    pc_buf[9] = 0x00;
    pc_buf[10] = 0x80;
    pc_buf[11] = 0x7F;

    // 3. 启动发送
    DMA_Cmd (DMA1_Channel4, DISABLE);
    USART_ClearFlag (USART1, USART_FLAG_TC);  // 清除串口完成标志，给下一帧判断用
    DMA_ClearFlag (DMA1_FLAG_TC4);
    DMA_SetCurrDataCounter (DMA1_Channel4, 12);
    DMA_Cmd (DMA1_Channel4, ENABLE);
}

/**
 * @brief  获取系统启动以来的总微秒数 (us)
 * @return 64位微秒时间戳
 */
uint64_t Get_System_us (void) {
    uint32_t ms;
    uint16_t us;

    // 防止在读取瞬间发生毫秒进位导致的误差
    do {
        ms = sys_tick_ms;
        us = TIM2->CNT;
    } while (ms != sys_tick_ms);

    return (uint64_t)ms * 1000 + us;
}

// 在 power_app.c 中
uint8_t Get_L_Logical_State (void) {
    uint8_t L = (GPIO_ReadInputDataBit (GPIOD, GPIO_Pin_1) == Bit_RESET);
    uint8_t R = (GPIO_ReadInputDataBit (GPIOD, GPIO_Pin_6) == Bit_RESET);
    return global_screen_flipped ? R : L;
}

uint8_t Get_R_Logical_State (void) {
    uint8_t L = (GPIO_ReadInputDataBit (GPIOD, GPIO_Pin_1) == Bit_RESET);
    uint8_t R = (GPIO_ReadInputDataBit (GPIOD, GPIO_Pin_6) == Bit_RESET);
    return global_screen_flipped ? L : R;
}

/**
 * @brief  多段线性插值引擎
 * @param  target_v: 当前测得的总线电压 (mV)
 * @return 预测的 S_RAW 底数
 */
int16_t Get_Offset_Generic (uint32_t target_v, const CalPoint_t *table, uint8_t size) {
    if (target_v <= table[0].volt_mv)
        return table[0].offset;
    if (target_v >= table[size - 1].volt_mv)
        return table[size - 1].offset;

    for (uint8_t i = 0; i < size - 1; i++) {
        if (target_v >= table[i].volt_mv && target_v <= table[i + 1].volt_mv) {
            int32_t x0 = table[i].volt_mv, x1 = table[i + 1].volt_mv;
            int32_t y0 = table[i].offset, y1 = table[i + 1].offset;
            return (int16_t)(y0 + (int32_t)(target_v - x0) * (y1 - y0) / (x1 - x0));
        }
    }
    return table[0].offset;
}

/**
 * @brief  全量程同步去皮逻辑
 * 核心思路：备份当前状态 -> 强制切到100R采集 -> 强制切到10mR采集 -> 恢复状态
 */
/**
 * @brief  工业级稳健去皮逻辑
 * 策略：档位切换后 -> 等待 100ms -> 读取 10 次并求平均
 */
void App_User_Tare (void) {
    // 1. 在阻塞开始前，先给用户一个即时的视觉确认
    tare_progress = 44;               // 强行填满
    tare_flash_timer = 15;            // 强行显示大 Z
    OLED_Update (App_UI_Dispatcher);  // ！！！手动触发一次刷新，把这一幕留在屏幕上

    INA226_Shunt_t original_mode = current_shunt_mode;
    int32_t sum_raw = 0;
    int16_t avg_raw = 0;

    // --- 1. 采集 100R 零点 ---
    INA226_Set_Shunt (INA226_SHUNT_100R);
    // 强制等待 100ms，让 INA226 内部的 16 次平均累加器彻底更新 5 轮以上
    Delay_Ms (100);

    sum_raw = 0;
    for (uint8_t i = 0; i < 10; i++) {
        sum_raw += (int16_t)IIC_Read_Reg16 (INA226_ADDR, INA226_REG_SHUNTV);
        Delay_Ms (5);  // 采样间隔
    }
    avg_raw = sum_raw / 10;

    // 更新电压，保证插值基准正确
    uint32_t v_raw_tmp = INA226_Get_Raw_BusV();
    v_mv = (uint32_t)((v_raw_tmp * (cal_v_lsb_nv / 100)) / 10000);
    user_tare_offset_100r = avg_raw;

    // --- 2. 采集 10mR 零点 ---
    INA226_Set_Shunt (INA226_SHUNT_10mR);
    // 同样给 100ms 的物理稳定期，确保“洗掉”刚才 100R 档位带来的信号残余
    Delay_Ms (100);

    sum_raw = 0;
    for (uint8_t i = 0; i < 10; i++) {
        sum_raw += (int16_t)IIC_Read_Reg16 (INA226_ADDR, INA226_REG_SHUNTV);
        Delay_Ms (5);
    }
    avg_raw = sum_raw / 10;

    user_tare_offset_10mr = avg_raw;

    // --- 3. 恢复 ---
    INA226_Set_Shunt (original_mode);
    user_tare_active = 1;   // 【新增】：标记去皮已激活，从此不再看动态表
    tare_action_done = 1;   //动画标志位
    tare_flash_timer = 15;  // 延长Z闪烁反馈，让用户知道校准还在跑
}

/**
 * @brief  数据采集与物理量转换
 */
void App_Measure_Update (void) {
    uint32_t now = Get_System_us();
    static uint8_t standard_sync_waiting = 0;  // 标准模式同步等待标志
    int32_t instant_ua = 0;


    static uint32_t last_tick = 0;
            uint32_t current_tick = sys_tick_ms;  // 维护了这个 1ms 计数值
            uint32_t dt = current_tick - last_tick;
            last_tick = sys_tick_ms;
            if (dt > 500)
                dt = 0;  // 防御性处理

        
    // 确定当前是否需要读电压/电流 (逻辑复用开关)
    uint8_t need_v = 0;
    if (pc_link_active && (PC_LINK_WITH_VOLT == 0))
        need_v = 0;
    else
        need_v = (current_page != UI_PAGE_CURVE || curve_view == CURVE_V || curve_view == CURVE_W);

    uint8_t need_i = (current_page != UI_PAGE_CURVE || curve_view == CURVE_A || curve_view == CURVE_W);

    // ==========================================
    // 1. 混合切档防御逻辑
    // ==========================================

    // --- 找到致盲和等待逻辑部分，修改为如下 ---
    if (current_rate_mode == INA226_RATE_FAST) {
        if (shunt_is_dirty) {
            shunt_is_dirty = 0;
            last_switch_us = now;
        }

        if ((now - last_switch_us) < 320) {
            if (pc_link_active) {
                App_Send_PC_DMA (v_mv, last_safe_instant_ua);
            }
            return;  // 只有在快速模式的致盲期才 return，且要带上 DMA
        }
    } else {
        if (shunt_is_dirty) {
            shunt_is_dirty = 0;
            IIC_Write_Reg16 (INA226_ADDR, INA226_REG_CONFIG, _config_reg);
            // 关键：写完配置立刻指回电流寄存器
            IIC_Write_Byte (INA226_ADDR, INA226_REG_SHUNTV, 0x00);
            standard_sync_waiting = 1;
            // 即使是这一帧，也要给上位机发个数据，不要让它断流
            if (pc_link_active)
                App_Send_PC_DMA (v_mv, last_safe_instant_ua);
            return;
        }

        if (standard_sync_waiting) {
             if (!(IIC_Read_Reg16 (INA226_ADDR, INA226_REG_MASK) & 0x0008)) {
                instant_ua = last_safe_instant_ua;
                return; // 硬件还没准备好
            }
            standard_sync_waiting = 0; // 好了，放行
            // 指针重置确保万无一失
            // if (pc_link_active)
            //     IIC_Write_Byte (INA226_ADDR, INA226_REG_SHUNTV, 0x00);
        }
    }

    // 低频更新偏移量,这样 10k 的循环里，只有 100Hz 会跑这个较慢的逻辑，其余时间主循环都是满速
    static uint32_t last_offset_update = 0;
    if (sys_tick_ms - last_offset_update >= 10) {
        if (user_tare_active) {
            running_offset_10mr = user_tare_offset_10mr;
            running_offset_100r = user_tare_offset_100r;
        } else {
            running_offset_10mr = Get_Offset_Generic (v_mv, table_10mr, 6);
            running_offset_100r = Get_Offset_Generic (v_mv, table_100r, 6);
        }
        last_offset_update = sys_tick_ms;
    }

    if(pc_link_active)Delay_Us(MEASURE_LOOP_DELAY);//主循环补偿堵塞
    
    // 1. 获取原始数据 (按需读取，节省 I2C 时间)
    if (need_v) {
        uint16_t v_raw = INA226_Get_Raw_BusV();
        v_mv = (uint32_t)((v_raw * (cal_v_lsb_nv / 100)) / 10000);
    }
    // 2. 电流计算 (区分档位)
    INA226_Shunt_t mode_at_this_moment = current_shunt_mode;  // 确定当前档位副本 (防止计算中途被中断篡改)
    if (need_i) {
        int16_t s_raw = 0;
        if (pc_link_active&& (PC_LINK_FAST_RATE == 1)) {
            s_raw = (int16_t)IIC_Read_PC_Fast_V2();
        } else {
            s_raw = (int16_t)INA226_Get_Raw_ShuntV();
        }
        // 只要读取期间发生了中断，shunt_is_dirty 必然为 1
        if (current_shunt_mode != mode_at_this_moment || shunt_is_dirty) {
            shunt_is_dirty = 1;    // 重新激活致盲
            last_switch_us = now;  // 刷新致盲时钟

            // 同样，拦截时也要给电脑发数据，防断流
            if (pc_link_active)
                App_Send_PC_DMA (v_mv, last_safe_instant_ua);
            return;
        }

        // 1. 先计算出当前的瞬时电流 (0.1uA 单位)
        if (mode_at_this_moment == INA226_SHUNT_10mR) {
            // 1. 查 10mR 地图并加上用户去皮
            // 【性能优化 2】：极简路径，没有任何 if-else
            int32_t raw_diff = s_raw - running_offset_10mr;
            if (raw_diff < 0) raw_diff = 0;
            
            // 既然 DIODE_K_10MR 为 0，编译器会自动删除这段代码
            if (DIODE_K_10MR > 0) {
                 raw_diff += (raw_diff * raw_diff) / DIODE_K_10MR; 
            }
            instant_ua = raw_diff * I_10MR_FACTOR;


            // --- 自动回切状态机 (降档) ---
            int32_t dynamic_threshold = (current_rate_mode == INA226_RATE_FAST) ? BACK_TO_UA_THRESHOLD + 2000 : BACK_TO_UA_THRESHOLD;
            if (instant_ua < dynamic_threshold) {
                low_current_counter++;
            } else {
                low_current_counter = 0;
            }

            if (low_current_counter > 3) {
                // 增加 500ms 冷却判断，sys_tick_ms 在 main.c 已定义
                static uint32_t last_downshift_tick = 0;
                if (sys_tick_ms - last_downshift_tick > 500) {
                    INA226_Set_Shunt (INA226_SHUNT_100R);
                    low_current_counter = 0;
                    IIC_Read_Reg16 (INA226_ADDR, INA226_REG_MASK);

                    // 这里的修改也是为了修复指针
                    if (pc_link_active)
                        IIC_Write_Byte (INA226_ADDR, INA226_REG_SHUNTV, 0x00);

                    shunt_is_dirty = 1;
                    last_switch_us = Get_System_us();
                    last_downshift_tick = sys_tick_ms;  // 更新冷却时间戳

                    if (pc_link_active) {
                        App_Send_PC_DMA (v_mv, last_safe_instant_ua);
                    }
                    return;
                } else {
                    low_current_counter = 0;  // 冷却期内不满足降档，清空计数防止瞬间切档
                }
            }

        }  else //100R档位
        {
         int32_t raw_diff = s_raw - running_offset_100r;
            if (raw_diff < 0) raw_diff = 0;

            if (DIODE_K_100R > 0) {
                 raw_diff += (raw_diff * raw_diff) / DIODE_K_100R; 
            }
            instant_ua = (raw_diff * I_100R_FACTOR) >> 16;
        }

        if (pc_link_active) {
            App_Send_PC_DMA (v_mv, instant_ua);
        }

        else {
            // --- 更新原始轨 (PEEK专用) ---
            i_ua_raw = instant_ua;

            // --- 瞬间对齐逻辑 (解决爬坡慢的问题) ---
            // 我们引入一个静态标志位，用来标记是否需要“重置滤波”
            static uint8_t filter_need_reset = 0;

            if (shunt_is_dirty) {
                filter_need_reset = 1;  // 档位动了，标记下一次数据出来时要对齐
            }

            if (filter_need_reset && (now - last_switch_us >= 308)) {
                // 致盲结束后的第一帧有效数据，直接覆盖旧值
                i_ua = instant_ua;
                filter_need_reset = 0;
            } else {
                // 常规滤波计算：不再使用 int64，不再除以变量
                // 根据不同模式，手动写死常数，让编译器优化成位移
                if (current_rate_mode == INA226_RATE_FAST) {
                    // 深度 32 的逻辑：(Instant + Old*31) / 32
                    i_ua = (instant_ua + (i_ua * 31)) / 32;
                } else {
                    // 深度 8 的逻辑： (Instant + Old*7) / 8
                    i_ua = (instant_ua + (i_ua * 7)) / 8;
                }
            }


            

            // 3. 功率计算 (mW)
            // 100R 档位下 i_ua 单位是 0.1uA，需要除以 10 还原

            if (need_v) {  // --- 修改 3：增加这个判断 ---
                // int32_t i_true_ua = (current_shunt_mode == INA226_SHUNT_10mR) ? i_ua : (i_ua / 10);
                // 先把电流除以 1000（从 0.1uA 变成 100uA 单位）
                // 36000 * 8000 = 288,000,000 (32 位整数范围内)
                 p_mw = (int32_t)(((uint32_t)v_mv * (uint32_t)(i_ua / 100)) / 1000);
            } else {
                p_mw = 0;  // 没读电压，不显示功率
            }


            if (stats_running && s_raw < 32760 && s_raw > -32760) {

            // --- A. 时间统计 ---
            static uint16_t ms_cnt = 0;
            ms_cnt += (uint16_t)dt;
            if (ms_cnt >= 1000) {
                total_runtime_sec++;
                ms_cnt -= 1000;
            }

            // --- B. 积分统计 (mAh) ---
            // 输入 i_ua 单位: 0.1uA | 目标 stats_mah 单位: 0.001 mAh (即 1uAh)
            // 物理换算: 1uAh = 3,600,000 uA*ms = 36,000,000 (单位为0.1uA*ms)
            // 修正后的阈值: 36,000,000
            static int32_t rem_uas = 0;
            rem_uas += (int32_t)((int64_t)i_ua * dt); // 使用 int64 防止大电流乘法溢出
            
            if (rem_uas >= 36000000) {  
                stats_mah++;           
                rem_uas -= 36000000;
            } else if (rem_uas <= -36000000) {
                if (stats_mah > 0) stats_mah--;
                rem_uas += 36000000;
            }

            // --- C. 积分统计 (mWh) ---
            // 输入 p_mw 单位: 0.01mW | 目标 stats_mwh 单位: 0.001 mWh (即 1uWh)
            // 物理换算: 1uWh = 3,600 mW*ms = 360,000 (单位为0.01mW*ms)
            // 修正后的阈值: 360,000
            static int32_t rem_mws = 0;
            rem_mws += (int32_t)((int64_t)p_mw * dt); 
            
            if (rem_mws >= 360000) {  
                stats_mwh++;
                rem_mws -= 360000;
            } else if (rem_mws <= -360000) {
                if (stats_mwh > 0) stats_mwh--;
                rem_mws += 360000;
            }
        }
        }
        if (!shunt_is_dirty && !standard_sync_waiting && (now - last_switch_us > 1000)) {
            last_safe_instant_ua = instant_ua;
            // last_safe_instant_ua = 66666;
        }
    }

    // --- 新增：每一帧测量完，立刻把数据记录到波形数组里 ---
    if (!pc_link_active)
        App_Curve_Record();
}

/**
 * @brief  业务交互中心：处理翻页和逻辑分发
 */
void App_Key_Handler (void) {
    Key_Event_t e = Key_Scan();
    if (e == KEY_EVENT_NONE)
        return;

    // --- 1. 处理全局最高优先级：双键长按翻转屏幕 ---
    if (e == KEY_BOTH_LONG) {
        global_screen_flipped = !global_screen_flipped;
        OLED_SetRotation (global_screen_flipped);
        return;  // 触发翻转后直接退出，防止误触发单键逻辑
    }

    // --- 2. 核心逻辑：按键逻辑对调 ---
    // 如果屏幕翻转了，物理上的“左”就变成了逻辑上的“右”
    if (global_screen_flipped) {
        if (e == KEY_L_SHORT)
            e = KEY_R_SHORT;
        else if (e == KEY_R_SHORT)
            e = KEY_L_SHORT;
        else if (e == KEY_L_LONG)
            e = KEY_R_LONG;
        else if (e == KEY_R_LONG)
            e = KEY_L_LONG;
    }

    // --- 3. 正常的分发逻辑 (现在 e 已经是经过纠正后的逻辑按键了) ---

    // --- 全局翻页逻辑：现在只有 3 页 (0, 1, 2) ---
    if (e == KEY_L_SHORT) {
        current_page = (current_page == 0) ? 2 : current_page - 1;
        return;
    }
    if (e == KEY_R_SHORT) {
        current_page = (current_page + 1) % 3;
        return;
    }

    // 将剩余的事件 (长按、双按) 丢给对应的页面处理器
    switch (current_page) {
    case UI_PAGE_STANDARD:
        Handle_Standard_Input (e);
        break;

    case UI_PAGE_CURVE:
        Handle_Curve_Input (e);
        break;

    case UI_PAGE_STATS:
        Handle_Stats_Input (e);
        break;
    }
}

/**
 * @brief  第一页(标准页)的专属逻辑
 */
void Handle_Standard_Input (Key_Event_t e) {
    // 1. 双击切换进入/退出 (或者是只进入)
    if (e == KEY_BOTH_SHORT) {
        if (!pc_link_active) {
            pc_link_active = 1;
            // 【新增硬件联动】：根据宏配置调整采样
            // --- 2. 在这里执行一次“临终刷新”，画好 PC 模式的静态界面 ---
            OLED_Update (App_UI_Dispatcher);
            INA226_Set_Rate (PC_LINK_FAST_RATE ? INA226_RATE_FAST : INA226_RATE_STANDARD);
            INA226_Set_Measure_Mode (PC_LINK_WITH_VOLT ? INA226_MODE_ALL : INA226_MODE_CURR_ONLY);
            // --- 核心优化：先发一次寄存器号，把 INA226 的内部指针指死在 01h ---
            IIC_Write_Byte (INA226_ADDR, INA226_REG_SHUNTV, 0x00);  // 这里的 0x00 不会被写入，仅仅是为了移动指针
            PC_Link_Start();
        }
        return;
    }

    // 2. 长按左键逻辑 (带状态识别)
    if (e == KEY_L_LONG) {
        if (pc_link_active) {
            // 如果在 PC 模式，长按左键 = 退出
            // 【新增硬件恢复】：退出 PC 模式，恢复标准 8.24ms 全采样
            INA226_Set_Rate (INA226_RATE_STANDARD);
            INA226_Set_Measure_Mode (INA226_MODE_ALL);
            PC_Link_Stop();
            pc_link_active = 0;
        } else {
            // 如果在普通模式，长按左键 = 去皮
            App_User_Tare();
        }
        return;
    }

    // 3. 右键长按切换档位 (仅在非 PC 模式生效)
    if (e == KEY_R_LONG && !pc_link_active) {
        INA226_Set_Shunt (current_shunt_mode == INA226_SHUNT_10mR ? INA226_SHUNT_100R : INA226_SHUNT_10mR);
    }
}

/**
 * @brief  渲染第一页：标准仪表盘
 * 每行 16 像素高，刚好四行占满 64 像素
 */
void Render_Standard_Page (void) {
    if (pc_link_active) {
        OLED_ShowString (110, 23, "PC");  // 在右侧中间显示 PC 字样
    }


    // --- 1. 左侧：去皮进度条 (x轴 2-10) ---
    uint8_t swL = Get_L_Logical_State();

    if (swL) {
        if (!tare_action_done && tare_flash_timer == 0) {
            if (tare_progress < 43)
                tare_progress += 1;  // 限制在 43 像素高度
        }
    } else {
        tare_progress = 0;     // 物理松手，重置进度
        tare_action_done = 0;  // 物理松手，解开动作锁 (关键修复！)
    }

    // 画左轨道外框 (y=19 到 62)
    for (uint8_t j = 19; j <= 62; j++) {
        OLED_DrawPixel (3, j, 1);
        OLED_DrawPixel (9, j, 1);
    }
    OLED_DrawPixel (4, 62, 1);
    OLED_DrawPixel (5, 62, 1);
    OLED_DrawPixel (6, 62, 1);
    OLED_DrawPixel (7, 62, 1);
    OLED_DrawPixel (8, 62, 1);

    // 画内部进度条 (y 从 61 向上涨)
    for (uint8_t j = 0; j < tare_progress; j++) {
        for (uint8_t i = 4; i <= 8; i++) OLED_DrawPixel (i, 61 - j, 1);
    }

    // 同轴顶部字母显示
    if (tare_flash_timer > 0) {
        OLED_ShowChar_9x18 (2, 0, 'Z');  // 大 Z 居中
        tare_flash_timer--;
    } else {
        OLED_ShowChar_9x18 (2, -1, 'z');  // 小 Z 居中
    }
    // ==========================================
    // 2. 中间：数值区 (向左微调 10px 达到视觉居中)
    // ==========================================
    const uint8_t mid_x = 28;
    OLED_ShowFixedNum (mid_x, 0, v_mv, 3, "V");

    int32_t abs_i = (i_ua < 0) ? -i_ua : i_ua;
    if (abs_i < 10000) {
        if (abs_i < 100)
            OLED_ShowFixedNum (mid_x, 21, i_ua, 1, " uA");
        else if (abs_i >= 100 && abs_i < 1000)
            OLED_ShowFixedNum (mid_x, 21, i_ua, 1, " uA");
        else if (abs_i >= 1000)
            OLED_ShowFixedNum (mid_x, 21, i_ua, 1, "uA");
    }

    else if (abs_i < 10000000)
        if (abs_i < 100000) {
            OLED_ShowFixedNum (mid_x, 21, i_ua / 10, 3, "mA");
        } else if (abs_i < 100000) {
        OLED_ShowFixedNum (mid_x, 21, i_ua / 100, 2, "mA");
        }else  {
            OLED_ShowFixedNum (mid_x, 21, i_ua / 1000, 1, "mA");
        }


    else
        OLED_ShowFixedNum (mid_x, 21, i_ua / 10000, 3, "A");


    int32_t abs_p = (p_mw < 0) ? -p_mw : p_mw;

    if (abs_p < 100000) { // 小于 1000.00 mW
        if (abs_p < 1000) // < 10.00 mW
            OLED_ShowFixedNum (mid_x, 42, p_mw, 2, "mW");
        else if (abs_p < 10000) // < 100.00 mW
            OLED_ShowFixedNum (mid_x, 42, p_mw, 2, "mW");
        else // 100.00mW ~ 999.99mW
            OLED_ShowFixedNum (mid_x, 42, p_mw/10, 1, "mW");
    } 
    else {
        // 大于 1W，显示为 W，保留 3 位小数
        // p_mw 是 0.01mW 单位，除以 10 变成 0.1mW 单位，
        // ShowFixedNum 使用 4 位精度（对应 0.0001 缩放）或 3 位
        // 这里建议统一到 4 位显示 1.2345 W 或者 3 位 1.234 W
        if (abs_p < 1000000) // < 10W
            OLED_ShowFixedNum (mid_x, 42, p_mw / 100, 3, " W");
        else
            OLED_ShowFixedNum (mid_x, 42, p_mw / 100, 3, "W");
    }

    // --- 3. 右侧：量程同轴指示 (x轴 117-125) ---
    // 顶部 u, 底部 A (x=117 保证 9px 字符中点在 121)
    OLED_ShowChar_9x18 (116, -1, 'u');
    OLED_ShowChar_9x18 (117, 44, 'A');

    // 轨道外框 (y=19 到 44)
    for (uint8_t j = 19; j <= 44; j++) {
        OLED_DrawPixel (118, j, 1);
        OLED_DrawPixel (124, j, 1);
    }

    // 内部滑块 (Slider)
    if (current_shunt_mode == INA226_SHUNT_100R) {
        // 滑块在靠上的位置 (y=19附近)
        for (uint8_t j = 19; j <= 25; j++)
            for (uint8_t i = 119; i <= 123; i++) OLED_DrawPixel (i, j, 1);
    } else {
        // 滑块在靠下的位置 (y=38附近)
        for (uint8_t j = 38; j <= 44; j++)
            for (uint8_t i = 119; i <= 123; i++) OLED_DrawPixel (i, j, 1);
    }
}

/**
 * @brief  波形记录逻辑 (在 App_Measure_Update 结尾调用)
 */
void App_Curve_Record (void) {
    int32_t current_raw;
    if (curve_view == CURVE_V)
        current_raw = v_mv;
    else if (curve_view == CURVE_A)
        current_raw = i_ua;
    else
        current_raw = p_mw/100;


    int32_t current_raw_raw;
    if (curve_view == CURVE_V)
        current_raw_raw = v_mv;
    else if (curve_view == CURVE_A)
        current_raw_raw = i_ua_raw;
    else
        current_raw_raw = p_mw/100;


    if (current_raw_raw > global_peek_raw) {
        global_peek_raw = current_raw_raw;
    }
    last_raw_sample = current_raw;  // 更新历史记录


    sample_counter++;
    if (sample_counter >= scroll_steps[scroll_level]) {
        sample_counter = 0;
        wave_buffer[wave_ptr] = current_raw;
        wave_ptr = (wave_ptr + 1) % 128;

        // --- 核心修正：仅在未满 128 时增加计数 ---
        if (valid_wave_points < 128) {
            valid_wave_points++;
        }
    }
}

/**
 * @brief  辅助函数：根据模式自动缩放单位并显示
 */
void render_slot (uint8_t x, uint8_t y, int32_t val) {
    char buf[12];
    uint8_t p = 0;
    OLED_ShowString (x, y, "      "); // 清行

    if (curve_view == CURVE_V) {
        // 电压特例手动拼接：4.39V 或 36.0V (不使用 ShowFixedNum 防止空格)
        if (val < 10000) { 
            // 4.39V 逻辑 (输入单位mV)
            uint32_t v = val / 10; // 439
            p = int_to_str(buf, v / 100); // 整数部分 "4"
            buf[p++] = '.';
            buf[p++] = ((v / 10) % 10) + '0'; // 小数第一位 "3"
            buf[p++] = (v % 10) + '0';         // 小数第二位 "9"
        } else { 
            // 36.0V 逻辑
            uint32_t v = val / 100; // 360
            p = int_to_str(buf, v / 10); // "36"
            buf[p++] = '.';
            buf[p++] = (v % 10) + '0';    // "0"
        }
        buf[p++] = 'V';
    } 
    else if (curve_view == CURVE_A) {
        int32_t abs_v = (val < 0) ? -val : val;
        if (abs_v < 10000) { 
            p = int_to_str(buf, val / 10);
            buf[p++] = 'u'; buf[p++] = 'A';
        } else if (abs_v < 10000000) { 
            p = int_to_str(buf, val / 10000);
            buf[p++] = 'm'; buf[p++] = 'A';
        } else {
            // 电流大于 1A 的特例也可以手动拼，防止 A 前面出空格
            uint32_t v = val / 100000; // 如 1.23A 对应 123
            p = int_to_str(buf, v / 100);
            buf[p++] = '.';
            buf[p++] = ((v / 10) % 10) + '0';
            buf[p++] = (v % 10) + '0';
            buf[p++] = 'A';
        }
    } 
    else {
        // 功率同理
        int32_t abs_v = (val < 0) ? -val : val;
        if (abs_v < 1000) {
            p = int_to_str(buf, val);
            buf[p++] = 'm'; buf[p++] = 'W';
        } else {
            uint32_t v = val / 10; // 如 1.23W 对应 123
            p = int_to_str(buf, v / 100);
            buf[p++] = '.';
            buf[p++] = ((v / 10) % 10) + '0';
            buf[p++] = (v % 10) + '0';
            buf[p++] = 'W';
        }
    }
    buf[p] = '\0';
    OLED_ShowString(x, y, buf);
}

/**
 * @brief  第二页(曲线页)渲染逻辑优化
 */
void Render_Curve_Page (void) {
    // 1. 累加当前已存入的所有有效点
    int32_t sum = 0;
    for (uint8_t i = 0; i < valid_wave_points; i++) {
        sum += wave_buffer[i];
    }
    
    // 关键修复：除数随有效点数变化，实现瞬间复位
    int32_t avg_val = (valid_wave_points > 0) ? (sum / (int32_t)valid_wave_points) : 0;

    // 2. 获取最新值 (环形缓冲区的前一个位置)
    int32_t latest_smooth = (valid_wave_points > 0) ? wave_buffer[(wave_ptr + 127) % 128] : 0;

    // --- 3. 渲染数值 ---
    render_slot (0, 6, global_peek_raw);
    render_slot (0, 23, latest_smooth);
    render_slot (0, 40, avg_val);

    // 速度指示
    char spd_buf[4] = {'S', (char)('0' + scroll_level + 1), '\0'};
    OLED_ShowString (110, 48, spd_buf);

    // --- 4. 绘制波形 (代码维持极简) ---
    int32_t range = global_peek_raw;
    if (range < 100) range = 100;

    for (uint8_t i = 0; i < valid_wave_points; i++) {
        // x 从 127 开始向左绘制
        uint8_t x = 127 - i;
        // 数据从最新(wave_ptr-1)开始往旧取
        uint8_t buf_idx = (wave_ptr + 128 - 1 - i) % 128;
        int32_t val = wave_buffer[buf_idx];

        int32_t y_mapped = 63 - (val * 63 / range); // 已移除强制 64 位，保证速度
        if (y_mapped < 0) y_mapped = 0;
        else if (y_mapped > 63) y_mapped = 63;
        OLED_DrawPixel (x, (uint8_t)y_mapped, 1);
    }
}

void Handle_Curve_Input (Key_Event_t e) {
    // L+R 双键：切换 V / A / W
    if (e == KEY_BOTH_SHORT) {
        curve_view = (Curve_Mode_t)((curve_view + 1) % 3);
        for (uint8_t i = 0; i < 128; i++) wave_buffer[i] = 0;
        // 【核心修复】：按键触发时才写一次 I2C 寄存器
        if (curve_view == CURVE_V) {
            INA226_Set_Measure_Mode (INA226_MODE_VOLT_ONLY);
        } else if (curve_view == CURVE_A) {
            INA226_Set_Measure_Mode (INA226_MODE_CURR_ONLY);
        } else {
            INA226_Set_Measure_Mode (INA226_MODE_ALL);
        }

        // 切换后清空一下
        global_peek_raw = 0;
        valid_wave_points = 0;
        wave_ptr = 0;
        for (uint8_t i = 0; i < 128; i++) wave_buffer[i] = 0;
        return;
    }

    // 左键长按：清除 PEEK (归零)
    if (e == KEY_L_LONG) {
        // 1. 重置峰值
        global_peek_raw = 0;

        // 2. 彻底清空缓冲区
        for (uint8_t i = 0; i < 128; i++) wave_buffer[i] = 0;

        // 3. --- 核心修正：重置有效点数记录 ---
        // 这会让 Render_Curve_Page 重新从 /1, /2... 开始计算平均值
        valid_wave_points = 0;
        wave_ptr = 0;
    }

    // 右键长按：三档循环切速
    if (e == KEY_R_LONG) {
        scroll_level = (scroll_level + 1) % 3;
    }
}

/**
 * @brief  第三页(统计页)专属逻辑
 */
void Handle_Stats_Input (Key_Event_t e) {
    // --- 核心：双击切换 数字/曲线 视图 ---
    if (e == KEY_BOTH_SHORT) {
    }


    // --- 左键长按：清零数据 (对应左侧进度条) ---
    if (e == KEY_L_LONG) {
        // 先手动刷一次满格画面，防止卡顿感
        stats_clear_progress = 43;
        stats_clear_flash = 15;
        OLED_Update (App_UI_Dispatcher);

        // 执行清零
        energy_uas_acc = 0;
        energy_mws_acc = 0;
        total_runtime_sec = 0;
        stats_mah = 0;
        stats_mwh = 0;

        stats_clear_done = 1;  // 挂上动作锁
    }

    // --- 右键长按：暂停/开始统计 (对应滑块 R/S 移动) ---
    if (e == KEY_R_LONG) {
        stats_running = !stats_running;
    }
}

void Render_Stats_Page (void) {

    // 1. 左侧：清零进度条 (c -> C)
    uint8_t swL = Get_L_Logical_State();

    if (swL) {
        if (!stats_clear_done && stats_clear_flash == 0) {
            if (stats_clear_progress < 43)
                stats_clear_progress += 1;
        }
    } else {
        stats_clear_progress = 0;
        stats_clear_done = 0;
    }

    // 绘制左导轨 (x轴坐标 3, 9 与第一页对齐)
    for (uint8_t j = 19; j <= 62; j++) {
        OLED_DrawPixel (3, j, 1);
        OLED_DrawPixel (9, j, 1);
    }
    OLED_DrawPixel (4, 62, 1);
    OLED_DrawPixel (5, 62, 1);
    OLED_DrawPixel (6, 62, 1);
    OLED_DrawPixel (7, 62, 1);
    OLED_DrawPixel (8, 62, 1);

    // 绘制内部进度条
    for (uint8_t j = 0; j < stats_clear_progress; j++) {
        for (uint8_t i = 4; i <= 8; i++) OLED_DrawPixel (i, 61 - j, 1);
    }

    // 顶部状态提示：c 代表 clear 准备中，C 代表已清除
    if (stats_clear_flash > 0) {
        OLED_ShowChar_9x18 (2, 0, 'C');
        stats_clear_flash--;
    } else {
        // 显示小写 c
        OLED_ShowChar_9x18 (2, -1, 'c');
    }


    // ==========================================
    // 2. 中间：统计数据 (坐标与第一页对齐)
    // ==========================================
    char time_str[16];


    uint8_t p = 0;  // 定义一个指针偏移量

    uint16_t h = total_runtime_sec / 3600;
    uint8_t m = (total_runtime_sec % 3600) / 60;
    uint8_t s = total_runtime_sec % 60;

    // 手动复刻 %02d:%02d:%02d
    if (h < 100) {
        int_to_str_fixed (&time_str[p], h, 2);
        p += 2;
    } else {
        p += int_to_str (&time_str[p], h);
    }

    time_str[p++] = ':';
    int_to_str_fixed (&time_str[p], m, 2);
    p += 2;

    time_str[p++] = ':';
    int_to_str_fixed (&time_str[p], s, 2);
    p += 2;

    time_str[p] = '\0';  // 结束符

    OLED_ShowString (26, 0, time_str);

    // 2. 累积电量：mAh 与 Ah 智能切换
    if (stats_mah < 100000) {
        // 小于 100 mAh，显示 mAh (带3位小数，即 0.001 mAh 分辨率)
        OLED_ShowFixedNum (26, 21, stats_mah / 10, 2, "mAh");
    } else if (stats_mah < 1000000) {
        // 小于 1000 mAh，显示 mAh (带2位小数，即 0.01 mAh 分辨率)
        OLED_ShowFixedNum (26, 21, stats_mah / 100, 1, "mAh");
    } else {
        // 大于 1000 mAh，切换到 Ah
        // stats_mah/1000 得到的是 0.001 Ah 为单位的整数
        OLED_ShowFixedNum (26, 21, stats_mah / 1000, 3, "Ah");
    }

    // 3. 累积能量：mWh 与 Wh 智能切换
    if (stats_mwh < 100000) {
        // 小于 100 mWh，显示 mWh
        OLED_ShowFixedNum (26, 42, stats_mwh / 10, 2, "mWh");
    } else if (stats_mwh < 1000000) {
        // 小于 1000 mWh，显示 mWh
        OLED_ShowFixedNum (26, 42, stats_mwh / 100, 1, "mWh");
    } else {
        // 大于 1000 mWh (即 1 Wh)，显示 Wh
        OLED_ShowFixedNum (26, 42, stats_mwh / 1000, 3, "Wh");
    }


    // 3. 右侧：运行状态拨杆 (R在下，S在上)
    // 轨道外框 (x=117-125)
    for (uint8_t j = 19; j <= 44; j++) {
        OLED_DrawPixel (118, j, 1);
        OLED_DrawPixel (124, j, 1);
    }

    // 标签位置：105 坐标是你微调后的
    OLED_ShowChar_9x18 (116, 0, 'S');   // 停止状态在顶
    OLED_ShowChar_9x18 (117, 44, 'R');  // 运行状态在底

    // 内部滑块 (根据 stats_running 变量)
    if (stats_running) {
        // 运行状态：滑块沉在底部 'R' 附近
        for (uint8_t j = 38; j <= 44; j++)
            for (uint8_t i = 119; i <= 123; i++) OLED_DrawPixel (i, j, 1);
    } else {
        // 停止状态：滑块升到顶部 'S' 附近
        for (uint8_t j = 19; j <= 25; j++)
            for (uint8_t i = 119; i <= 123; i++) OLED_DrawPixel (i, j, 1);
    }
}

/**
 * @brief  UI 总调度
 */
void App_UI_Dispatcher (void) {
    if (pc_link_active) {
        OLED_Clear();                       // 如果 Flash 够，可以画个漂亮的图标
        OLED_ShowChar_9x18 (117, 44, 'R');  // 运行状态在底
        return;                             // 后面的三页渲染全部跳过
    }

    static UI_Page_t last_page_snapshot = 0xFF;

    if (current_page != last_page_snapshot) {
        if (current_page == UI_PAGE_CURVE) {
            INA226_Set_Rate (INA226_RATE_FAST);

        } else {
            INA226_Set_Rate (INA226_RATE_STANDARD);
        }
        last_page_snapshot = current_page;
    }


    switch (current_page) {
    case UI_PAGE_STANDARD:
        Render_Standard_Page();
        break;

    case UI_PAGE_CURVE:
        Render_Curve_Page();
        break;

    case UI_PAGE_STATS:
        Render_Stats_Page();
        break;
    }
}
