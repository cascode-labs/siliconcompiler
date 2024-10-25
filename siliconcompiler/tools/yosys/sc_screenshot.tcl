###############################
# Reading SC Schema
###############################

source ./sc_manifest.tcl

yosys echo on

###############################
# Schema Adapter
###############################

set sc_tool yosys
set sc_step [sc_cfg_get arg step]
set sc_index [sc_cfg_get arg index]
set sc_flow [sc_cfg_get option flow]
set sc_task [sc_cfg_get flowgraph $sc_flow $sc_step $sc_index task]
set sc_refdir [sc_cfg_tool_task_get refdir]

####################
# DESIGNER's CHOICE
####################

set sc_design [sc_top]
set sc_flow [sc_cfg_get option flow]
set sc_optmode [sc_cfg_get option optmode]
set sc_pdk [sc_cfg_get option pdk]

########################################################
# Design Inputs
########################################################

if { [file exists "inputs/$sc_design.v"] } {
    set input_verilog "inputs/$sc_design.v"
    yosys read_verilog -noblackbox -sv $input_verilog
    set file_type "v"
} elseif { [file exists "inputs/$sc_design.vg"] } {
    set input_verilog "inputs/$sc_design.vg"
    yosys read_verilog -noblackbox -sv $input_verilog
    set file_type "vg"
} elseif { [sc_cfg_tool_task_exists var show_filepath] } {
    yosys read_verilog -noblackbox -sv [sc_cfg_tool_task_get var show_filepath]
    set file_type [lindex [sc_cfg_tool_task_get var show_filetype] 0]
}

########################################################
# Override top level parameters
########################################################

yosys chparam -list $sc_design
if { [sc_cfg_exists option param] } {
    yosys echo off
    set module_params [yosys tee -q -s result.string chparam -list $sc_design]
    yosys echo on

    dict for {key value} [sc_cfg_get option param] {
        if { ![string is integer $value] } {
            set value [concat \"$value\"]
        }

        if { [string first $key $module_params] != -1 } {
            yosys chparam -set $key $value $sc_design
        } else {
            puts "Warning: $key is not a defined parameter in $sc_design"
        }
    }
}

########################################################
# Read Libraries
########################################################

set sc_logiclibs [sc_get_asic_libraries logic]
set sc_macrolibs [sc_get_asic_libraries macro]

set sc_libraries [sc_cfg_tool_task_get {file} synthesis_libraries]
if { [sc_cfg_tool_task_exists {file} synthesis_libraries_macros] } {
    set sc_macro_libraries \
        [sc_cfg_tool_task_get {file} synthesis_libraries_macros]
} else {
    set sc_macro_libraries []
}

set sc_blackboxes []
foreach lib $sc_macrolibs {
    if { [sc_cfg_exists library $lib output blackbox verilog] } {
        foreach lib_f [sc_cfg_get library $lib output blackbox verilog] {
            lappend sc_blackboxes $lib_f
        }
    }
}

foreach lib_file "$sc_libraries $sc_macro_libraries" {
    yosys read_liberty -lib $lib_file
}
foreach bb_file $sc_blackboxes {
    yosys log "Reading blackbox model file: $bb_file"
    yosys read_verilog -sv $bb_file
}

########################################################
# Screenshot
########################################################

yosys hierarchy -top $sc_design

if { $file_type == "v" } {
    yosys proc
}

yosys show \
    -nobg \
    -format png \
    -width \
    -signed \
    -stretch \
    -prefix outputs/${sc_design} \
    $sc_design
