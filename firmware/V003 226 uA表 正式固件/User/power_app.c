#include "power_app.h"
#include "ina226.h"
#include "oled.h"
#include <stdio.h>
#include "key.h"

//--- 2.多点位零点线性校准参数 ---
typedef struct {
    uint32_t volt_mv;
    int16_t offset;
} CalPoint_t;

typedef struct {
    int32_t s_raw_val;  // 分流原始值
    int32_t factor;     // 对应的乘法因子 (0.1uA/LSB)
} GainPoint_t;

static uint16_t low_current_counter = 0;  // 用于计数，防止毛刺触发回切

//-----------------------------------------用户修改项---------------------------------//

// --- 1.电压线性校准参数 ---
// 理论值为 1250000 nV (1.25mV)
// 根据实测比例计算出的校准值
uint32_t cal_v_lsb_nv = 1250000;  // nV


//=====================2.零点校准替换区开始===================
/*
// 校准表(table_10mr): 326 桶 -> 压缩后为 20 关键点 (Epsilon=0.20)
// 校准表(table_100r): 324 桶 -> 压缩后为 22 关键点 (Epsilon=0.28)
*/

const CalPoint_t table_10mr[] = {
    { 2900,  4208}, // 2.9V (实际：16.44 LSB)
    { 3700,  4030}, // 3.7V (实际：15.74 LSB)
    { 4600,  3499}, // 4.6V (实际：13.67 LSB)
    { 6200,  3047}, // 6.2V (实际：11.90 LSB)
    { 8800,  2708}, // 8.8V (实际：10.58 LSB)
    {10300,  2691}, // 10.3V (实际：10.51 LSB)
    {14700,  2515}, // 14.7V (实际：9.83 LSB)
    {15400,  2603}, // 15.4V (实际：10.17 LSB)
    {17100,  2472}, // 17.1V (实际：9.66 LSB)
    {19100,  2477}, // 19.1V (实际：9.68 LSB)
    {21800,  2413}, // 21.8V (实际：9.43 LSB)
    {22500,  2467}, // 22.5V (实际：9.64 LSB)
    {24700,  2373}, // 24.7V (实际：9.27 LSB)
    {26200,  2381}, // 26.2V (实际：9.30 LSB)
    {27000,  2296}, // 27.0V (实际：8.97 LSB)
    {27800,  2465}, // 27.8V (实际：9.63 LSB)
    {29800,  2264}, // 29.8V (实际：8.84 LSB)
    {30500,  2285}, // 30.5V (实际：8.92 LSB)
    {31000,  2345}, // 31.0V (实际：9.16 LSB)
    {36000,  2427}, // 36.0V (实际：9.48 LSB)
};
#define TABLE_10MR_SIZE 20

const CalPoint_t table_100r[] = {
    { 2900,  8516}, // 2.9V (实际：33.27 LSB)
    { 3200,  8732}, // 3.2V (实际：34.11 LSB)
    { 3500,  9165}, // 3.5V (实际：35.80 LSB)
    { 3800,  9498}, // 3.8V (实际：37.10 LSB)
    { 5500,  9613}, // 5.5V (实际：37.55 LSB)
    { 6800,  9956}, // 6.8V (实际：38.89 LSB)
    {10700, 11791}, // 10.7V (实际：46.06 LSB)
    {14000, 13499}, // 14.0V (实际：52.73 LSB)
    {16700, 15012}, // 16.7V (实际：58.64 LSB)
    {17400, 15360}, // 17.4V (实际：60.00 LSB)
    {19500, 16700}, // 19.5V (实际：65.23 LSB)
    {22900, 18258}, // 22.9V (实际：71.32 LSB)
    {24800, 19190}, // 24.8V (实际：74.96 LSB)
    {27100, 20385}, // 27.1V (实际：79.63 LSB)
    {27600, 20820}, // 27.6V (实际：81.33 LSB)
    {28500, 21099}, // 28.5V (实际：82.42 LSB)
    {30600, 22352}, // 30.6V (实际：87.31 LSB)
    {31600, 22746}, // 31.6V (实际：88.85 LSB)
    {34600, 24447}, // 34.6V (实际：95.49 LSB)
    {34800, 24674}, // 34.8V (实际：96.38 LSB)
    {35200, 24867}, // 35.2V (实际：97.13 LSB)
    {36000, 25334}, // 36.0V (实际：98.96 LSB)
};
#define TABLE_100R_SIZE 22




