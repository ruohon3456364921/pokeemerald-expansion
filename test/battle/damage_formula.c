#include "global.h"
#include "test/battle.h"

// From https://bulbapedia.bulbagarden.net/wiki/Damage#Example

SINGLE_BATTLE_TEST("Damage calculation matches Gen5+")
{
    s16 dmg;
    s16 expectedDamage;
    PARAMETRIZE { expectedDamage = 196; }
    PARAMETRIZE { expectedDamage = 192; }
    PARAMETRIZE { expectedDamage = 192; }
    PARAMETRIZE { expectedDamage = 192; }
    PARAMETRIZE { expectedDamage = 184; }
    PARAMETRIZE { expectedDamage = 184; }
    PARAMETRIZE { expectedDamage = 184; }
    PARAMETRIZE { expectedDamage = 180; }
    PARAMETRIZE { expectedDamage = 180; }
    PARAMETRIZE { expectedDamage = 180; }
    PARAMETRIZE { expectedDamage = 172; }
    PARAMETRIZE { expectedDamage = 172; }
    PARAMETRIZE { expectedDamage = 172; }
    PARAMETRIZE { expectedDamage = 168; }
    PARAMETRIZE { expectedDamage = 168; }
    PARAMETRIZE { expectedDamage = 168; }
    GIVEN {
        ASSUME(GetMoveCategory(MOVE_ICE_FANG) == DAMAGE_CATEGORY_PHYSICAL);
        PLAYER(SPECIES_GLACEON) { Level(75); Attack(123); }
        OPPONENT(SPECIES_GARCHOMP) { Defense(163); }
    } WHEN {
        TURN {
            MOVE(player, MOVE_ICE_FANG, WITH_RNG(RNG_DAMAGE_MODIFIER, i));
        }
    }
    SCENE {
        MESSAGE("Glaceon used Ice Fang!");
        HP_BAR(opponent, captureDamage: &dmg);
    }
    THEN {
        EXPECT_EQ(expectedDamage, dmg);
    }
}

SINGLE_BATTLE_TEST("Damage calculation matches Gen6+ (Muscle Band, crit)")
{
    s16 dmg;
    s16 expectedDamage;
    PARAMETRIZE { expectedDamage = 324; }
    PARAMETRIZE { expectedDamage = 316; }
    PARAMETRIZE { expectedDamage = 312; }
    PARAMETRIZE { expectedDamage = 312; }
    PARAMETRIZE { expectedDamage = 304; }
    PARAMETRIZE { expectedDamage = 304; }
    PARAMETRIZE { expectedDamage = 300; }
    PARAMETRIZE { expectedDamage = 300; }
    PARAMETRIZE { expectedDamage = 292; }
    PARAMETRIZE { expectedDamage = 292; }
    PARAMETRIZE { expectedDamage = 288; }
    PARAMETRIZE { expectedDamage = 288; }
    PARAMETRIZE { expectedDamage = 280; }
    PARAMETRIZE { expectedDamage = 276; }
    PARAMETRIZE { expectedDamage = 276; }
    PARAMETRIZE { expectedDamage = 268; }
    GIVEN {
        WITH_CONFIG(B_CRIT_MULTIPLIER, GEN_6);
        ASSUME(GetMoveCategory(MOVE_ICE_FANG) == DAMAGE_CATEGORY_PHYSICAL);
        PLAYER(SPECIES_GLACEON) { Level(75); Attack(123); Item(ITEM_MUSCLE_BAND); }
        OPPONENT(SPECIES_GARCHOMP) { Defense(163); }
    } WHEN {
        TURN {
            MOVE(player, MOVE_ICE_FANG, WITH_RNG(RNG_DAMAGE_MODIFIER, i), criticalHit: TRUE);
        }
    }
    SCENE {
        MESSAGE("Glaceon used Ice Fang!");
        HP_BAR(opponent, captureDamage: &dmg);
    }
    THEN {
        EXPECT_EQ(expectedDamage, dmg);
    }
}

