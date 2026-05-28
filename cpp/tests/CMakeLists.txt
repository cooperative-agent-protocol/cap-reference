# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
#
# Unit tests for the C++ SDK. Uses GoogleTest (fetched via FetchContent if
# not found on the system).

find_package(GTest CONFIG QUIET)

if(NOT GTest_FOUND)
    include(FetchContent)
    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.15.2
    )
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

add_executable(cap_sdk_core_tests
    test_validator.cpp
    test_frame_builder.cpp
)

target_link_libraries(cap_sdk_core_tests PRIVATE
    cap_sdk_core
    cap_sdk_construction
    GTest::gtest_main
)

include(GoogleTest)
gtest_discover_tests(cap_sdk_core_tests)