//=========================3.线性电阻值补偿区开始============================
const GainPoint_t gain_table_10r[] = {
    {    0,   1424061}, // 0.001MA
    {    2,    606592}, // 0.0021MA
    {  345,    400394}, // 0.2107MA
    {  804,    400835}, // 0.4916MA
    { 9785,    401185}, // 5.99MA
    {22455,    400708}, // 13.73MA
    {26864,    400579}, // 16.42MA
};
#define GAIN_TABLE_10R_SIZE 7


const GainPoint_t gain_table_10mr[] = {
    {  845,      2425}, // 0.205A
    { 4900,      2449}, // 1.2A
    { 8953,      2455}, // 2.198A
    {13035,      2450}, // 3.194A
    {17095,      2452}, // 4.192A
};
#define GAIN_TABLE_10MR_SIZE 5

//=========================线性电阻值补偿结束============================
//----4. 切档
#define BACK_TO_UA 2             // N次检测均满足要求触发降档
#define BACK_TO_UA_PERCENT 0.2  // 设定降档阈值：当 10mR 档的寄存器值低于满量程的 X 时，切回 uA 档


//-----5. 上位机 PC 模式配置
#define PC_LINK_WITH_VOLT 0  // 1: 同时采样电压和电流, 0: 只采样电流 (采样率翻倍)

// 6.定义采样率
#define Standard_Page_RATE INA226_RATE_FAST
#define Curve_Page_RATE INA226_RATE_FAST
#define Stats_Page_RATE INA226_RATE_FAST
#define PC_LINK_RATE INA226_RATE_VERYFAST
// ==========采样间隔配置开始=============
#if (PC_LINK_RATE == 0)    // VERYFAST (140us 档)
#define PC_DELTA_T 141
#elif (PC_LINK_RATE == 1)  // FAST (204us 档)
#define PC_DELTA_T 204
#elif (PC_LINK_RATE == 2)  // FAST (332us 档)
#define PC_DELTA_T 332
#elif (PC_LINK_RATE == 3)  // STANDARD (588us 档)
#define PC_DELTA_T 588
#elif (PC_LINK_RATE == 5)  // SLOW (2.116ms 档)
#define PC_DELTA_T 2116
#else
#define PC_DELTA_T 140  // 默认兜底值
#endif
// ==========采样间隔配置结束=================

// 7.滤波深度定义：最好是 2 的幂（如 64, 128, 256），以便编译器优化
#define FILTER_DEPTH_FAST 1024
#define FILTER_DEPTH_STD 64

//---------------------------------修改项截止----------------------------------//


#define DOWNSHIFT_RAW_LIMIT ((32767 * BACK_TO_UA_PERCENT) / 100)

// 放在 power_app.c 顶部，主循环直接减这两个数
int32_t running_offset_10mr = 0;
int32_t running_offset_100r = 0;

// --- 自动计算的常量系数 (编译器会在编译时算出结果，不占 CPU) ---
#define I_10MR_FACTOR (25000000 / CAL_RES_10MR)         // 结果是 2955
#define I_100R_FACTOR ((25000LL << 16) / CAL_RES_100R)  // 定点数比例

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