SINGLE_BATTLE_TEST("Damage calculation matches Gen5+ (Marshadow vs Mawile)")
{
    s16 dmg;
    s16 expectedDamage;
    PARAMETRIZE { expectedDamage = 145; }
    PARAMETRIZE { expectedDamage = 144; }
    PARAMETRIZE { expectedDamage = 142; }
    PARAMETRIZE { expectedDamage = 141; }
    PARAMETRIZE { expectedDamage = 139; }
    PARAMETRIZE { expectedDamage = 138; }
    PARAMETRIZE { expectedDamage = 136; }
    PARAMETRIZE { expectedDamage = 135; }
    PARAMETRIZE { expectedDamage = 133; }
    PARAMETRIZE { expectedDamage = 132; }
    PARAMETRIZE { expectedDamage = 130; }
    PARAMETRIZE { expectedDamage = 129; }
    PARAMETRIZE { expectedDamage = 127; }
    PARAMETRIZE { expectedDamage = 126; }
    PARAMETRIZE { expectedDamage = 124; }
    PARAMETRIZE { expectedDamage = 123; }
    GIVEN {
        ASSUME(GetMoveCategory(MOVE_SPECTRAL_THIEF) == DAMAGE_CATEGORY_PHYSICAL);
        ASSUME(B_UPDATED_TYPE_MATCHUPS >= GEN_6); // Steel resists Ghost in Gen2-5
        PLAYER(SPECIES_MARSHADOW) { Level(100); Attack(286); }
        OPPONENT(SPECIES_MAWILE) { Level(100); Defense(226); HP(241); }
    } WHEN {
        TURN {
            MOVE(player, MOVE_SPECTRAL_THIEF, WITH_RNG(RNG_DAMAGE_MODIFIER, i), criticalHit: FALSE);
        }
    }
    SCENE{
        MESSAGE("Marshadow used Spectral Thief!");
        HP_BAR(opponent, captureDamage: &dmg);
    }
    THEN{
        EXPECT_EQ(expectedDamage, dmg);
    }
}

DOUBLE_BATTLE_TEST("A spread move will do correct damage to the second mon if the first target faints from first hit of the spread move (double battle)")
{
    s16 damage[6];
    GIVEN {
        PLAYER(SPECIES_REGIROCK);
        PLAYER(SPECIES_REGIROCK);
        OPPONENT(SPECIES_WOBBUFFET) { HP(200); }
        OPPONENT(SPECIES_WOBBUFFET) { MaxHP(999); HP(999); }
    } WHEN {
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); MOVE(playerRight, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
    } SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[0]);
        HP_BAR(opponentRight, captureDamage: &damage[1]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[2]);
        HP_BAR(opponentRight, captureDamage: &damage[3]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerRight);
        HP_BAR(opponentRight, captureDamage: &damage[4]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentRight, captureDamage: &damage[5]);
    } THEN {
        EXPECT_EQ(damage[0], damage[1]);
        EXPECT_EQ(damage[1], damage[3]);
        EXPECT_MUL_EQ(damage[5], UQ_4_12(0.75), damage[3]);
        EXPECT_EQ(damage[4], damage[5]);
    }
}

MULTI_BATTLE_TEST("A spread move will do correct damage to the second mon if the first target faints from first hit of the spread move (multibattle)")
{
    s16 damage[6];
    GIVEN {
        PLAYER(SPECIES_REGIROCK);
        PARTNER(SPECIES_REGIROCK);
        OPPONENT_A(SPECIES_WOBBUFFET) { HP(200); }
        OPPONENT_B(SPECIES_WOBBUFFET) { MaxHP(999); HP(999); }
    } WHEN {
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); MOVE(playerRight, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
    } SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[0]);
        HP_BAR(opponentRight, captureDamage: &damage[1]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[2]);
        HP_BAR(opponentRight, captureDamage: &damage[3]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerRight);
        HP_BAR(opponentRight, captureDamage: &damage[4]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentRight, captureDamage: &damage[5]);
    } THEN {
        EXPECT_EQ(damage[0], damage[1]);
        EXPECT_EQ(damage[1], damage[3]);
        EXPECT_MUL_EQ(damage[5], UQ_4_12(0.75), damage[3]);
        EXPECT_EQ(damage[4], damage[5]);
    }
}

