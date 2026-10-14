#include "power_app.h"
#include "ina226.h"
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
// 校准表(table_10mr): 332 桶 -> 压缩后为 8 关键点 (Epsilon=0.36)
// 校准表(table_100r): 327 桶 -> 压缩后为 23 关键点 (Epsilon=0.20)
*/


const CalPoint_t table_10mr[] = {
    { 2700,  5417}, // 2.7V (实际：21.16 LSB)
    { 2800,  5199}, // 2.8V (实际：20.31 LSB)
    { 2900,  5021}, // 2.9V (实际：19.61 LSB)
    { 3000,  4927}, // 3.0V (实际：19.25 LSB)
    { 3100,  4836}, // 3.1V (实际：18.89 LSB)
    { 3200,  4779}, // 3.2V (实际：18.67 LSB)
    { 3300,  4772}, // 3.3V (实际：18.64 LSB)
    { 3500,  4622}, // 3.5V (实际：18.05 LSB)
    { 3600,  4523}, // 3.6V (实际：17.67 LSB)
    { 4000,  4033}, // 4.0V (实际：15.75 LSB)
    { 4200,  3865}, // 4.2V (实际：15.10 LSB)
    { 4300,  3787}, // 4.3V (实际：14.79 LSB)
    { 4500,  3692}, // 4.5V (实际：14.42 LSB)
    { 4600,  3654}, // 4.6V (实际：14.27 LSB)
    { 4800,  3537}, // 4.8V (实际：13.82 LSB)
    { 5000,  3460}, // 5.0V (实际：13.51 LSB)
    { 5300,  3351}, // 5.3V (实际：13.09 LSB)
    { 5400,  3325}, // 5.4V (实际：12.99 LSB)
    { 5500,  3294}, // 5.5V (实际：12.87 LSB)
    { 5600,  3230}, // 5.6V (实际：12.62 LSB)
    { 5900,  3173}, // 5.9V (实际：12.39 LSB)
    { 6100,  3142}, // 6.1V (实际：12.27 LSB)
    { 6500,  3089}, // 6.5V (实际：12.07 LSB)
    { 6800,  3010}, // 6.8V (实际：11.76 LSB)
    { 7100,  2991}, // 7.1V (实际：11.68 LSB)
    { 7600,  2968}, // 7.6V (实际：11.59 LSB)
    { 8000,  2915}, // 8.0V (实际：11.39 LSB)
    { 8200,  2905}, // 8.2V (实际：11.35 LSB)
    { 8500,  2904}, // 8.5V (实际：11.34 LSB)
    { 8700,  2872}, // 8.7V (实际：11.22 LSB)
    { 8800,  2876}, // 8.8V (实际：11.23 LSB)
    { 9100,  2843}, // 9.1V (实际：11.11 LSB)
    { 9600,  2841}, // 9.6V (实际：11.10 LSB)
    { 9900,  2835}, // 9.9V (实际：11.07 LSB)
    {10100,  2813}, // 10.1V (实际：10.99 LSB)
    {10200,  2837}, // 10.2V (实际：11.08 LSB)
    {10400,  2779}, // 10.4V (实际：10.86 LSB)
    {10700,  2788}, // 10.7V (实际：10.89 LSB)
    {10800,  2801}, // 10.8V (实际：10.94 LSB)
    {10900,  2807}, // 10.9V (实际：10.97 LSB)
    {11100,  2796}, // 11.1V (实际：10.92 LSB)
    {11300,  2825}, // 11.3V (实际：11.03 LSB)
    {11400,  2800}, // 11.4V (实际：10.94 LSB)
    {11500,  2784}, // 11.5V (实际：10.87 LSB)
    {12000,  2792}, // 12.0V (实际：10.91 LSB)
    {12200,  2765}, // 12.2V (实际：10.80 LSB)
    {12400,  2784}, // 12.4V (实际：10.88 LSB)
    {12500,  2769}, // 12.5V (实际：10.81 LSB)
    {12800,  2780}, // 12.8V (实际：10.86 LSB)
    {13100,  2750}, // 13.1V (实际：10.74 LSB)
    {13200,  2774}, // 13.2V (实际：10.84 LSB)
    {13500,  2758}, // 13.5V (实际：10.77 LSB)
    {13900,  2779}, // 13.9V (实际：10.86 LSB)
    {14000,  2789}, // 14.0V (实际：10.89 LSB)
    {14200,  2765}, // 14.2V (实际：10.80 LSB)
    {14600,  2769}, // 14.6V (实际：10.82 LSB)
    {14800,  2781}, // 14.8V (实际：10.86 LSB)
    {15000,  2736}, // 15.0V (实际：10.69 LSB)
    {15200,  2776}, // 15.2V (实际：10.84 LSB)
    {15500,  2750}, // 15.5V (实际：10.74 LSB)
    {15600,  2790}, // 15.6V (实际：10.90 LSB)
    {15700,  2769}, // 15.7V (实际：10.82 LSB)
    {15900,  2777}, // 15.9V (实际：10.85 LSB)
    {16000,  2742}, // 16.0V (实际：10.71 LSB)
    {16200,  2774}, // 16.2V (实际：10.84 LSB)
    {16300,  2768}, // 16.3V (实际：10.81 LSB)
    {16400,  2772}, // 16.4V (实际：10.83 LSB)
    {16700,  2760}, // 16.7V (实际：10.78 LSB)
    {17000,  2805}, // 17.0V (实际：10.96 LSB)
    {17100,  2785}, // 17.1V (实际：10.88 LSB)
    {17300,  2773}, // 17.3V (实际：10.83 LSB)
    {17400,  2740}, // 17.4V (实际：10.70 LSB)
    {17500,  2776}, // 17.5V (实际：10.85 LSB)
    {18100,  2781}, // 18.1V (实际：10.86 LSB)
    {18300,  2824}, // 18.3V (实际：11.03 LSB)
    {18500,  2806}, // 18.5V (实际：10.96 LSB)
    {18600,  2835}, // 18.6V (实际：11.07 LSB)
    {18800,  2833}, // 18.8V (实际：11.07 LSB)
    {19000,  2845}, // 19.0V (实际：11.11 LSB)
    {19300,  2840}, // 19.3V (实际：11.10 LSB)
    {19500,  2794}, // 19.5V (实际：10.91 LSB)
    {19700,  2856}, // 19.7V (实际：11.16 LSB)
    {20000,  2866}, // 20.0V (实际：11.19 LSB)
};
#define TABLE_10MR_SIZE 83

