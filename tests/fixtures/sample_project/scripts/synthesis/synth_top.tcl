set script_dir [file dirname [file normalize [info script]]]
set rtl_dir "${script_dir}/../src/verilog_model/rtl"

create_project -in_memory -part xc7z020clg400-1

add_files [glob ${rtl_dir}/top_module.v]
add_files [glob ${rtl_dir}/sub_module_a.v]
add_files [glob ${rtl_dir}/sub_module_b.v]
add_files ${rtl_dir}/atan_lut.hex
set_property USED_IN_SYNTHESIS true [get_files atan_lut.hex]
set_property USED_IN_SIMULATION true [get_files atan_lut.hex]

set_property include_dirs [list $rtl_dir] [current_fileset]
set_property top top_module [current_fileset]
update_compile_order -fileset sources_1