#include "global.h"
#include "stat_editor.h"
#include "battle.h"
#include "bg.h"
#include "event_data.h"
#include "field_effect.h"
#include "gpu_regs.h"
#include "graphics.h"
#include "main.h"
#include "malloc.h"
#include "menu.h"
#include "menu_helpers.h"
#include "palette.h"
#include "party_menu.h"
#include "pokemon.h"
#include "pokemon_icon.h"
#include "scanline_effect.h"
#include "sound.h"
#include "sprite.h"
#include "string_util.h"
#include "task.h"
#include "text.h"
#include "text_window.h"
#include "trainer_pokemon_sprites.h"
#include "window.h"
#include "strings.h"
#include "constants/abilities.h"
#include "constants/characters.h"
#include "constants/pokemon.h"
#include "constants/rgb.h"
#include "constants/songs.h"

#define WIN_TITLE 0
#define WIN_MAIN  1

#define EDIT_COL_EV 0
#define EDIT_COL_IV 1
#define NUM_STATS   6

// 左面板：立绘 + 特性/性格
#define LEFT_X   2
#define LEFT_W   70
// 右面板：能力表格
#define RIGHT_X  74
#define RIGHT_W  164
#define PANEL_Y  2
#define PANEL_H  90

#define TBL_X_NAME    80
#define TBL_X_ACTUAL  124
#define TBL_X_EV      168
#define TBL_X_IV      212
#define TBL_HEADER_Y  2
#define TBL_ROW_Y0    16
#define TBL_ROW_DY    13

#define LEFT_TEXT_Y1  0
#define LEFT_TEXT_Y2  0

#define PIC_X 38
#define PIC_Y 70

struct StatEditorData
{
    MainCallback savedCallback;
    u16 partyId;
    u8 selCol;
    u8 selRow;
    bool8 editing;
    u16 iconSpriteId;
};

static EWRAM_DATA struct StatEditorData *sData = NULL;

static const struct BgTemplate sBgTemplates[] =
{
    {
        .bg = 0,
        .charBaseIndex = 0,
        .mapBaseIndex = 30,
        .priority = 1,
    },
};

static const struct WindowTemplate sWindowTemplates[] =
{
    [WIN_TITLE] = {
        .bg = 0,
        .tilemapLeft = 0,
        .tilemapTop = 0,
        .width = 30,
        .height = 3,
        .paletteNum = 15,
        .baseBlock = 30,
    },
    [WIN_MAIN] = {
        .bg = 0,
        .tilemapLeft = 0,
        .tilemapTop = 3,
        .width = 30,
        .height = 12,
        .paletteNum = 15,
        .baseBlock = 120,
    },
    DUMMY_WIN_TEMPLATE,
};

static const u16 sActualStatIds[NUM_STATS] = {MON_DATA_MAX_HP, MON_DATA_ATK, MON_DATA_DEF, MON_DATA_SPATK, MON_DATA_SPDEF, MON_DATA_SPEED};
static const u16 sEvStatIds[NUM_STATS]     = {MON_DATA_HP_EV, MON_DATA_ATK_EV, MON_DATA_DEF_EV, MON_DATA_SPATK_EV, MON_DATA_SPDEF_EV, MON_DATA_SPEED_EV};
static const u16 sIvStatIds[NUM_STATS]     = {MON_DATA_HP_IV, MON_DATA_ATK_IV, MON_DATA_DEF_IV, MON_DATA_SPATK_IV, MON_DATA_SPDEF_IV, MON_DATA_SPEED_IV};

static const u8 *const sStatNames[NUM_STATS] =
{
    COMPOUND_STRING("HP"),
    COMPOUND_STRING("攻击"),
    COMPOUND_STRING("防御"),
    COMPOUND_STRING("特攻"),
    COMPOUND_STRING("特防"),
    COMPOUND_STRING("速度"),
};

