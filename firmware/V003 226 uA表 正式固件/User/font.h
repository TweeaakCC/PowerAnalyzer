#ifndef __FONT_H
#define __FONT_H

#include "ch32v00x.h"

// 1. 定义你真正需要的字符集
// 包含：空格、数字、常用符号、单位、页面标题字母
#define FONT_INDEX_STR  " 0123456789.:AVWmAhsuRZzSCc"

// 2. 导出字库数组：现在它的大小由你选取的字符数决定
extern const uint8_t ascii_9x18[][27];

#endif