TWO_VS_ONE_BATTLE_TEST("A spread move will do correct damage to the second mon if the first target faints from first hit of the spread move (2v1)")
{
    s16 damage[6];
    GIVEN {
        PLAYER(SPECIES_REGIROCK);
        PARTNER(SPECIES_REGIROCK);
        OPPONENT_A(SPECIES_WOBBUFFET) { HP(200); }
        OPPONENT_A(SPECIES_WOBBUFFET) { MaxHP(999); HP(999); }
    } WHEN {
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); MOVE(playerRight, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
    } SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[0]);
        HP_BAR(opponentRight, captureDamage: &damage[1]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[2]);
        HP_BAR(opponentRight, captureDamage: &damage[3]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerRight);
        HP_BAR(opponentRight, captureDamage: &damage[4]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentRight, captureDamage: &damage[5]);
    } THEN {
        EXPECT_EQ(damage[0], damage[1]);
        EXPECT_EQ(damage[1], damage[3]);
        EXPECT_MUL_EQ(damage[5], UQ_4_12(0.75), damage[3]);
        EXPECT_EQ(damage[4], damage[5]);
    }
}

ONE_VS_TWO_BATTLE_TEST("A spread move will do correct damage to the second mon if the first target faints from first hit of the spread move (1v2)")
{
    s16 damage[6];
    GIVEN {
        PLAYER(SPECIES_REGIROCK);
        PLAYER(SPECIES_REGIROCK);
        OPPONENT_A(SPECIES_WOBBUFFET) { HP(200); }
        OPPONENT_B(SPECIES_WOBBUFFET) { MaxHP(999); HP(999); }
    } WHEN {
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); MOVE(playerRight, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
        TURN { MOVE(playerLeft, MOVE_ROCK_SLIDE, WITH_RNG(RNG_DAMAGE_MODIFIER, 0)); }
    } SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[0]);
        HP_BAR(opponentRight, captureDamage: &damage[1]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damage[2]);
        HP_BAR(opponentRight, captureDamage: &damage[3]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerRight);
        HP_BAR(opponentRight, captureDamage: &damage[4]);

        ANIMATION(ANIM_TYPE_MOVE, MOVE_ROCK_SLIDE, playerLeft);
        HP_BAR(opponentRight, captureDamage: &damage[5]);
    } THEN {
        EXPECT_EQ(damage[0], damage[1]);
        EXPECT_EQ(damage[1], damage[3]);
        EXPECT_MUL_EQ(damage[5], UQ_4_12(0.75), damage[3]);
        EXPECT_EQ(damage[4], damage[5]);
    }
}