// 替换 power_app.c 中的插值函数
int32_t Get_Dynamic_Ratio (int32_t current_s, const GainPoint_t *table, uint8_t size) {
    // 1. 基础边界检查
    if (size == 0)
        return 0;
    if (current_s <= table[0].s_raw_val)
        return table[0].factor;
    if (current_s >= table[size - 1].s_raw_val)
        return table[size - 1].factor;

    // 2. 查表
    for (uint8_t i = 0; i < size - 1; i++) {
        // 找到 current_s 所在的区间 [table[i], table[i+1]]
        if (current_s < table[i + 1].s_raw_val) {
            int32_t x0 = table[i].s_raw_val;
            int32_t x1 = table[i + 1].s_raw_val;
            int32_t y0 = table[i].factor;
            int32_t y1 = table[i + 1].factor;

            int32_t dx = current_s - x0;
            int32_t dy = y1 - y0;
            int32_t rx = x1 - x0;

            if (rx <= 0)
                return y0;

            // --- 核心优化点 ---
            // 只要 (dx * dy) 不超过 21 亿，直接乘除是最准且最省空间的。
            // 你的表中 max(dx)=30000, max(dy)=6200, 乘积 1.8亿，远小于 21亿。
            return y0 + (dx * dy) / rx;
        }
    }
    return table[size - 1].factor;
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
 * @brief  工业级无温漂、无溢出、无阶梯断层的高精密双点线性插值引擎
 * @param  target_v: 当前测得的总线电压 (mV)
 * @return Q8 格式的高精密 LSB 零点偏置 (放大 256 倍)
 */
int16_t Get_Offset_Generic (uint32_t target_v, const CalPoint_t *table, uint8_t size) {
    // 1. 边界防御
    if (target_v <= table[0].volt_mv)
        return table[0].offset;
    if (target_v >= table[size - 1].volt_mv)
        return table[size - 1].offset;

    // 2. 双点线性插值检索
    for (uint8_t i = 0; i < size - 1; i++) {
        if (target_v >= table[i].volt_mv && target_v <= table[i + 1].volt_mv) {
            int32_t x0 = table[i].volt_mv;
            int32_t x1 = table[i + 1].volt_mv;
            int32_t y0 = table[i].offset;
            int32_t y1 = table[i + 1].offset;

            int32_t dx = (int32_t)(target_v - x0);
            int32_t dy = y1 - y0;
            int32_t rx = x1 - x0;

            if (rx <= 0)
                return (int16_t)y0;

            // 线性插值核心公式：y = y0 + dx * dy / rx
            // 32 位无溢出乘法，完美实现亚 LSB 级的零点平滑追踪
            return (int16_t)(y0 + (dx * dy) / rx);
        }
    }
    return table[0].offset;
}

/**
 * @brief  工业级 512 次物理超采样极速去皮逻辑
 * 核心思路：保持当前高速转换率 -> 硬件防抖稳定 30ms -> 微秒级连续采集 512 点均值
 */
/**
 * @brief  工业级 1024 次物理超采样极速去皮逻辑 (极简体积优化版)
 */
void App_User_Tare (void) {
    tare_progress = 43;               
    tare_flash_timer = 15;            
    OLED_Update (App_UI_Dispatcher);  

    INA226_Shunt_t original_mode = current_shunt_mode;
    int32_t sum_raw = 0;
    
    uint16_t t_conv_us = 204; 

    // --- 1. 采集 100R（小电流档）1024次超采样零点 ---
    INA226_Set_Shunt (INA226_SHUNT_100R);
    Delay_Ms (40);  

    sum_raw = 0;
    I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV); 
    for (uint16_t i = 0; i < 1024; i++) {
        sum_raw += (int16_t)INA226_Get_Raw_ShuntV();
        Delay_Us (t_conv_us);  
    }
    // 【从源头统一】：右移 2 位（即除以4），直接将 1024 次累加和转化为高精度 Q8 零点！
    user_tare_offset_100r = sum_raw >> 2;

    // --- 2. 采集 10mR（大电流档）1024次超采样零点 ---
    INA226_Set_Shunt (INA226_SHUNT_10mR);
    Delay_Ms (40);  

    sum_raw = 0;
    I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV);
    for (uint16_t i = 0; i < 1024; i++) {
        sum_raw += (int16_t)INA226_Get_Raw_ShuntV();
        Delay_Us (t_conv_us);
    }
    // 转化为 Q8 零点
    user_tare_offset_10mr = sum_raw >> 2;

    INA226_Set_Shunt (original_mode);
    I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV);
    
    user_tare_active = 1;   
    tare_action_done = 1;   
    tare_flash_timer = 15;  
}

