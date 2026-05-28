# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
cmake_minimum_required(VERSION 3.20)
project(cap_sdk_cpp VERSION 0.1.0 LANGUAGES CXX)

# C++17 minimum per ADR-011 (RHEL 8 / Ubuntu 20.04 LTS ship gcc-9).
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(CAP_SDK_BUILD_TESTS "Build the C++ SDK unit tests" OFF)

find_package(Protobuf REQUIRED)
find_package(gRPC CONFIG REQUIRED)

include(GNUInstallDirs)

# ─── Generated proto sources (from `buf generate`) ───────────────────
# Post Phase-0.3 reorg, Core lives under cap/v0/core/ and the
# Construction Domain Pack under cap/v0/domains/construction/.
set(CAP_GEN_DIR "${CMAKE_SOURCE_DIR}/../../cap-spec/gen/cpp"
    CACHE PATH "Path to buf-generated C++ proto sources")

file(GLOB CAP_CORE_PROTO_SRCS  "${CAP_GEN_DIR}/cap/v0/core/*.pb.cc")
file(GLOB CAP_CONSTRUCTION_SRCS "${CAP_GEN_DIR}/cap/v0/domains/construction/*.pb.cc")

# ─── cap_sdk_core (compiled: proto + frame_builder + client) ─────────
add_library(cap_sdk_core
    src/frame_builder.cpp
    src/client.cpp
    ${CAP_CORE_PROTO_SRCS}
)
add_library(cap::sdk_core ALIAS cap_sdk_core)

target_include_directories(cap_sdk_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CAP_GEN_DIR}>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_link_libraries(cap_sdk_core PUBLIC
    protobuf::libprotobuf
    gRPC::grpc++
)

# ─── cap_sdk_construction (header-only Domain Pack shim) ─────────────
add_library(cap_sdk_construction INTERFACE)
add_library(cap::sdk_construction ALIAS cap_sdk_construction)
target_include_directories(cap_sdk_construction INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
# Compiled construction proto, when present, is linked into core consumers
# that need it. At v0.1 the Domain Pack shim is header-only constants.
if(CAP_CONSTRUCTION_SRCS)
    target_sources(cap_sdk_core PRIVATE ${CAP_CONSTRUCTION_SRCS})
endif()

# ─── Install + export (find_package(cap_sdk_core) support) ───────────
install(TARGETS cap_sdk_core cap_sdk_construction
    EXPORT cap_sdk_coreTargets
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install(DIRECTORY include/cap_sdk_core include/cap_sdk_construction
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install(EXPORT cap_sdk_coreTargets
    FILE cap_sdk_coreTargets.cmake
    NAMESPACE cap::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/cap_sdk_core
)

include(CMakePackageConfigHelpers)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/cap_sdk_coreConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)
# A minimal generated config that re-exports the targets file.
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/cap_sdk_coreConfig.cmake"
"include(CMakeFindDependencyMacro)\n\
find_dependency(Protobuf)\n\
find_dependency(gRPC CONFIG)\n\
include(\"\${CMAKE_CURRENT_LIST_DIR}/cap_sdk_coreTargets.cmake\")\n")
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/cap_sdk_coreConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/cap_sdk_coreConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/cap_sdk_core
)

# ─── Tests ───────────────────────────────────────────────────────────
if(CAP_SDK_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()