SINGLE_BATTLE_TEST("Punching Glove vs Muscle Band Damage calculation")
{
    s16 dmgPlayer, dmgOpponent;
    s16 expectedDamagePlayer, expectedDamageOpponent;
    PARAMETRIZE { expectedDamagePlayer = 218, expectedDamageOpponent = 214; }
    PARAMETRIZE { expectedDamagePlayer = 214, expectedDamageOpponent = 211; }
    PARAMETRIZE { expectedDamagePlayer = 213, expectedDamageOpponent = 210; }
    PARAMETRIZE { expectedDamagePlayer = 210, expectedDamageOpponent = 206; }
    PARAMETRIZE { expectedDamagePlayer = 208, expectedDamageOpponent = 205; }
    PARAMETRIZE { expectedDamagePlayer = 206, expectedDamageOpponent = 203; }
    PARAMETRIZE { expectedDamagePlayer = 203, expectedDamageOpponent = 200; }
    PARAMETRIZE { expectedDamagePlayer = 202, expectedDamageOpponent = 198; }
    PARAMETRIZE { expectedDamagePlayer = 200, expectedDamageOpponent = 197; }
    PARAMETRIZE { expectedDamagePlayer = 197, expectedDamageOpponent = 194; }
    PARAMETRIZE { expectedDamagePlayer = 195, expectedDamageOpponent = 192; }
    PARAMETRIZE { expectedDamagePlayer = 194, expectedDamageOpponent = 190; }
    PARAMETRIZE { expectedDamagePlayer = 190, expectedDamageOpponent = 187; }
    PARAMETRIZE { expectedDamagePlayer = 189, expectedDamageOpponent = 186; }
    PARAMETRIZE { expectedDamagePlayer = 186, expectedDamageOpponent = 184; }
    PARAMETRIZE { expectedDamagePlayer = 184, expectedDamageOpponent = 181; }
    GIVEN {
        PLAYER(SPECIES_MAKUHITA) { Item(ITEM_PUNCHING_GLOVE); }
        OPPONENT(SPECIES_MAKUHITA) { Item(ITEM_MUSCLE_BAND); }
    } WHEN {
        TURN {
            MOVE(player, MOVE_DRAIN_PUNCH, WITH_RNG(RNG_DAMAGE_MODIFIER, i));
            MOVE(opponent, MOVE_DRAIN_PUNCH, WITH_RNG(RNG_DAMAGE_MODIFIER, i));
        }
    }
    SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_DRAIN_PUNCH, player);
        HP_BAR(opponent, captureDamage: &dmgPlayer);
        ANIMATION(ANIM_TYPE_MOVE, MOVE_DRAIN_PUNCH, opponent);
        HP_BAR(player, captureDamage: &dmgOpponent);
    }
    THEN {
        EXPECT_EQ(expectedDamagePlayer, dmgPlayer);
        EXPECT_EQ(expectedDamageOpponent, dmgOpponent);
    }
}

SINGLE_BATTLE_TEST("Gem boosted Damage calculation")
{
    s16 dmg;
    s16 expectedDamage;
#if I_GEM_BOOST_POWER >= GEN_6
    PARAMETRIZE { expectedDamage = 256; }
    PARAMETRIZE { expectedDamage = 253; }
    PARAMETRIZE { expectedDamage = 250; }
    PARAMETRIZE { expectedDamage = 248; }
    PARAMETRIZE { expectedDamage = 245; }
    PARAMETRIZE { expectedDamage = 243; }
    PARAMETRIZE { expectedDamage = 240; }
    PARAMETRIZE { expectedDamage = 237; }
    PARAMETRIZE { expectedDamage = 235; }
    PARAMETRIZE { expectedDamage = 232; }
    PARAMETRIZE { expectedDamage = 230; }
    PARAMETRIZE { expectedDamage = 227; }
    PARAMETRIZE { expectedDamage = 224; }
    PARAMETRIZE { expectedDamage = 222; }
    PARAMETRIZE { expectedDamage = 219; }
    PARAMETRIZE { expectedDamage = 218; }
#else
    PARAMETRIZE { expectedDamage = 273; }
    PARAMETRIZE { expectedDamage = 270; }
    PARAMETRIZE { expectedDamage = 267; }
    PARAMETRIZE { expectedDamage = 264; }
    PARAMETRIZE { expectedDamage = 261; }
    PARAMETRIZE { expectedDamage = 258; }
    PARAMETRIZE { expectedDamage = 256; }
    PARAMETRIZE { expectedDamage = 253; }
    PARAMETRIZE { expectedDamage = 250; }
    PARAMETRIZE { expectedDamage = 247; }
    PARAMETRIZE { expectedDamage = 244; }
    PARAMETRIZE { expectedDamage = 241; }
    PARAMETRIZE { expectedDamage = 240; }
    PARAMETRIZE { expectedDamage = 237; }
    PARAMETRIZE { expectedDamage = 234; }
    PARAMETRIZE { expectedDamage = 231; }
#endif
    GIVEN {
        PLAYER(SPECIES_MAKUHITA) { Item(ITEM_FIGHTING_GEM); }
        OPPONENT(SPECIES_MAKUHITA) { MaxHP(999); HP(999); }
    } WHEN {
        TURN {
            MOVE(player, MOVE_DRAIN_PUNCH, WITH_RNG(RNG_DAMAGE_MODIFIER, i));
        }
    }
    SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_DRAIN_PUNCH, player);
        HP_BAR(opponent, captureDamage: &dmg);
    }
    THEN {
        EXPECT_EQ(expectedDamage, dmg);
    }
}