static const u8 sTextColorNormal[3] = {TEXT_COLOR_TRANSPARENT, TEXT_COLOR_WHITE, TEXT_COLOR_DARK_GRAY};
static const u8 sTextColorSelect[3] = {TEXT_COLOR_TRANSPARENT, TEXT_COLOR_RED,   TEXT_COLOR_DARK_GRAY};

// 分区配色：0 底色 / 1 白字 / 2 阴影 / 3 灰绿 / 4 红 / 5 左面板深绿 / 6 右面板浅绿
static const u16 sStatEditorPalette[16] =
{
    [0] = RGB(9, 16, 8),
    [1] = RGB(31, 31, 31),
    [2] = RGB(3, 6, 3),
    [3] = RGB(20, 24, 18),
    [4] = RGB(31, 8, 8),
    [5] = RGB(4, 10, 4),
    [6] = RGB(14, 22, 12),
};

static void CB2_StatEditorMain(void);
static void VBlankCB_StatEditor(void);
static void Task_StatEditorMain(u8 taskId);
static void Task_StatEditorFadeOut(u8 taskId);
static void Task_StatEditorFadeIn(u8 taskId);

static struct Pokemon *CurrentMon(void)
{
    return &gParties[B_TRAINER_PLAYER][sData->partyId];
}

static u16 CurrentStatId(void)
{
    if (sData->selCol == EDIT_COL_IV)
        return sIvStatIds[sData->selRow];
    return sEvStatIds[sData->selRow];
}

static u16 GetEvTotal(struct Pokemon *mon)
{
    u16 total = 0;
    u16 i;

    for (i = 0; i < NUM_STATS; i++)
        total += GetMonData(mon, sEvStatIds[i]);
    return total;
}

static u8 GetAbilitySlotCount(struct Pokemon *mon)
{
    u16 species = GetMonData(mon, MON_DATA_SPECIES);
    u8 count = 0;
    u8 i;

    for (i = 0; i < NUM_ABILITY_SLOTS; i++)
    {
        if (gSpeciesInfo[species].abilities[i] != ABILITY_NONE)
            count++;
    }
    if (count == 0)
        count = 1;
    return count;
}

static const u8 *GetCurrentAbilityName(struct Pokemon *mon)
{
    u16 species = GetMonData(mon, MON_DATA_SPECIES);
    u8 slot = GetMonData(mon, MON_DATA_ABILITY_NUM);

    if (slot >= NUM_ABILITY_SLOTS || gSpeciesInfo[species].abilities[slot] == ABILITY_NONE)
        slot = 0;

    return gAbilitiesInfo[gSpeciesInfo[species].abilities[slot]].name;
}

static void DrawBorder(u8 windowId, u8 w, u8 h)
{
    FillWindowPixelRect(windowId, PIXEL_FILL(1), 0, 0, w, 1);
    FillWindowPixelRect(windowId, PIXEL_FILL(1), 0, h - 1, w, 1);
    FillWindowPixelRect(windowId, PIXEL_FILL(1), 0, 0, 1, h);
    FillWindowPixelRect(windowId, PIXEL_FILL(1), w - 1, 0, 1, h);
}

static void LoadMonPicture(void)
{
    struct Pokemon *mon = CurrentMon();
    u16 species = GetMonData(mon, MON_DATA_SPECIES);
    u32 personality = GetMonData(mon, MON_DATA_PERSONALITY);
    bool8 shiny = IsMonShiny(mon);

    if (sData->iconSpriteId != 0xFFFF)
    {
        FreeResourcesAndDestroySprite(&gSprites[sData->iconSpriteId], sData->iconSpriteId);
        sData->iconSpriteId = 0xFFFF;
    }

    sData->iconSpriteId = CreateMonPicSprite_Affine(species, shiny, personality, MON_PIC_AFFINE_FRONT, PIC_X, PIC_Y, 14, TAG_NONE);
    if (sData->iconSpriteId != 0xFFFF)
        gSprites[sData->iconSpriteId].oam.priority = 0;
}

