# AutoRemesher コア静的ライブラリ + C ABI DLL
#
# external/autoremesher (submodule, MIT, タグ 1.0.0 に pin) の Qt 非依存な
# コア（src/AutoRemesher/*）と、そのビルドに必要な thirdparty
# （geogram 1.8.3 / isotropicremesher / tbb をソースからビルド、Eigen はヘッダオンリー）
# を GUI 抜きでビルドする。ソースファイル一覧・DEFINES・INCLUDEPATH は
# external/autoremesher/autoremesher.pro を精読して移植したもの。
#
# ターゲット:
#   autoremesher_core (STATIC) - AutoRemesher コア + thirdparty
#   ywta_autoremesher  (SHARED) - capi.cpp の C ABI ラッパー DLL（Blender等から ctypes で利用）
#
# external/autoremesher 以下のファイルは一切変更しないこと。

cmake_minimum_required(VERSION 3.15)

project(ywta_autoremesher_core LANGUAGES C CXX)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 99)

if(MSVC)
    # autoremesher.pro と同じく /MD 系ランタイム（DLL境界のCRT不整合を避ける）
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")
endif()

# 古い thirdparty/tbb の CMakeLists.txt (cmake_minimum_required 2.8) を
# 新しい CMake でもポリシーエラーなしに処理できるようにする
if(POLICY CMP0091)
    cmake_policy(SET CMP0091 NEW)
endif()
set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "" FORCE)

