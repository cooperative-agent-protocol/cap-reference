# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Conan recipe for the CAP C++ SDK (cap_sdk_core + cap_sdk_construction).

Build:
    conan create . --version 0.1.0

Consume (downstream conanfile.txt or conanfile.py):
    [requires]
    cap-sdk-core-cpp/0.1.0
"""

from conan import ConanFile
from conan.tools.cmake import CMake, CMakeToolchain, CMakeDeps, cmake_layout
from conan.tools.files import copy
import os


class CapSdkCoreCppConan(ConanFile):
    name = "cap-sdk-core-cpp"
    version = "0.1.0"
    license = "Apache-2.0"
    url = "https://github.com/cooperative-agent-protocol/cap-reference"
    homepage = "https://cap-protocol.dev"
    description = (
        "CAP (Cooperative Agent Protocol) C++ SDK — Core + Construction "
        "Domain Pack v0. MachineAgentClient, frame builder, validators, "
        "and HAL abstractions."
    )
    topics = ("cap", "cooperative-agent-protocol", "robotics", "grpc",
              "construction", "multi-agent")
    settings = "os", "compiler", "build_type", "arch"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = {"shared": False, "fPIC": True}

    # gRPC + protobuf pinned per ADR-008 / compatibility matrix.
    # gRPC 1.62 (LTS) is the floor; CI also exercises 1.66.
    requires = (
        "grpc/1.65.0",
        "protobuf/5.27.0",
    )

    exports_sources = (
        "CMakeLists.txt",
        "include/*",
        "src/*",
        "tests/*",
        # Generated proto C++ must be present (or CAP_GEN_DIR pointed at it).
    )

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def layout(self):
        cmake_layout(self)

    def generate(self):
        CMakeDeps(self).generate()
        tc = CMakeToolchain(self)
        # Downstream must point CAP_GEN_DIR at buf-generated C++ sources.
        gen_dir = os.environ.get("CAP_GEN_DIR", "")
        if gen_dir:
            tc.cache_variables["CAP_GEN_DIR"] = gen_dir
        tc.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        cmake = CMake(self)
        cmake.install()
        copy(self, "LICENSE", src=self.source_folder,
             dst=os.path.join(self.package_folder, "licenses"))

    def package_info(self):
        self.cpp_info.components["core"].libs = ["cap_sdk_core"]
        self.cpp_info.components["core"].requires = [
            "grpc::grpc++", "protobuf::libprotobuf"]
        # construction is header-only
        self.cpp_info.components["construction"].requires = ["core"]