static void PrintTitle(void)
{
    struct Pokemon *mon = CurrentMon();
    u16 level = GetMonData(mon, MON_DATA_LEVEL);

    FillWindowPixelBuffer(WIN_TITLE, PIXEL_FILL(0));

    StringCopy(gStringVar4, GetSpeciesName(GetMonData(mon, MON_DATA_SPECIES)));
    AddTextPrinterParameterized4(WIN_TITLE, FONT_SMALL_NARROW, 4, 1, 0, 0,
                                 sTextColorNormal, TEXT_SKIP_DRAW, gStringVar4);

    StringCopy(gStringVar4, COMPOUND_STRING("Lv"));
    ConvertIntToDecimalStringN(gStringVar2, level, STR_CONV_MODE_LEFT_ALIGN, 3);
    StringAppend(gStringVar4, gStringVar2);
    AddTextPrinterParameterized4(WIN_TITLE, FONT_SMALL_NARROW, 100, 1, 0, 0,
                                 sTextColorNormal, TEXT_SKIP_DRAW, gStringVar4);

    StringCopy(gStringVar4, COMPOUND_STRING("努力"));
    ConvertIntToDecimalStringN(gStringVar2, GetEvTotal(mon), STR_CONV_MODE_LEFT_ALIGN, 3);
    StringAppend(gStringVar4, gStringVar2);
    StringAppend(gStringVar4, COMPOUND_STRING("/510"));
    AddTextPrinterParameterized4(WIN_TITLE, FONT_SMALL_NARROW, 168, 1, 0, 0,
                                 sTextColorNormal, TEXT_SKIP_DRAW, gStringVar4);

    StringCopy(gStringVar4, COMPOUND_STRING("特性 "));
    StringAppend(gStringVar4, GetCurrentAbilityName(mon));
    AddTextPrinterParameterized4(WIN_TITLE, FONT_SMALL_NARROW, 4, 12, 0, 0,
                                 sTextColorNormal, TEXT_SKIP_DRAW, gStringVar4);

    if (GetAbilitySlotCount(mon) > 1)
        AddTextPrinterParameterized4(WIN_TITLE, FONT_SMALL_NARROW, 104, 12, 0, 0,
                                     sTextColorSelect, TEXT_SKIP_DRAW, COMPOUND_STRING("SEL"));


    StringCopy(gStringVar4, COMPOUND_STRING("性格 "));
    StringAppend(gStringVar4, gNaturesInfo[GetNature(mon)].name);
    AddTextPrinterParameterized4(WIN_TITLE, FONT_SMALL_NARROW, 140, 12, 0, 0,
                                 sTextColorNormal, TEXT_SKIP_DRAW, gStringVar4);

    PutWindowTilemap(WIN_TITLE);
    CopyWindowToVram(WIN_TITLE, COPYWIN_FULL);
}

static void PrintLeftPanel(struct Pokemon *mon)
{
    FillWindowPixelRect(WIN_MAIN, PIXEL_FILL(5), LEFT_X, PANEL_Y, LEFT_W, PANEL_H);
}

static void PrintStatRow(struct Pokemon *mon, u16 i, u8 y)
{
    const u8 *evColor;
    const u8 *ivColor;

    evColor = (sData->selRow == i && sData->selCol == EDIT_COL_EV) ? sTextColorSelect : sTextColorNormal;
    ivColor = (sData->selRow == i && sData->selCol == EDIT_COL_IV) ? sTextColorSelect : sTextColorNormal;

    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_NAME, y, 0, 0, sTextColorNormal, TEXT_SKIP_DRAW, sStatNames[i]);

    ConvertIntToDecimalStringN(gStringVar2, GetMonData(mon, sActualStatIds[i]), STR_CONV_MODE_RIGHT_ALIGN, 3);
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_ACTUAL, y, 0, 0, sTextColorNormal, TEXT_SKIP_DRAW, gStringVar2);

    ConvertIntToDecimalStringN(gStringVar2, GetMonData(mon, sEvStatIds[i]), STR_CONV_MODE_RIGHT_ALIGN, 3);
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_EV, y, 0, 0, evColor, TEXT_SKIP_DRAW, gStringVar2);

    ConvertIntToDecimalStringN(gStringVar2, GetMonData(mon, sIvStatIds[i]), STR_CONV_MODE_RIGHT_ALIGN, 3);
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_IV, y, 0, 0, ivColor, TEXT_SKIP_DRAW, gStringVar2);
}