const CalPoint_t table_100r[] = {
    { 2700, 10742}, // 2.7V (实际：41.96 LSB)
    { 2800, 10673}, // 2.8V (实际：41.69 LSB)
    { 2900, 10670}, // 2.9V (实际：41.68 LSB)
    { 3000, 10771}, // 3.0V (实际：42.07 LSB)
    { 3100, 10851}, // 3.1V (实际：42.39 LSB)
    { 3300, 11289}, // 3.3V (实际：44.10 LSB)
    { 3400, 11591}, // 3.4V (实际：45.28 LSB)
    { 3500, 11642}, // 3.5V (实际：45.48 LSB)
    { 3600, 11613}, // 3.6V (实际：45.36 LSB)
    { 3700, 11528}, // 3.7V (实际：45.03 LSB)
    { 3800, 11376}, // 3.8V (实际：44.44 LSB)
    { 4100, 11086}, // 4.1V (实际：43.30 LSB)
    { 4200, 10997}, // 4.2V (实际：42.96 LSB)
    { 4400, 10899}, // 4.4V (实际：42.57 LSB)
    { 4500, 10822}, // 4.5V (实际：42.27 LSB)
    { 4600, 10796}, // 4.6V (实际：42.17 LSB)
    { 4800, 10676}, // 4.8V (实际：41.70 LSB)
    { 4900, 10667}, // 4.9V (实际：41.67 LSB)
    { 5000, 10586}, // 5.0V (实际：41.35 LSB)
    { 5200, 10548}, // 5.2V (实际：41.20 LSB)
    { 5300, 10470}, // 5.3V (实际：40.90 LSB)
    { 5700, 10368}, // 5.7V (实际：40.50 LSB)
    { 5800, 10316}, // 5.8V (实际：40.30 LSB)
    { 5900, 10329}, // 5.9V (实际：40.35 LSB)
    { 6300, 10258}, // 6.3V (实际：40.07 LSB)
    { 6500, 10228}, // 6.5V (实际：39.95 LSB)
    { 6800, 10215}, // 6.8V (实际：39.90 LSB)
    { 7000, 10171}, // 7.0V (实际：39.73 LSB)
    { 7100, 10161}, // 7.1V (实际：39.69 LSB)
    { 7200, 10179}, // 7.2V (实际：39.76 LSB)
    { 7500, 10114}, // 7.5V (实际：39.51 LSB)
    { 7600, 10139}, // 7.6V (实际：39.60 LSB)
    { 7900, 10105}, // 7.9V (实际：39.47 LSB)
    { 8200, 10109}, // 8.2V (实际：39.49 LSB)
    { 8700, 10059}, // 8.7V (实际：39.29 LSB)
    { 9200, 10068}, // 9.2V (实际：39.33 LSB)
    { 9300, 10027}, // 9.3V (实际：39.17 LSB)
    { 9500, 10039}, // 9.5V (实际：39.21 LSB)
    { 9600,  9983}, // 9.6V (实际：39.00 LSB)
    { 9700, 10010}, // 9.7V (实际：39.10 LSB)
    {10300, 10002}, // 10.3V (实际：39.07 LSB)
    {10500, 10043}, // 10.5V (实际：39.23 LSB)
    {10900, 10033}, // 10.9V (实际：39.19 LSB)
    {11100, 10051}, // 11.1V (实际：39.26 LSB)
    {11200, 10071}, // 11.2V (实际：39.34 LSB)
    {11500, 10036}, // 11.5V (实际：39.20 LSB)
    {11600, 10031}, // 11.6V (实际：39.18 LSB)
    {11800, 10037}, // 11.8V (实际：39.21 LSB)
    {12100, 10060}, // 12.1V (实际：39.30 LSB)
    {12400, 10030}, // 12.4V (实际：39.18 LSB)
    {12600, 10055}, // 12.6V (实际：39.28 LSB)
    {12800, 10075}, // 12.8V (实际：39.35 LSB)
    {12900, 10067}, // 12.9V (实际：39.32 LSB)
    {13000, 10101}, // 13.0V (实际：39.46 LSB)
    {13200, 10091}, // 13.2V (实际：39.42 LSB)
    {13500, 10091}, // 13.5V (实际：39.42 LSB)
    {13700, 10128}, // 13.7V (实际：39.56 LSB)
    {13900, 10124}, // 13.9V (实际：39.55 LSB)
    {14100, 10148}, // 14.1V (实际：39.64 LSB)
    {14500, 10164}, // 14.5V (实际：39.70 LSB)
    {14600, 10174}, // 14.6V (实际：39.74 LSB)
    {14800, 10209}, // 14.8V (实际：39.88 LSB)
    {14900, 10162}, // 14.9V (实际：39.69 LSB)
    {15100, 10236}, // 15.1V (实际：39.98 LSB)
    {15200, 10189}, // 15.2V (实际：39.80 LSB)
    {15300, 10253}, // 15.3V (实际：40.05 LSB)
    {15500, 10232}, // 15.5V (实际：39.97 LSB)
    {15600, 10287}, // 15.6V (实际：40.18 LSB)
    {16000, 10291}, // 16.0V (实际：40.20 LSB)
    {16300, 10323}, // 16.3V (实际：40.32 LSB)
    {16400, 10363}, // 16.4V (实际：40.48 LSB)
    {16700, 10382}, // 16.7V (实际：40.55 LSB)
    {17000, 10458}, // 17.0V (实际：40.85 LSB)
    {17500, 10516}, // 17.5V (实际：41.08 LSB)
    {17600, 10514}, // 17.6V (实际：41.07 LSB)
    {17800, 10556}, // 17.8V (实际：41.23 LSB)
    {18000, 10639}, // 18.0V (实际：41.56 LSB)
    {18200, 10623}, // 18.2V (实际：41.50 LSB)
    {18400, 10737}, // 18.4V (实际：41.94 LSB)
    {18500, 10728}, // 18.5V (实际：41.90 LSB)
    {18700, 10740}, // 18.7V (实际：41.95 LSB)
    {18900, 10784}, // 18.9V (实际：42.13 LSB)
    {19200, 10852}, // 19.2V (实际：42.39 LSB)
    {19300, 10915}, // 19.3V (实际：42.64 LSB)
    {19500, 10968}, // 19.5V (实际：42.84 LSB)
    {19700, 11029}, // 19.7V (实际：43.08 LSB)
    {20000, 11135}, // 20.0V (实际：43.50 LSB)
};
#define TABLE_100R_SIZE 87


