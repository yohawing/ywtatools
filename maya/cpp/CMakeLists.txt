cmake_minimum_required(VERSION 3.1...3.15)

if(${CMAKE_VERSION} VERSION_LESS 3.12)
    cmake_policy(VERSION ${CMAKE_MAJOR_VERSION}.${CMAKE_MINOR_VERSION})
endif()

cmake_policy(SET CMP0048 NEW)

project(ywtatools VERSION 1.0 DESCRIPTION "YohaWing TechArt Tools" LANGUAGES CXX)

set(CMAKE_INSTALL_PREFIX ${CMAKE_CURRENT_SOURCE_DIR})
set(CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/modules)

set(ENV{EIGEN3_ROOT_DIR} "${CMAKE_CURRENT_SOURCE_DIR}/third-party/Eigen")

# autoremesher_core (静的lib) を取り込む。ywtatools.mll は AutoRemesher コアを
# 直接静的リンクして呼び出すため、ywta_autoremesher (C ABI DLL, Blender用) の
# ビルドはここでは不要なのでOFFにする。
# (external/autoremesher / cpp/autoremesher_core の実装は変更しない)
set(YWTA_AUTOREMESHER_BUILD_DLL OFF CACHE BOOL "" FORCE)
set(YWTA_AUTOREMESHER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../../cpp/autoremesher_core"
    "${CMAKE_CURRENT_BINARY_DIR}/autoremesher_core"
)

add_subdirectory(src)