static uint64_t sync_ready_time_us = 0;  // 在此时间之后，电流数据一定有效
static uint8_t sync_ptr_set_done = 0;    // 确保只设置一次指针

/**
 * @brief  工业级双通道（电压+电流）1024次超采样无损级联均值算法 (零成本空间优化版)
 */
void App_Measure_Update (void) {
    static uint32_t next_sample_us = 0;
    uint32_t now = Get_System_us();

    if (pc_link_active) {
        if (now < next_sample_us) return;
        next_sample_us += PC_DELTA_T;
        if (now > next_sample_us + 1000)
            next_sample_us = now + PC_DELTA_T;
    }

    uint8_t need_v = 0;
    if (pc_link_active && (PC_LINK_WITH_VOLT == 0))
        need_v = 0;
    else
        need_v = (current_page != UI_PAGE_CURVE || curve_view == CURVE_V || curve_view == CURVE_W);

    uint8_t need_i = (current_page != UI_PAGE_CURVE || curve_view == CURVE_A || curve_view == CURVE_W);

    // ==========================================
    // 1. 混合切档防御与累加器初始化 (新增电压累加器)
    // ==========================================
    static int32_t s_raw_sum = 0;     
    static int32_t v_raw_sum = 0;     // 【新增】：零 FLASH 成本的电压原始和累加器
    static uint32_t s_raw_count = 0;  

    if (shunt_is_dirty) {
        IIC_Write_Reg16 (INA226_ADDR, INA226_REG_CONFIG, _config_reg);

        uint8_t vshct = (_config_reg >> 3) & 0x07;
        uint8_t avg = (_config_reg >> 9) & 0x07;
        const uint16_t t_conv_us[8] = {66, 134, 269, 542, 1085, 2170, 4341, 8682};
        uint32_t t_total = (uint32_t)t_conv_us[vshct] * (1UL << avg) + 10;

        sync_ready_time_us = Get_System_us() + t_total;
        sync_ptr_set_done = 0;

        // 统一清空
        s_raw_sum = 0;
        v_raw_sum = 0;
        s_raw_count = 0;

        if (pc_link_active)
            App_Send_PC_DMA (v_mv, last_safe_instant_ua);

        shunt_is_dirty = 0;
        return;
    }

    if ((int64_t)(Get_System_us() - sync_ready_time_us) < 0) return;

    if (!sync_ptr_set_done) {
        I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV);
        sync_ptr_set_done = 1;
        return;
    }

    // 更新 Q8 零点偏置
    static uint32_t last_offset_update = 0;
    if (sys_tick_ms - last_offset_update >= 10) {
        if (user_tare_active) {
            running_offset_10mr = user_tare_offset_10mr;
            running_offset_100r = user_tare_offset_100r;
        } else {
            running_offset_10mr = Get_Offset_Generic (v_mv, table_10mr, TABLE_10MR_SIZE);
            running_offset_100r = Get_Offset_Generic (v_mv, table_100r, TABLE_100R_SIZE);
        }
        last_offset_update = sys_tick_ms;
    }

    INA226_Shunt_t mode_at_this_moment = current_shunt_mode;
    int32_t instant_ua = 0;

    if (need_i) {
        int16_t s_raw = 0;
        if (pc_link_active) {
            s_raw = (int16_t)IIC_Read_PC_Fast_V2();
        } else {
            s_raw = (int16_t)INA226_Get_Raw_ShuntV();
        }

        if (current_shunt_mode != mode_at_this_moment || shunt_is_dirty) {
            shunt_is_dirty = 1;
            last_switch_us = now;
            s_raw_sum = 0;
            v_raw_sum = 0;
            s_raw_count = 0;
            if (pc_link_active)
                App_Send_PC_DMA (v_mv, last_safe_instant_ua);
            return;
        }

        // =======================================================
        // 核心分支 1：PC 高速发送流
        // =======================================================
        if (pc_link_active) {
            // PC 模式下电压依然保持瞬时读取，确保波形同步
            if (PC_LINK_WITH_VOLT) {
                uint16_t v_raw = INA226_Get_Raw_BusV();
                v_mv = (uint32_t)((v_raw * (cal_v_lsb_nv / 100)) / 10000);
            }

            if (mode_at_this_moment == INA226_SHUNT_10mR) {
                int32_t raw_diff = s_raw - (running_offset_10mr >> 8);
                // if (raw_diff < 0) raw_diff = 0;
                int32_t current_ratio = Get_Dynamic_Ratio(raw_diff, gain_table_10mr, GAIN_TABLE_10MR_SIZE);
                instant_ua = raw_diff * current_ratio;

                // 后台降档跟踪
                static int32_t pc_s_raw_sum = 0;
                static uint16_t pc_s_raw_cnt = 0;
                pc_s_raw_sum += s_raw;
                pc_s_raw_cnt++;

                if (pc_s_raw_cnt >= 128) {
                    int32_t pc_raw_avg = pc_s_raw_sum / 128;
                    int32_t pc_raw_diff = pc_raw_avg - (running_offset_10mr >> 8);
                    // if (pc_raw_diff < 0) pc_raw_diff = 0;
                    
                    pc_s_raw_sum = 0;
                    pc_s_raw_cnt = 0;

                    if (pc_raw_diff < DOWNSHIFT_RAW_LIMIT) {
                        low_current_counter += 128;
                    } else {
                        low_current_counter = 0;
                    }
                }
            } else {
                int32_t raw_diff = s_raw - (running_offset_100r >> 8);
                // if (raw_diff < 0) raw_diff = 0;
                int32_t current_ratio = Get_Dynamic_Ratio(raw_diff, gain_table_10r, GAIN_TABLE_10R_SIZE);
                instant_ua = (int32_t)(((int64_t)raw_diff * current_ratio) >> 16);
            }
            App_Send_PC_DMA(v_mv, instant_ua);
        } 
        // =======================================================
        // 核心分支 2：本地显示模式 (电压+电流双通道 1024 均值超滤)
        // =======================================================
        else {
            s_raw_sum += s_raw;
            if (need_v) {
                // 【搭便车优化 1】：直接在此处累加原始电压值，避免在主循环中运行昂贵的 32 位乘除法
                v_raw_sum += INA226_Get_Raw_BusV();
            }
            s_raw_count++;

            uint8_t depth_shift = (current_rate_mode <= INA226_RATE_STANDARD) ? 10 : 6;
            uint32_t target_filter_depth = 1 << depth_shift;

            if (s_raw_count >= target_filter_depth) {
                
                // 【搭便车优化 2】：只在 1024 次平均满的那一瞬间，才算一次电压
                // 算力开销直接暴降 99.9%！且消除了全局重复的 /10000 汇编，Flash 空间不增反减！
                if (need_v) {
                    int32_t v_raw_avg = v_raw_sum >> depth_shift;
                    v_raw_sum = 0; // 清空电压累加器
                    v_mv = (uint32_t)((v_raw_avg * (cal_v_lsb_nv / 100)) / 10000);
                }

                int32_t offset_q8 = (mode_at_this_moment == INA226_SHUNT_10mR) ? running_offset_10mr : running_offset_100r;
                int32_t offset_correction = (depth_shift == 10) ? (offset_q8 << 2) : (offset_q8 >> 2);
                
                int32_t raw_diff_sum = s_raw_sum - offset_correction;
                if (raw_diff_sum < 0) raw_diff_sum = 0;
                
                s_raw_sum = 0;
                s_raw_count = 0;

                int32_t raw_diff_for_lookup = raw_diff_sum >> depth_shift;

                if (mode_at_this_moment == INA226_SHUNT_10mR) {
                    int32_t current_ratio = Get_Dynamic_Ratio(raw_diff_for_lookup, gain_table_10mr, GAIN_TABLE_10MR_SIZE);
                    int64_t huge_product = (int64_t)raw_diff_sum * current_ratio;
                    instant_ua = (int32_t)(huge_product >> depth_shift);

                    // 降档
                    int32_t dynamic_limit = (current_rate_mode == INA226_RATE_FAST) ? (DOWNSHIFT_RAW_LIMIT + 50) : DOWNSHIFT_RAW_LIMIT;
                    if (raw_diff_for_lookup < dynamic_limit) {
                        low_current_counter += target_filter_depth; 
                    } else {
                        low_current_counter = 0;
                    }
                } 
                else {
                    int32_t current_ratio = Get_Dynamic_Ratio(raw_diff_for_lookup, gain_table_10r, GAIN_TABLE_10R_SIZE);
                    int64_t huge_product = (int64_t)raw_diff_sum * current_ratio;
                    instant_ua = (int32_t)(huge_product >> (16 + depth_shift));
                }

                i_ua = instant_ua;
                i_ua_raw = instant_ua;
            }
        }

        // 自动降档触发
        if (mode_at_this_moment == INA226_SHUNT_10mR && low_current_counter > BACK_TO_UA * 50) {
            static uint32_t last_downshift_tick = 0;
            if (sys_tick_ms - last_downshift_tick > 500) {
                INA226_Set_Shunt(INA226_SHUNT_100R);
                low_current_counter = 0;
                IIC_Read_Reg16(INA226_ADDR, INA226_REG_MASK);
                shunt_is_dirty = 1;
                last_switch_us = Get_System_us();
                last_downshift_tick = sys_tick_ms;
                
                if (pc_link_active) {
                    I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV);
                }
                return;
            } else {
                low_current_counter = 0;
            }
        }

        // 5. 累积积分统计
        if (!pc_link_active && stats_running && s_raw < 32760 && s_raw > -32760) {
            static uint32_t last_tick = 0;
            uint32_t current_tick = sys_tick_ms;
            uint32_t dt = current_tick - last_tick;
            last_tick = sys_tick_ms;
            if (dt > 500) dt = 0;

            static uint16_t ms_cnt = 0;
            ms_cnt += (uint16_t)dt;
            if (ms_cnt >= 1000) {
                total_runtime_sec++;
                ms_cnt -= 1000;
            }

            static int64_t rem_uas = 0;
            rem_uas += (int64_t)i_ua * (int64_t)dt;
            while (rem_uas >= 36000000) {
                stats_mah++;
                rem_uas -= 36000000;
            }
            while (rem_uas <= -36000000) {
                if (stats_mah > 0) stats_mah--;
                rem_uas += 36000000;
            }

            static int64_t rem_mws = 0;
            if (need_v) {
                uint32_t abs_i = (i_ua < 0) ? -i_ua : i_ua;
                uint32_t V = (uint32_t)v_mv;
                uint32_t p_high = (V * (abs_i / 1000)) / 100;
                uint32_t p_low = (V * (abs_i % 1000)) / 100000;
                p_mw = (i_ua < 0) ? -(int32_t)(p_high + p_low) : (int32_t)(p_high + p_low);
            } else {
                p_mw = 0;
            }

            rem_mws += (int64_t)p_mw * (int64_t)dt;
            while (rem_mws >= 360000) {
                stats_mwh++;
                rem_mws -= 360000;
            }
            while (rem_mws <= -360000) {
                if (stats_mwh > 0) stats_mwh--;
                rem_mws += 360000;
            }
        }

        if (!shunt_is_dirty && (now - last_switch_us > 1000)) {
            last_safe_instant_ua = instant_ua;
        }
    }

    if (!pc_link_active) {
        App_Curve_Record();
    }
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
            INA226_Set_Measure_Mode (PC_LINK_WITH_VOLT ? INA226_MODE_ALL : INA226_MODE_CURR_ONLY);
            INA226_Set_Rate (PC_LINK_RATE);
            // --- 核心优化：先发一次寄存器号，把 INA226 的内部指针指死在 01h ---
            I2C_Set_Reg_Pointer (INA226_ADDR, INA226_REG_SHUNTV);  // 这里的 0x00 不会被写入，仅仅是为了移动指针
            PC_Link_Start();
        }
        return;
    }

    // 2. 长按左键逻辑 (带状态识别)
    if (e == KEY_L_LONG) {
        if (pc_link_active) {
            // 如果在 PC 模式，长按左键 = 退出
            INA226_Set_Rate (Standard_Page_RATE);
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
    if (e == KEY_R_LONG) {
        if (pc_link_active) {
            // 如果在 PC 模式，长按左键 = 退出
            INA226_Set_Rate (Standard_Page_RATE);
            INA226_Set_Measure_Mode (INA226_MODE_ALL);
            PC_Link_Stop();
            pc_link_active = 0;
        } else {
            INA226_Set_Shunt (current_shunt_mode == INA226_SHUNT_10mR ? INA226_SHUNT_100R : INA226_SHUNT_10mR);
        }
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
        } else {
            OLED_ShowFixedNum (mid_x, 21, i_ua / 1000, 1, "mA");
        }


    else
        OLED_ShowFixedNum (mid_x, 21, i_ua / 10000, 3, "A");


    int32_t abs_p = (p_mw < 0) ? -p_mw : p_mw;

    if (abs_p < 100000) {        // 小于 1000.00 mW
        if (abs_p < 1000)        // < 10.00 mW
            OLED_ShowFixedNum (mid_x, 42, p_mw, 2, "mW");
        else if (abs_p < 10000)  // < 100.00 mW
            OLED_ShowFixedNum (mid_x, 42, p_mw, 2, "mW");
        else                     // 100.00mW ~ 999.99mW
            OLED_ShowFixedNum (mid_x, 42, p_mw / 10, 1, "mW");
    } else {
        // 大于 1W，显示为 W，保留 3 位小数
        // p_mw 是 0.01mW 单位，除以 10 变成 0.1mW 单位，
        // ShowFixedNum 使用 4 位精度（对应 0.0001 缩放）或 3 位
        // 这里建议统一到 4 位显示 1.2345 W 或者 3 位 1.234 W
        if (abs_p < 1000000)  // < 10W
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
        current_raw = p_mw / 100;


    int32_t current_raw_raw;
    if (curve_view == CURVE_V)
        current_raw_raw = v_mv;
    else if (curve_view == CURVE_A)
        current_raw_raw = i_ua_raw;
    else
        current_raw_raw = p_mw / 100;


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
    OLED_ShowString (x, y, "      ");  // 清行

    if (curve_view == CURVE_V) {
        // 电压特例手动拼接：4.39V 或 36.0V (不使用 ShowFixedNum 防止空格)
        if (val < 10000) {
            // 4.39V 逻辑 (输入单位mV)
            uint32_t v = val / 10;             // 439
            p = int_to_str (buf, v / 100);     // 整数部分 "4"
            buf[p++] = '.';
            buf[p++] = ((v / 10) % 10) + '0';  // 小数第一位 "3"
            buf[p++] = (v % 10) + '0';         // 小数第二位 "9"
        } else {
            // 36.0V 逻辑
            uint32_t v = val / 100;        // 360
            p = int_to_str (buf, v / 10);  // "36"
            buf[p++] = '.';
            buf[p++] = (v % 10) + '0';     // "0"
        }
        buf[p++] = 'V';
    } else if (curve_view == CURVE_A) {
        int32_t abs_v = (val < 0) ? -val : val;
        if (abs_v < 10000) {
            p = int_to_str (buf, val / 10);
            buf[p++] = 'u';
            buf[p++] = 'A';
        } else if (abs_v < 10000000) {
            p = int_to_str (buf, val / 10000);
            buf[p++] = 'm';
            buf[p++] = 'A';
        } else {
            // 电流大于 1A 的特例也可以手动拼，防止 A 前面出空格
            uint32_t v = val / 100000;  // 如 1.23A 对应 123
            p = int_to_str (buf, v / 100);
            buf[p++] = '.';
            buf[p++] = ((v / 10) % 10) + '0';
            buf[p++] = (v % 10) + '0';
            buf[p++] = 'A';
        }
    } else {
        // 功率同理
        int32_t abs_v = (val < 0) ? -val : val;
        if (abs_v < 1000) {
            p = int_to_str (buf, val);
            buf[p++] = 'm';
            buf[p++] = 'W';
        } else {
            uint32_t v = val / 10;  // 如 1.23W 对应 123
            p = int_to_str (buf, v / 100);
            buf[p++] = '.';
            buf[p++] = ((v / 10) % 10) + '0';
            buf[p++] = (v % 10) + '0';
            buf[p++] = 'W';
        }
    }
    buf[p] = '\0';
    OLED_ShowString (x, y, buf);
}

/**
 * @brief  第二页(曲线页)渲染逻辑优化
 */
void Render_Curve_Page (void) {
    // 1. 局部快照，防止计算中途有效点数发生变化
    uint8_t n = valid_wave_points;
    if (n == 0)
        return;

    // 2. 【核心精准算法】：32 位分拆除法
    // q_sum 存商的和，r_sum 存余数的和
    int32_t q_sum = 0;
    int32_t r_sum = 0;

    for (uint8_t i = 0; i < n; i++) {
        int32_t val = wave_buffer[i];

        // 分别累加商和余数
        // 即使 val 是 8A (80,000,000)，32 位除法也极快且不占 Flash
        q_sum += val / n;
        r_sum += val % n;
    }

    // 3. 将累加后的余数再次求均值并合并
    // 即使 128 个点的余数相加，最大也就 128 * 127 = 16256，绝不溢出
    int32_t avg_val = q_sum + (r_sum / n);

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
    if (range < 100)
        range = 100;

    for (uint8_t i = 0; i < valid_wave_points; i++) {
        // x 从 127 开始向左绘制
        uint8_t x = 127 - i;
        // 数据从最新(wave_ptr-1)开始往旧取
        uint8_t buf_idx = (wave_ptr + 128 - 1 - i) % 128;
        int32_t val = wave_buffer[buf_idx];

        int32_t y_mapped;
        if (range > 30000000) {
            // 如果峰值超过 3A，我们将分子分母同时缩小，防止 val * 63 溢出
            // 右移 6 位等于除以 64，3.4A * 63 / 64 绝对不会溢出
            y_mapped = 63 - ((val >> 6) * 63 / (range >> 6));
        } else if (range > 0) {
            // 3A 以下正常计算，保证小电流时的平滑度
            y_mapped = 63 - (val * 63 / range);
        } else {
            y_mapped = 63;
        }
        // --- 核心修复结束 ---

        if (y_mapped < 0)
            y_mapped = 0;
        if (y_mapped > 63)
            y_mapped = 63;
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
 * @brief  主 UI 调度器
 */
void App_UI_Dispatcher (void) {
    // ==========================================
    // 核心修复：PC 模式采用标准的 DMA 分页缓冲机制
    // 不仅完美解决了“R”无法渲染的 Bug，还彻底消除了屏幕剧烈闪烁和卡顿
    // ==========================================
    if (pc_link_active) {
        OLED_ShowString (108, 44, "CR"); // 居中显示工作状态
        return;                             
    }

    static UI_Page_t last_page_snapshot = 0xFF;

    if (current_page != last_page_snapshot) {
        if (current_page == UI_PAGE_CURVE) {
            INA226_Set_Rate (Curve_Page_RATE);
        }
        if (current_page == UI_PAGE_STATS) {
            INA226_Set_Rate (Stats_Page_RATE);
        } else if (current_page == UI_PAGE_STANDARD) {
            INA226_Set_Rate (Standard_Page_RATE);
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