#define NUM_DAMAGE_SPREADS (DMG_ROLL_PERCENT_HI - DMG_ROLL_PERCENT_LO) + 1

static const s16 sThunderShockTransistorSpreadGen9[] = { 58, 59, 60, 61, 61, 62, 63, 64, 64, 65, 65, 66, 67, 68, 69, 69 };
static const s16 sThunderShockTransistorSpreadGen8[] = { 68, 69, 69, 70, 71, 72, 73, 73, 74, 75, 76, 77, 77, 78, 79, 80 };
static const s16 sThunderShockRegularSpread[] = { 45, 45, 46, 46, 47, 48, 48, 49, 49, 49, 50, 51, 51, 52, 53, 53 };
static const s16 sWildChargeTransistorSpreadGen9[] = { 131, 133, 134, 136, 137, 139, 141, 142, 144, 145, 147, 149, 150, 152, 153, 155 };
static const s16 sWildChargeTransistorSpreadGen8[] = { 151, 153, 155, 157, 158, 160, 161, 164, 165, 167, 169, 171, 173, 174, 176, 178 };
static const s16 sWildChargeRegularSpread[] = { 101, 102, 103, 105, 105, 107, 108, 109, 110, 112, 113, 114, 115, 117, 117, 119 };

DOUBLE_BATTLE_TEST("Transistor Damage calculation", s16 damage)
{
    s16 expectedDamageTransistorSpec = 0, expectedDamageRegularPhys = 0, expectedDamageRegularSpec = 0, expectedDamageTransistorPhys = 0;
    s16 damagePlayerLeft, damagePlayerRight, damageOpponentLeft, damageOpponentRight;
    u32 gen = 0;
    for (u32 spread = 0; spread < 16; ++spread) {
        PARAMETRIZE { gen = GEN_9,
                      expectedDamageTransistorSpec = sThunderShockTransistorSpreadGen9[spread],
                      expectedDamageRegularSpec = sThunderShockRegularSpread[spread];
                      expectedDamageTransistorPhys = sWildChargeTransistorSpreadGen9[spread],
                      expectedDamageRegularPhys = sWildChargeRegularSpread[spread];
                    }
    }
    for (u32 spread = 0; spread < 16; ++spread) {
        PARAMETRIZE { gen = GEN_8,
                      expectedDamageTransistorSpec = sThunderShockTransistorSpreadGen8[spread],
                      expectedDamageRegularSpec = sThunderShockRegularSpread[spread],
                      expectedDamageTransistorPhys = sWildChargeTransistorSpreadGen8[spread],
                      expectedDamageRegularPhys = sWildChargeRegularSpread[spread];
                    }
    }
    GIVEN {
        WITH_CONFIG(B_TRANSISTOR_BOOST, gen);
        ASSUME(GetMoveType(MOVE_WILD_CHARGE) == TYPE_ELECTRIC);
        ASSUME(GetMoveType(MOVE_THUNDER_SHOCK) == TYPE_ELECTRIC);
        ASSUME(GetMoveCategory(MOVE_WILD_CHARGE) == DAMAGE_CATEGORY_PHYSICAL);
        ASSUME(GetMoveCategory(MOVE_THUNDER_SHOCK) == DAMAGE_CATEGORY_SPECIAL);
        ASSUME(NUM_DAMAGE_SPREADS == 16);

        PLAYER(SPECIES_REGIELEKI) { Ability(ABILITY_KLUTZ); }
        PLAYER(SPECIES_REGIELEKI) { Ability(ABILITY_TRANSISTOR); }
        OPPONENT(SPECIES_REGIELEKI) { Ability(ABILITY_KLUTZ); }
        OPPONENT(SPECIES_REGIELEKI) { Ability(ABILITY_TRANSISTOR); }
    } WHEN {
        TURN {
            MOVE(playerLeft, MOVE_THUNDER_SHOCK, target: opponentLeft, WITH_RNG(RNG_DAMAGE_MODIFIER, 15 - (i % 16)));
            MOVE(playerRight, MOVE_THUNDER_SHOCK, target: opponentRight, WITH_RNG(RNG_DAMAGE_MODIFIER, 15 - (i % 16)));
            MOVE(opponentLeft, MOVE_WILD_CHARGE, target: playerLeft, WITH_RNG(RNG_DAMAGE_MODIFIER, 15 - (i % 16)));
            MOVE(opponentRight, MOVE_WILD_CHARGE, target: playerRight, WITH_RNG(RNG_DAMAGE_MODIFIER, 15 - (i % 16)));
        }
    } SCENE {
        ANIMATION(ANIM_TYPE_MOVE, MOVE_THUNDER_SHOCK, playerLeft);
        HP_BAR(opponentLeft, captureDamage: &damageOpponentLeft);
        ANIMATION(ANIM_TYPE_MOVE, MOVE_THUNDER_SHOCK, playerRight);
        HP_BAR(opponentRight, captureDamage: &damageOpponentRight);
        ANIMATION(ANIM_TYPE_MOVE, MOVE_WILD_CHARGE, opponentLeft);
        HP_BAR(playerLeft, captureDamage: &damagePlayerLeft);
        ANIMATION(ANIM_TYPE_MOVE, MOVE_WILD_CHARGE, opponentRight);
        HP_BAR(playerRight, captureDamage: &damagePlayerRight);
    } THEN {
        EXPECT_EQ(damageOpponentLeft, expectedDamageRegularSpec);
        EXPECT_EQ(damageOpponentRight, expectedDamageTransistorSpec);
        EXPECT_EQ(damagePlayerLeft, expectedDamageRegularPhys);
        EXPECT_EQ(damagePlayerRight, expectedDamageTransistorPhys);
    }
}