static void PrintStats(void)
{
    struct Pokemon *mon = CurrentMon();
    u8 i;

    FillWindowPixelBuffer(WIN_MAIN, PIXEL_FILL(0));

    // 两个面板底色
    FillWindowPixelRect(WIN_MAIN, PIXEL_FILL(6), RIGHT_X, PANEL_Y, RIGHT_W, PANEL_H);
    PrintLeftPanel(mon);

    // 边框
    DrawBorder(WIN_MAIN, 240, 96);

    // 表头
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_NAME,   TBL_HEADER_Y, 0, 0, sTextColorNormal, TEXT_SKIP_DRAW, COMPOUND_STRING("能力"));
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_ACTUAL, TBL_HEADER_Y, 0, 0, sTextColorNormal, TEXT_SKIP_DRAW, COMPOUND_STRING("数值"));
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_EV,     TBL_HEADER_Y, 0, 0, sTextColorNormal, TEXT_SKIP_DRAW, COMPOUND_STRING("努力"));
    AddTextPrinterParameterized4(WIN_MAIN, FONT_SMALL_NARROW, TBL_X_IV,     TBL_HEADER_Y, 0, 0, sTextColorNormal, TEXT_SKIP_DRAW, COMPOUND_STRING("个体"));

    for (i = 0; i < NUM_STATS; i++)
        PrintStatRow(mon, i, TBL_ROW_Y0 + i * TBL_ROW_DY);

    PutWindowTilemap(WIN_MAIN);
    CopyWindowToVram(WIN_MAIN, COPYWIN_FULL);
}

static void ApplyStat(u16 statId, u16 value)
{
    struct Pokemon *mon = CurrentMon();
    u8 val = value;
    u32 curHp = GetMonData(mon, MON_DATA_HP);
    u32 oldMaxHp = GetMonData(mon, MON_DATA_MAX_HP);
    u32 hpLost = oldMaxHp - curHp;

    SetMonData(mon, statId, &val);
    CalculateMonStats(mon);

    if (hpLost > 0 && curHp != 0)
    {
        s32 newHp = (s32)GetMonData(mon, MON_DATA_MAX_HP) - (s32)hpLost;
        u32 setHp;

        if (newHp < 0)
            newHp = 0;
        setHp = (u32)newHp;
        SetMonData(mon, MON_DATA_HP, &setHp);
    }
}

static void ChangeStat(s16 delta)
{
    struct Pokemon *mon = CurrentMon();
    u16 statId = CurrentStatId();
    u16 cur = GetMonData(mon, statId);
    u16 cap;
    s32 newVal;

    if (delta > 0)
    {
        if (sData->selCol == EDIT_COL_IV)
        {
            cap = MAX_PER_STAT_IVS;
        }
        else
        {
            u16 remain = MAX_TOTAL_EVS - GetEvTotal(mon);

            cap = MAX_PER_STAT_EVS;
            if (cap > cur + remain)
                cap = cur + remain;
        }
        newVal = cur + delta;
        if (newVal > cap)
            newVal = cap;
    }
    else if (delta < 0)
    {
        newVal = (s32)cur + delta;
        if (newVal < 0)
            newVal = 0;
    }
    else
    {
        return;
    }

    ApplyStat(statId, (u16)newVal);
    PrintStats();
    PrintTitle();
}

