// external/autoremesher/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/version.h は
// 本来 `#include "basic/version.h"` であるべき箇所が、リポジトリ上ではその
// パス文字列そのもの（"basic/version.h" という無効なC++）になっている
// （upstream側の既知の不具合。submoduleは変更しないためここで肩代わりする）。
//
// このシムを include path 上で本物より手前に置くことで
// `#include <geogram/version.h>` の解決先をこちらに差し替える。
#ifndef YWTA_AUTOREMESHER_GEOGRAM_VERSION_SHIM_H
#define YWTA_AUTOREMESHER_GEOGRAM_VERSION_SHIM_H

#include <geogram/basic/version.h>

#endif // YWTA_AUTOREMESHER_GEOGRAM_VERSION_SHIM_H
