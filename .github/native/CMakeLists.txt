cmake_minimum_required(VERSION 3.22)
project(effectcraft_ai_video_worker LANGUAGES C CXX)

if(NOT DEFINED RIFE_SOURCE_DIR OR NOT DEFINED ESRGAN_SOURCE_DIR)
    message(FATAL_ERROR "RIFE_SOURCE_DIR and ESRGAN_SOURCE_DIR are required")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(NCNN_INSTALL_SDK OFF CACHE BOOL "" FORCE)
set(NCNN_VULKAN ON CACHE BOOL "" FORCE)
set(NCNN_VULKAN_ONLINE_SPIRV ON CACHE BOOL "" FORCE)
set(NCNN_BUILD_BENCHMARK OFF CACHE BOOL "" FORCE)
set(NCNN_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(NCNN_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(NCNN_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(NCNN_DISABLE_RTTI ON CACHE BOOL "" FORCE)
set(NCNN_DISABLE_EXCEPTION ON CACHE BOOL "" FORCE)
set(NCNN_PIXEL_ROTATE OFF CACHE BOOL "" FORCE)
set(NCNN_PIXEL_AFFINE OFF CACHE BOOL "" FORCE)
set(NCNN_PIXEL_DRAWING OFF CACHE BOOL "" FORCE)
add_subdirectory("${RIFE_SOURCE_DIR}/src/ncnn" "${CMAKE_BINARY_DIR}/ncnn")

find_package(Threads REQUIRED)
find_program(GLSLANGVALIDATOR_EXECUTABLE NAMES glslangValidator REQUIRED)

# RIFE embeds GLSL source and compiles SPIR-V at runtime through ncnn.
set(RIFE_SHADER_HEADERS)
function(rife_shader source)
    get_filename_component(name ${source} NAME_WE)
    set(output "${CMAKE_CURRENT_BINARY_DIR}/${name}.comp.hex.h")
    add_custom_command(
        OUTPUT "${output}"
        COMMAND ${CMAKE_COMMAND}
            -DSHADER_SRC=${RIFE_SOURCE_DIR}/src/${source}
            -DSHADER_COMP_HEADER=${output}
            -P "${RIFE_SOURCE_DIR}/src/generate_shader_comp_header.cmake"
        DEPENDS "${RIFE_SOURCE_DIR}/src/${source}"
                "${RIFE_SOURCE_DIR}/src/generate_shader_comp_header.cmake"
        VERBATIM)
    set(RIFE_SHADER_HEADERS ${RIFE_SHADER_HEADERS} "${output}" PARENT_SCOPE)
endfunction()

foreach(shader
    rife_preproc.comp rife_postproc.comp
    rife_preproc_tta.comp rife_postproc_tta.comp
    rife_flow_tta_avg.comp rife_v2_flow_tta_avg.comp rife_v4_flow_tta_avg.comp
    rife_flow_tta_temporal_avg.comp rife_v2_flow_tta_temporal_avg.comp rife_v4_flow_tta_temporal_avg.comp
    rife_out_tta_temporal_avg.comp rife_v4_timestep.comp rife_v4_timestep_tta.comp
    warp.comp warp_pack4.comp warp_pack8.comp)
    rife_shader(${shader})
endforeach()

# Real-ESRGAN embeds SPIR-V binary headers. Generate all precision variants included by its source.
set(ESRGAN_SHADER_HEADERS)
function(esrgan_shader source variant)
    get_filename_component(name ${source} NAME_WE)
    set(output "${CMAKE_CURRENT_BINARY_DIR}/${name}${variant}.spv.hex.h")
    set(defines)
    if(variant STREQUAL "_fp16s")
        list(APPEND defines -DNCNN_fp16_storage=1)
    elseif(variant STREQUAL "_int8s")
        list(APPEND defines -DNCNN_fp16_storage=1 -DNCNN_int8_storage=1)
    endif()
    add_custom_command(
        OUTPUT "${output}"
        COMMAND ${GLSLANGVALIDATOR_EXECUTABLE} ${defines} -V -s -x -o "${output}" "${ESRGAN_SOURCE_DIR}/src/${source}"
        DEPENDS "${ESRGAN_SOURCE_DIR}/src/${source}"
        VERBATIM)
    set(ESRGAN_SHADER_HEADERS ${ESRGAN_SHADER_HEADERS} "${output}" PARENT_SCOPE)
endfunction()

foreach(shader realesrgan_preproc.comp realesrgan_postproc.comp realesrgan_preproc_tta.comp realesrgan_postproc_tta.comp)
    esrgan_shader(${shader} "")
    esrgan_shader(${shader} "_fp16s")
    esrgan_shader(${shader} "_int8s")
endforeach()

add_custom_target(effectcraft_ai_video_shaders DEPENDS ${RIFE_SHADER_HEADERS} ${ESRGAN_SHADER_HEADERS})

add_executable(effectcraft-ai-video-worker
    effectcraft_ai_video_worker.cpp
    "${RIFE_SOURCE_DIR}/src/rife.cpp"
    "${RIFE_SOURCE_DIR}/src/warp.cpp"
    "${ESRGAN_SOURCE_DIR}/src/realesrgan.cpp")

add_dependencies(effectcraft-ai-video-worker effectcraft_ai_video_shaders)
target_include_directories(effectcraft-ai-video-worker PRIVATE
    "${CMAKE_CURRENT_BINARY_DIR}"
    "${RIFE_SOURCE_DIR}/src"
    "${ESRGAN_SOURCE_DIR}/src")

target_link_libraries(effectcraft-ai-video-worker PRIVATE ncnn Threads::Threads)
if(TARGET OpenMP::OpenMP_CXX)
    target_link_libraries(effectcraft-ai-video-worker PRIVATE OpenMP::OpenMP_CXX)
endif()

if(ANDROID)
    target_compile_definitions(effectcraft-ai-video-worker PRIVATE NCNN_VULKAN=1)
    set_target_properties(effectcraft-ai-video-worker PROPERTIES
        OUTPUT_NAME "effectcraft-ai-video-worker"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
endif()