static void SetStatToLimit(bool8 max)
{
    struct Pokemon *mon = CurrentMon();
    u16 statId = CurrentStatId();
    u16 value = 0;

    if (max)
    {
        if (sData->selCol == EDIT_COL_IV)
        {
            value = MAX_PER_STAT_IVS;
        }
        else
        {
            u16 cur = GetMonData(mon, statId);
            u16 remain = MAX_TOTAL_EVS - GetEvTotal(mon);

            value = MAX_PER_STAT_EVS;
            if (value > cur + remain)
                value = cur + remain;
        }
    }

    ApplyStat(statId, value);
    PrintStats();
    PrintTitle();
}

static void SwitchAbility(bool8 forward)
{
    struct Pokemon *mon = CurrentMon();
    u16 species = GetMonData(mon, MON_DATA_SPECIES);
    u8 cur = GetMonData(mon, MON_DATA_ABILITY_NUM);
    u8 slot = cur;
    u8 tries;

    for (tries = 0; tries < NUM_ABILITY_SLOTS; tries++)
    {
        if (forward)
            slot = (slot + 1) % NUM_ABILITY_SLOTS;
        else
            slot = (slot + NUM_ABILITY_SLOTS - 1) % NUM_ABILITY_SLOTS;

        if (slot == cur)
            return; // 绕回原点：没有其它可选特性

        if (gSpeciesInfo[species].abilities[slot] != ABILITY_NONE)
        {
            SetMonData(mon, MON_DATA_ABILITY_NUM, &slot);
            PrintTitle();
            PrintStats();
            return;
        }
    }
}

static void SwitchMon(bool8 forward)
{
    u16 count = gPartiesCount[B_TRAINER_PLAYER];

    if (count == 0)
        return;

    if (forward)
        sData->partyId = (sData->partyId + 1) % count;
    else
        sData->partyId = (sData->partyId + count - 1) % count;

    sData->selRow = 0;
    sData->selCol = EDIT_COL_EV;
    sData->editing = FALSE;

    LoadMonPicture();
    PrintTitle();
    PrintStats();
}

static void Task_StatEditorMain(u8 taskId)
{
    if (JOY_NEW(B_BUTTON))
    {
        if (sData->editing)
        {
            sData->editing = FALSE;
            PlaySE(SE_SELECT);
            PrintStats();
            return;
        }

        PlaySE(SE_PC_OFF);
        BeginNormalPaletteFade(0xFFFFFFFF, 0, 0, 16, RGB_BLACK);
        gTasks[taskId].func = Task_StatEditorFadeOut;
        return;
    }

    if (JOY_NEW(SELECT_BUTTON))
    {
        PlaySE(SE_SELECT);
        SwitchAbility(TRUE);
        return;
    }

    if (sData->editing)
    {
        if (JOY_NEW(DPAD_LEFT))
            ChangeStat(-1);
        else if (JOY_NEW(DPAD_RIGHT))
            ChangeStat(1);
        else if (JOY_NEW(DPAD_UP) || JOY_NEW(R_BUTTON))
            SetStatToLimit(TRUE);
        else if (JOY_NEW(DPAD_DOWN) || JOY_NEW(L_BUTTON))
            SetStatToLimit(FALSE);
        return;
    }

    if (JOY_NEW(DPAD_UP))
    {
        sData->selRow = (sData->selRow == 0) ? NUM_STATS - 1 : sData->selRow - 1;
        PlaySE(SE_SELECT);
        PrintStats();
    }
    else if (JOY_NEW(DPAD_DOWN))
    {
        sData->selRow = (sData->selRow == NUM_STATS - 1) ? 0 : sData->selRow + 1;
        PlaySE(SE_SELECT);
        PrintStats();
    }
    else if (JOY_NEW(DPAD_LEFT) || JOY_NEW(DPAD_RIGHT))
    {
        sData->selCol = (sData->selCol == EDIT_COL_EV) ? EDIT_COL_IV : EDIT_COL_EV;
        PlaySE(SE_SELECT);
        PrintStats();
    }
    else if (JOY_NEW(A_BUTTON))
    {
        sData->editing = TRUE;
        PlaySE(SE_SELECT);
        PrintStats();
    }
    else if (JOY_NEW(L_BUTTON))
    {
        PlaySE(SE_SELECT);
        SwitchMon(FALSE);
    }
    else if (JOY_NEW(R_BUTTON))
    {
        PlaySE(SE_SELECT);
        SwitchMon(TRUE);
    }
}