//=========================3.线性电阻值补偿区开始============================
const GainPoint_t gain_table_10mr[] = {
	{   86,      1232}, // 10.61MA
    {  107,      1231}, // 13.18MA
    {  117,      1232}, // 14.42MA
    {  129,      1230}, // 15.81MA
    { 1480,      1230}, // 0.182A
	{ 1480,      1230}, // 0.182A
    { 2321,      1228}, // 0.285A
    { 3096,      1227}, // 0.38A
    { 3127,      1228}, // 0.384A
    { 3937,      1229}, // 0.484A
    { 4712,      1229}, // 0.579A
    { 4749,      1228}, // 0.583A
    { 5557,      1231}, // 0.684A
    { 6368,      1228}, // 0.782A
    { 7174,      1231}, // 0.883A
    { 7950,      1229}, // 0.977A
    { 7984,      1229}, // 0.981A
    { 8796,      1230}, // 1.082A
    {10410,      1231}, // 1.281A
    {11991,      1230}, // 1.475A
    {12041,      1230}, // 1.481A
    {16052,      1230}, // 1.974A
    {16097,      1229}, // 1.979A
    {18468,      1231}, // 2.273A
    {20069,      1234}, // 2.477A
};
#define GAIN_TABLE_10MR_SIZE 25

const GainPoint_t gain_table_10r[] = {
    {    2,    260587}, // 0.9UA
    {    6,    225705}, // 1.9UA
    {   14,    210778}, // 4.5UA
    {   30,    206292}, // 9.3UA
    {   62,    202799}, // 19.3UA
    {  147,    201316}, // 45.3UA
    {  305,    200953}, // 93.5UA
    {  628,    200821}, // 192.3UA
    {  907,    201050}, // 278.4UA
    { 1467,    200488}, // 448.8UA
    { 2295,    200554}, // 702.4UA
    { 2982,    200450}, // 912.2UA
    { 5943,    200441}, // 1817.8UA
    {12245,    200161}, // 3.74MA
    {17762,    200353}, // 5.43MA
    {23148,    200450}, // 7.08MA
    {29834,    200335}, // 9.12MA
};
#define GAIN_TABLE_10R_SIZE 17

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

