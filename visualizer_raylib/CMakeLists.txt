cmake_minimum_required(VERSION 3.16)
project(intune_visualizer_raylib LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Try to find raylib (user should have it via vcpkg, system, or -DRAYLIB_DIR=...)
find_package(raylib QUIET)

if (NOT raylib_FOUND)
    # Fallback: allow user to point at a local raylib install or source build
    if (DEFINED RAYLIB_DIR)
        set(raylib_DIR "${RAYLIB_DIR}")
        find_package(raylib REQUIRED)
    else()
        message(FATAL_ERROR "raylib not found. Install via vcpkg (vcpkg install raylib), or pass -DRAYLIB_DIR=/path/to/raylib/cmake, or build raylib separately and set the var.")
    endif()
endif()

add_executable(intune_viz
    src/main.cpp
)

target_link_libraries(intune_viz PRIVATE raylib)

# Platform specific libs (raylib examples usually pull these)
if (WIN32)
    target_link_libraries(intune_viz PRIVATE winmm gdi32 opengl32)
endif()

if (APPLE)
    target_link_libraries(intune_viz PRIVATE "-framework IOKit" "-framework Cocoa" "-framework OpenGL")
endif()

# Nice warnings
if (MSVC)
    target_compile_options(intune_viz PRIVATE /W4)
else()
    target_compile_options(intune_viz PRIVATE -Wall -Wextra)
endif()

# Copy any assets next to the binary on build (fonts, etc. if added later)
# file(COPY ${CMAKE_SOURCE_DIR}/assets DESTINATION ${CMAKE_CURRENT_BINARY_DIR})

install(TARGETS intune_viz RUNTIME DESTINATION bin)