static void Task_StatEditorFadeOut(u8 taskId)
{
    if (!gPaletteFade.active)
    {
        MainCallback cb = sData->savedCallback;

        if (sData->iconSpriteId != 0xFFFF)
            FreeResourcesAndDestroySprite(&gSprites[sData->iconSpriteId], sData->iconSpriteId);
        FreeMonIconPalettes();
        FreeAllWindowBuffers();
        Free(sData);
        sData = NULL;
        SetMainCallback2(cb);
        DestroyTask(taskId);
    }
}

static void Task_StatEditorFadeIn(u8 taskId)
{
    if (!gPaletteFade.active)
        gTasks[taskId].func = Task_StatEditorMain;
}

static void VBlankCB_StatEditor(void)
{
    LoadOam();
    ProcessSpriteCopyRequests();
    TransferPlttBuffer();
}

static void CB2_StatEditorMain(void)
{
    RunTasks();
    AnimateSprites();
    BuildOamBuffer();
    DoScheduledBgTilemapCopiesToVram();
    UpdatePaletteFade();
}

static void CB2_StatEditorSetup(void)
{
    switch (gMain.state)
    {
    case 0:
        DmaClearLarge16(3, (void *)VRAM, VRAM_SIZE, 0x1000);
        SetVBlankHBlankCallbacksToNull();
        ResetVramOamAndBgCntRegs();
        ClearScheduledBgCopiesToVram();
        gMain.state++;
        break;
    case 1:
        ScanlineEffect_Stop();
        FreeAllSpritePalettes();
        ResetPaletteFade();
        ResetSpriteData();
        ResetTasks();
        gMain.state++;
        break;
    case 2:
        ResetBgsAndClearDma3BusyFlags(0);
        InitBgsFromTemplates(0, sBgTemplates, 1);
        SetGpuReg(REG_OFFSET_DISPCNT, DISPCNT_OBJ_ON | DISPCNT_OBJ_1D_MAP);
        ShowBg(0);
        InitWindows(sWindowTemplates);
        DeactivateAllTextPrinters();
        LoadPalette(sStatEditorPalette, BG_PLTT_ID(0), PLTT_SIZE_4BPP);
        LoadPalette(sStatEditorPalette, BG_PLTT_ID(15), PLTT_SIZE_4BPP);
        LoadMonIconPalettes();
        gMain.state++;
        break;
    case 3:
        LoadMonPicture();
        PrintTitle();
        PrintStats();
        CreateTask(Task_StatEditorFadeIn, 0);
        BlendPalettes(0xFFFFFFFF, 16, RGB_BLACK);
        gMain.state++;
        break;
    case 4:
        BeginNormalPaletteFade(0xFFFFFFFF, 0, 16, 0, RGB_BLACK);
        SetVBlankCallback(VBlankCB_StatEditor);
        SetMainCallback2(CB2_StatEditorMain);
        gMain.state++;
        break;
    }
}

void StatEditor_Init(MainCallback callback)
{
    sData = AllocZeroed(sizeof(*sData));
    if (sData == NULL)
    {
        SetMainCallback2(callback);
        return;
    }

    sData->savedCallback = callback;
    sData->iconSpriteId = 0xFFFF;

    sData->partyId = gSpecialVar_0x8004;
    if (sData->partyId >= gPartiesCount[B_TRAINER_PLAYER])
        sData->partyId = 0;

    gMain.state = 0;
    SetMainCallback2(CB2_StatEditorSetup);
}