// 定义一个静态缓冲区供 DMA 使用
uint8_t pc_buf[12];

/**
 * @brief 在 main 函数初始化完毕后调用此函数，强制进入 PC 模式
 */
void Boot_Into_PCLink_Mode(void) {
    pc_link_active = 1;
    
    // 强制配置 INA226 的采样率和模式
    INA226_Set_Measure_Mode(PC_LINK_WITH_VOLT ? INA226_MODE_ALL : INA226_MODE_CURR_ONLY);
    INA226_Set_Rate(PC_LINK_RATE);
    
    // 锁死 I2C 寄存器指针
    I2C_Set_Reg_Pointer(INA226_ADDR, INA226_REG_SHUNTV);
    
    // 启动串口 DMA (这是你串口收到数据的关键)
    PC_Link_Start();
}

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
        // 核心分支 2：本地后台模式 (电压+电流双通道 1024 均值超滤保留)
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
 * @brief  业务交互中心：处理逻辑分发
 */
void App_Key_Handler (void) {
    Key_Event_t e = Key_Scan();
    if (e == KEY_EVENT_NONE)
        return;

    // --- 1. 处理全局最高优先级：双键长按翻转屏幕逻辑 ---
    if (e == KEY_BOTH_LONG) {
        global_screen_flipped = !global_screen_flipped;
        return;  // 触发翻转后直接退出，防止误触发单键逻辑
    }

    // --- 2. 核心逻辑：按键逻辑对调 ---
    // 如果物理上翻转了，物理上的“左”就变成了逻辑上的“右”
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

    // --- 全局数据记录页切换逻辑 ---
    if (e == KEY_L_SHORT) {
        current_page = (current_page == 0) ? 2 : current_page - 1;
        return;
    }
    if (e == KEY_R_SHORT) {
        current_page = (current_page + 1) % 3;
        return;
    }

    // 将剩余的事件 (长按、双按) 丢给对应的处理器
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
 * @brief  第一页(标准状态)的专属逻辑
 */
void Handle_Standard_Input (Key_Event_t e) {
    // 1. 双击切换进入/退出 (或者是只进入)
    if (e == KEY_BOTH_SHORT) {
        if (!pc_link_active) {
            pc_link_active = 1;
            // 【新增硬件联动】：根据宏配置调整采样
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
        // 这会让后台重新从 /1, /2... 开始计算平均值
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
    // --- 核心：双击 ---
    if (e == KEY_BOTH_SHORT) {
    }

    // --- 左键长按：清零数据 ---
    if (e == KEY_L_LONG) {
        // 执行清零
        energy_uas_acc = 0;
        energy_mws_acc = 0;
        total_runtime_sec = 0;
        stats_mah = 0;
        stats_mwh = 0;
    }

    // --- 右键长按：暂停/开始统计 ---
    if (e == KEY_R_LONG) {
        stats_running = !stats_running;
    }
}

/**
 * @brief  主后台页面速率调度器
 */
void App_UI_Dispatcher (void) {
    if (pc_link_active) {
        return;                             
    }

    static UI_Page_t last_page_snapshot = 0xFF;

    if (current_page != last_page_snapshot) {
        if (current_page == UI_PAGE_CURVE) {
            INA226_Set_Rate (Curve_Page_RATE);
        } else if (current_page == UI_PAGE_STATS) {
            INA226_Set_Rate (Stats_Page_RATE);
        } else if (current_page == UI_PAGE_STANDARD) {
            INA226_Set_Rate (Standard_Page_RATE);
        }
        last_page_snapshot = current_page;
    }
}