SINGLE_BATTLE_TEST("Damage calculation for Protosynthesis")
{
    s16 dmg;
    s16 expectedDamage;
    PARAMETRIZE { expectedDamage = 91; }
    PARAMETRIZE { expectedDamage = 90; }
    PARAMETRIZE { expectedDamage = 88; }
    PARAMETRIZE { expectedDamage = 87; }
    PARAMETRIZE { expectedDamage = 87; }
    PARAMETRIZE { expectedDamage = 86; }
    PARAMETRIZE { expectedDamage = 85; }
    PARAMETRIZE { expectedDamage = 85; }
    PARAMETRIZE { expectedDamage = 83; }
    PARAMETRIZE { expectedDamage = 82; }
    PARAMETRIZE { expectedDamage = 82; }
    PARAMETRIZE { expectedDamage = 81; }
    PARAMETRIZE { expectedDamage = 79; }
    PARAMETRIZE { expectedDamage = 78; }
    PARAMETRIZE { expectedDamage = 78; }
    PARAMETRIZE { expectedDamage = 77; }
    GIVEN {
        ASSUME(GetMoveCategory(MOVE_CLOSE_COMBAT) == DAMAGE_CATEGORY_PHYSICAL);
        PLAYER(SPECIES_URSHIFU_RAPID_STRIKE) { Level(95); Attack(281); }
        OPPONENT(SPECIES_GOUGING_FIRE) { Defense(305); Ability(ABILITY_PROTOSYNTHESIS); Item(ITEM_BOOSTER_ENERGY); }
    } WHEN {
        TURN {
            MOVE(player, MOVE_CLOSE_COMBAT, WITH_RNG(RNG_DAMAGE_MODIFIER, i));
        }
    }
    SCENE {
        HP_BAR(opponent, captureDamage: &dmg);
    }
    THEN {
        EXPECT_EQ(expectedDamage, dmg);
    }
}
