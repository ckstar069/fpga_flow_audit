set script_dir [file dirname [file normalize [info script]]]
set rtl_dir "${script_dir}/../src/verilog_model/rtl"
set ext_dir "${script_dir}/../external_modules/verilog"

create_project -in_memory -part xc7z020clg400-1

add_files [glob ${rtl_dir}/*.v]
add_files [glob ${ext_dir}/DSP48E1_stub.v]
add_files ${rtl_dir}/nonexistent_file.v

set_property top top_module [current_fileset]
update_compile_order -fileset sources_1