cmake_minimum_required(VERSION 3.22)
project(effectcraft_exec_bridge C)

add_library(effectcraft_exec SHARED src/effectcraft_exec_bridge.c)
target_compile_features(effectcraft_exec PRIVATE c_std_11)
target_compile_options(effectcraft_exec PRIVATE -Wall -Wextra -Werror -fvisibility=hidden)
set_target_properties(effectcraft_exec PROPERTIES
    OUTPUT_NAME "effectcraft-exec"
    C_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES)