set(AR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../external/autoremesher")
get_filename_component(AR_ROOT "${AR_ROOT}" ABSOLUTE)

if(NOT EXISTS "${AR_ROOT}/src/AutoRemesher/autoremesher.h")
    message(FATAL_ERROR "external/autoremesher submodule が見つかりません。`git submodule update --init` を実行してください。 (${AR_ROOT})")
endif()

# ---------------------------------------------------------------------------
# TBB (静的ライブラリ tbb_static のみビルド。shared/malloc/tests は不要)
# ---------------------------------------------------------------------------
set(TBB_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(TBB_BUILD_STATIC ON CACHE BOOL "" FORCE)
set(TBB_BUILD_TBBMALLOC OFF CACHE BOOL "" FORCE)
set(TBB_BUILD_TBBMALLOC_PROXY OFF CACHE BOOL "" FORCE)
set(TBB_BUILD_TESTS OFF CACHE BOOL "" FORCE)

add_subdirectory("${AR_ROOT}/thirdparty/tbb" "${CMAKE_CURRENT_BINARY_DIR}/tbb" EXCLUDE_FROM_ALL)

if(TARGET tbb_static)
    # tbb/internal/_tbb_windef.h は __TBB_BUILD (tbb_static自身のビルド定義) が
    # 立っていると `#pragma comment(lib, "tbb.lib")` を埋め込み、
    # 静的リンクしているにもかかわらず動的版 tbb.lib を要求してリンクエラーになる。
    # 明示的にCMakeでリンクするため、暗黙リンクは両側（tbb_static本体・利用側）で無効化する。
    target_compile_definitions(tbb_static PUBLIC __TBB_NO_IMPLICIT_LINKAGE=1)
endif()

# ---------------------------------------------------------------------------
# autoremesher_core (STATIC)
# ---------------------------------------------------------------------------
set(CORE_SOURCES
    ${AR_ROOT}/src/AutoRemesher/autoremesher.cpp
    ${AR_ROOT}/src/AutoRemesher/isotropicremesher.cpp
    ${AR_ROOT}/thirdparty/isotropicremesher/isotropicremesher.cpp
    ${AR_ROOT}/thirdparty/isotropicremesher/isotropichalfedgemesh.cpp
    ${AR_ROOT}/thirdparty/isotropicremesher/axisalignedboundingboxtree.cpp
    ${AR_ROOT}/src/AutoRemesher/parameterizer.cpp
    ${AR_ROOT}/src/AutoRemesher/quadextractor.cpp
    ${AR_ROOT}/src/AutoRemesher/positionkey.cpp
    ${AR_ROOT}/src/AutoRemesher/meshseparator.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/algorithm.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/assert.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/attributes.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/b_stream.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/command_line.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/command_line_args.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/common.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/counted.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/environment.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/factory.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/file_system.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/geofile.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/geometry.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/line_stream.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/logger.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/numeric.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/packed_arrays.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/process.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/process_win.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/progress.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/quaternion.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/stopwatch.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/basic/string.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/bibliography/bibliography.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/bibliography/embedded_references.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/LFS.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/delaunay.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/delaunay_2d.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/delaunay_3d.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/delaunay_nn.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/delaunay_tetgen.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/delaunay_triangle.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/parallel_delaunay_3d.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/periodic.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/delaunay/periodic_delaunay_3d.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/colormap.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image_library.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image_rasterizer.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image_serializer.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image_serializer_pgm.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image_serializer_stb.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/image_serializer_xpm.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/image/morpho_math.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_AABB.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_fill_holes.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_frame_field.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_geometry.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_halfedges.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_io.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_partition.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_preprocessing.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_reorder.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_repair.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/mesh/mesh_topology.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/numerics/expansion_nt.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/numerics/lbfgs_optimizers.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/numerics/matrix_util.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/numerics/multi_precision.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/numerics/optimizer.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/numerics/predicates.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/parameterization/mesh_global_param.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/points/co3ne.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/points/colocate.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/points/kd_tree.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/points/nn_search.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/points/principal_axes.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/CVT.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/RVD.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/RVD_callback.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/RVD_mesh_builder.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/convex_cell.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/generic_RVD_cell.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/generic_RVD_polygon.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/voronoi/integration_simplex.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/exploragram/hexdom/basic.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/exploragram/hexdom/frame.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/exploragram/hexdom/spherical_harmonics_l4.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/exploragram/hexdom/polygon.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/exploragram/hexdom/quad_cover.cpp
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_api.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_matrix.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_context.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_blas.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_arpack.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_iterative_solvers.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_preconditioners.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL/nl_os.c
    ${AR_ROOT}/src/AutoRemesher/nl_ext_stubs.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/libMeshb/sources/libmeshb7.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/rply/rply.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/adler32.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/compress.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/crc32.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/deflate.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/gzclose.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/gzlib.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/gzread.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/gzwrite.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/inffast.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/inflate.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/inftrees.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/trees.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/uncompr.c
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib/zutil.c
)

add_library(autoremesher_core STATIC ${CORE_SOURCES})

# qtshim: submoduleを変更せずに (1) Qt非依存ビルドのための QDebug シム、
# (2) geogram/version.h の既知の不具合(内容が "basic/version.h" という文字列の
# みで#includeになっていない)を回避するための version.h シム、を提供する。
# 他のインクルードパスより必ず手前に検索させる必要があるため BEFORE を使う。
target_include_directories(autoremesher_core BEFORE PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/qtshim
)

target_include_directories(autoremesher_core PUBLIC
    ${AR_ROOT}/include
    ${AR_ROOT}/thirdparty/eigen
    ${AR_ROOT}/thirdparty/isotropicremesher
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/libMeshb/sources
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/third_party/zlib
    ${AR_ROOT}/thirdparty/geogram/geogram-1.8.3/src/lib/geogram/NL
    ${AR_ROOT}/thirdparty/geogram
    ${AR_ROOT}/thirdparty/tbb/include
)

target_compile_definitions(autoremesher_core PUBLIC
    _USE_MATH_DEFINES
    NOMINMAX
    _CRT_SECURE_NO_WARNINGS
    _SCL_SECURE_NO_WARNINGS
)

target_link_libraries(autoremesher_core PUBLIC tbb_static)

if(WIN32)
    target_link_libraries(autoremesher_core PUBLIC advapi32 shell32)
    # autoremesher.pro: `DEFINES -= UNICODE`（ANSI版WinAPIを使う）。
    # CMakeでは既定でUNICODE/_UNICODEを定義しないため、明示的な対応は不要。
endif()

if(MSVC)
    target_compile_options(autoremesher_core PRIVATE /bigobj /MP)
    # 大量の警告が出るが、サードパーティコードなのでビルドを止めない
    target_compile_options(autoremesher_core PRIVATE /W0)
endif()

set_target_properties(autoremesher_core PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    FOLDER "autoremesher"
)

# ---------------------------------------------------------------------------
# ywta_autoremesher (SHARED) - C ABI DLL
# ---------------------------------------------------------------------------
add_library(ywta_autoremesher SHARED
    capi.h
    capi.cpp
)

target_link_libraries(ywta_autoremesher PRIVATE autoremesher_core)

target_compile_definitions(ywta_autoremesher PRIVATE YWTA_AUTOREMESHER_BUILD_DLL)

if(MSVC)
    target_compile_options(ywta_autoremesher PRIVATE /bigobj)
endif()

set_target_properties(ywta_autoremesher PROPERTIES
    FOLDER "autoremesher"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/output"
)
