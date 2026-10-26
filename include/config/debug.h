#ifndef GUARD_CONFIG_DEBUG_H
#define GUARD_CONFIG_DEBUG_H

// Overworld Debug
#define DEBUG_OVERWORLD_MENU            TRUE                // 启用地图调试菜单，可修改 flags、variables、给予宝可梦等，是开发测试的核心工具。
#define DEBUG_OVERWORLD_HELD_KEYS       (R_BUTTON)          // 打开菜单需按住的键，保持默认的 R 键即可。
#define DEBUG_OVERWORLD_TRIGGER_EVENT   pressedStartButton  // 在按住 R 键的同时按下 START 键来触发菜单，符合操作习惯。
#define DEBUG_OVERWORLD_IN_MENU         TRUE                // 将调试菜单入口放入开始菜单，比按键组合更方便查找和使用。

// Battle Debug Menu
#define DEBUG_BATTLE_MENU               TRUE                // 启用战斗调试菜单，在战斗菜单按 Select 即可打开，可实时修改对战数据。
#define DEBUG_AI_DELAY_TIMER            TRUE                // 显示 AI 选择招式所耗帧数，方便监控和优化 AI 性能，避免因逻辑复杂导致等待过长。

// Pokémon Debug
#define DEBUG_POKEMON_SPRITE_VISUALIZER TRUE                // 启用宝可梦精灵/图标可视化调试，在摘要界面按 Select 可预览所有精灵和动画。

#endif // GUARD_CONFIG_DEBUG_H