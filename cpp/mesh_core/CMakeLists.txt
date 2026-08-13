cmake_minimum_required(VERSION 3.20)

project(ywta_mesh_core LANGUAGES CXX)

add_library(ywta_mesh_core_core STATIC
    src/hair_tube_cage.cpp
    src/hair_tube_topology.cpp
    src/raw_topology.cpp
)
target_include_directories(ywta_mesh_core_core PUBLIC include)
target_compile_features(ywta_mesh_core_core PUBLIC cxx_std_17)
if(MSVC)
    target_compile_options(ywta_mesh_core_core PUBLIC /utf-8 PRIVATE /W4)
else()
    target_compile_options(ywta_mesh_core_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

option(YWTA_MESH_CORE_BUILD_TESTS "Build mesh core tests" ON)
if(YWTA_MESH_CORE_BUILD_TESTS)
    enable_testing()
    add_executable(ywta_mesh_core_tests
        tests/raw_topology_test.cpp
    )
    target_link_libraries(ywta_mesh_core_tests PRIVATE ywta_mesh_core_core)
    if(MSVC)
        target_compile_options(ywta_mesh_core_tests PRIVATE /W4)
    else()
        target_compile_options(ywta_mesh_core_tests PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME ywta_mesh_core_tests COMMAND ywta_mesh_core_tests)

    add_executable(ywta_hair_tube_topology_tests
        tests/hair_tube_topology_test.cpp
    )
    target_link_libraries(ywta_hair_tube_topology_tests PRIVATE ywta_mesh_core_core)
    if(MSVC)
        target_compile_options(ywta_hair_tube_topology_tests PRIVATE /W4)
    else()
        target_compile_options(ywta_hair_tube_topology_tests PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME ywta_hair_tube_topology_tests COMMAND ywta_hair_tube_topology_tests)

    add_executable(ywta_hair_tube_cage_tests
        tests/hair_tube_cage_test.cpp
    )
    target_link_libraries(ywta_hair_tube_cage_tests PRIVATE ywta_mesh_core_core)
    if(MSVC)
        target_compile_options(ywta_hair_tube_cage_tests PRIVATE /W4)
    else()
        target_compile_options(ywta_hair_tube_cage_tests PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME ywta_hair_tube_cage_tests COMMAND ywta_hair_tube_cage_tests)
endif()
