#ifndef GUARD_STAT_EDITOR_H
#define GUARD_STAT_EDITOR_H

#include "main.h"

// Entry point. Opens the IV/EV stat editor UI over the current party member.
// `callback` is run when the editor is closed.
void StatEditor_Init(MainCallback callback);

#endif // GUARD_STAT_EDITOR_H
