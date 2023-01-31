###############################
# Reading SC Schema
###############################

source ./sc_manifest.tcl  > /dev/null

##############################
# Schema Helper functions
###############################

proc sc_get_layer_name { name } {
  if { [ string is integer $name ] } {
    set layer [[ord::get_db_tech] findRoutingLayer $name]
    if { $layer == "NULL" } {
      utl::error FLW 1 "$name is not a valid routing layer."
    }
    return [$layer getName]
  }
  return $name
}

proc has_tie_cell { type } {
    upvar sc_cfg sc_cfg
    upvar sc_mainlib sc_mainlib
    upvar sc_tool sc_tool

    return [dict exists $sc_cfg library $sc_mainlib option {var} openroad_tie${type}_cell] && \
           [dict exists $sc_cfg library $sc_mainlib option {var} openroad_tie${type}_port]
}

proc get_tie_cell { type } {
    upvar sc_cfg sc_cfg
    upvar sc_mainlib sc_mainlib
    upvar sc_tool sc_tool

    set cell [lindex [dict get $sc_cfg library $sc_mainlib option {var} openroad_tie${type}_cell] 0]
    set port [lindex [dict get $sc_cfg library $sc_mainlib option {var} openroad_tie${type}_port] 0]

    return "$cell/$port"
}

##############################
# Schema Adapter
###############################

set sc_tool   openroad
set sc_step   [dict get $sc_cfg arg step]
set sc_index  [dict get $sc_cfg arg index]
set sc_flow   [dict get $sc_cfg option flow]
set sc_task   [dict get $sc_cfg flowgraph $sc_flow $sc_step $sc_index task]

set sc_refdir [dict get $sc_cfg tool $sc_tool task $sc_task refdir $sc_step $sc_index ]

# Design
set sc_design     [sc_top]
set sc_optmode    [dict get $sc_cfg option optmode]
set sc_pdk        [dict get $sc_cfg option pdk]
set sc_stackup    [dict get $sc_cfg option stackup]

# APR Parameters
set sc_targetlibs  [dict get $sc_cfg asic logiclib]
set sc_mainlib     [lindex $sc_targetlibs 0]
set sc_delaymodel  [dict get $sc_cfg asic delaymodel]
set sc_hpinmetal   [lindex [dict get $sc_cfg pdk $sc_pdk {var} $sc_tool pin_layer_horizontal $sc_stackup] 0]
set sc_vpinmetal   [lindex [dict get $sc_cfg pdk $sc_pdk {var} $sc_tool pin_layer_vertical $sc_stackup] 0]
set sc_rc_signal   [lindex [dict get $sc_cfg pdk $sc_pdk {var} $sc_tool rclayer_clock $sc_stackup] 0]
set sc_rc_clk      [lindex [dict get $sc_cfg pdk $sc_pdk {var} $sc_tool rclayer_clock $sc_stackup] 0]
set sc_minmetal    [dict get $sc_cfg pdk $sc_pdk minlayer $sc_stackup]
set sc_maxmetal    [dict get $sc_cfg pdk $sc_pdk maxlayer $sc_stackup]
set sc_aspectratio [dict get $sc_cfg constraint aspectratio]
set sc_density     [dict get $sc_cfg constraint density]
set sc_scenarios   [dict keys [dict get $sc_cfg constraint timing]]

# Library
set sc_libtype      [dict get $sc_cfg library $sc_mainlib asic libarch]
# TODO: handle multiple sites properly
set sc_site         [lindex [dict get $sc_cfg library $sc_mainlib asic site $sc_libtype] 0]
set sc_filler       [dict get $sc_cfg library $sc_mainlib asic cells filler]
set sc_dontuse      [dict get $sc_cfg library $sc_mainlib asic cells dontuse]
set sc_clkbuf       [dict get $sc_cfg library $sc_mainlib asic cells clkbuf]
set sc_filler       [dict get $sc_cfg library $sc_mainlib asic cells filler]
set sc_tap          [dict get $sc_cfg library $sc_mainlib asic cells tap]
set sc_endcap       [dict get $sc_cfg library $sc_mainlib asic cells endcap]
set sc_corners      [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index timing_corners]
set sc_power_corner [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index power_corner] 0]

# PDK Design Rules
set sc_techlef     [dict get $sc_cfg pdk $sc_pdk aprtech openroad $sc_stackup $sc_libtype lef]

if {[dict exists $sc_cfg datasheet $sc_design]} {
  set sc_pins    [dict keys [dict get $sc_cfg datasheet $sc_design pin]]
} else {
  set sc_pins    [list]
}

set sc_threads     [dict get $sc_cfg tool $sc_tool task $sc_task threads $sc_step $sc_index]

set openroad_dont_touch {}
if {[dict exists $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index dont_touch]} {
  set openroad_dont_touch [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index dont_touch]
}

###############################
# Optional
###############################

# MACROS
set sc_macrolibs [dict get $sc_cfg asic macrolib]

###############################
# Read Files
###############################

# Read Liberty
define_corners {*}$sc_corners
foreach lib "$sc_targetlibs $sc_macrolibs" {
  #Liberty
  foreach corner $sc_corners {
    if {[dict exists $sc_cfg library $lib output $corner $sc_delaymodel]} {
      foreach lib_file [dict get $sc_cfg library $lib output $corner $sc_delaymodel] {
        puts "Reading liberty file for ${corner}: ${lib_file}"
        read_liberty -corner $corner $lib_file
      }
    }
  }
}

if {[file exists "inputs/$sc_design.odb"]} {
  # read ODB
  set odb_file "inputs/$sc_design.odb"
  puts "Reading ODB: ${odb_file}"
  read_db $odb_file
} else {
  # Read techlef
  puts "Reading techlef: ${sc_techlef}"
  read_lef $sc_techlef

  # Read Lefs
  foreach lib "$sc_targetlibs $sc_macrolibs" {
    foreach lef_file [dict get $sc_cfg library $lib output $sc_stackup lef] {
      puts "Reading lef: ${lef_file}"
      read_lef $lef_file
    }
  }

  if {$sc_step == "floorplan"} {
    # Read Verilog
    if {[dict exists $sc_cfg input netlist verilog]} {
      foreach netlist [dict get $sc_cfg input netlist verilog] {
        puts "Reading netlist verilog: ${netlist}"
        read_verilog $netlist
      }
    } else {
      puts "Reading netlist verilog: inputs/${sc_design}.vg"
      read_verilog "inputs/${sc_design}.vg"
    }
    link_design $sc_design
  } else {
    # Read DEF
    if {[file exists "inputs/${sc_design}.def"]} {
      # get from previous step
      puts "Reading DEF: inputs/${sc_design}.def"
      read_def "inputs/${sc_design}.def"
    } elseif {[dict exists $sc_cfg input layout def]} {
      # Floorplan initialize handled separately in sc_floorplan.tcl
      set sc_def [lindex [dict get $sc_cfg input layout def] 0]
      puts "Reading DEF: ${sc_def}"
      read_def $sc_def
    }
  }
}

# Read SDC (in order of priority)
# TODO: add logic for reading from ['constraint', ...] once we support MCMM
if {[file exists "inputs/${sc_design}.sdc"]} {
  # get from previous step
  puts "Reading SDC: inputs/${sc_design}.sdc"
  read_sdc "inputs/${sc_design}.sdc"
} elseif {[dict exists $sc_cfg input constraint sdc]} {
  foreach sdc [dict get $sc_cfg input constraint sdc] {
    # read step constraint if exists
    puts "Reading SDC: ${sdc}"
    read_sdc $sdc
  }
} else {
  # fall back on default auto generated constraints file
  puts "Reading SDC: ${sc_refdir}/sc_constraints.sdc"
  utl::warn FLW 1 "Defaulting back to default SDC"
  read_sdc "${sc_refdir}/sc_constraints.sdc"
}

###############################
# Common Setup
###############################

# Sweep parameters
set openroad_ifp_tie_separation [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index ifp_tie_separation] 0]

set openroad_pdn_enable [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index pdn_enable] 0]

set openroad_psm_enable [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index psm_enable] 0]

set openroad_mpl_macro_place_halo [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step  $sc_index macro_place_halo]
set openroad_mpl_macro_place_channel [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index macro_place_channel]

set openroad_gpl_place_density [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index place_density] 0]
set openroad_gpl_padding [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index pad_global_place] 0]
set openroad_gpl_routability_driven [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index gpl_routability_driven] 0]
set openroad_gpl_timing_driven [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index gpl_timing_driven] 0]

set openroad_dpo_enable [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index dpo_enable] 0]
set openroad_dpo_max_displacement [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index dpo_max_displacement] 0]

set openroad_dpl_max_displacement [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index dpl_max_displacement] 0]
set openroad_dpl_padding [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index pad_detail_place] 0]

set openroad_cts_distance_between_buffers [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index cts_distance_between_buffers] 0]
set openroad_cts_cluster_diameter [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index cts_cluster_diameter] 0]
set openroad_cts_cluster_size [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index cts_cluster_size] 0]
set openroad_cts_balance_levels [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index cts_balance_levels] 0]

set openroad_ant_iterations [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index ant_iterations] 0]
set openroad_ant_margin [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index ant_margin] 0]

set openroad_grt_use_pin_access [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_use_pin_access] 0]
set openroad_grt_overflow_iter [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_overflow_iter] 0]
set openroad_grt_macro_extension [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_macro_extension] 0]
set openroad_grt_allow_congestion [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_allow_congestion] 0]
set openroad_grt_allow_overflow [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_allow_overflow] 0]
set openroad_grt_signal_min_layer [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_signal_min_layer] 0]
set openroad_grt_signal_max_layer [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_signal_max_layer] 0]
set openroad_grt_clock_min_layer [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_clock_min_layer] 0]
set openroad_grt_clock_max_layer [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index grt_clock_max_layer] 0]

set openroad_drt_disable_via_gen [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index drt_disable_via_gen] 0]
set openroad_drt_process_node [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index drt_process_node] 0]
set openroad_drt_via_in_pin_bottom_layer [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index drt_via_in_pin_bottom_layer] 0]
set openroad_drt_via_in_pin_top_layer [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index drt_via_in_pin_top_layer] 0]
set openroad_drt_repair_pdn_vias [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index drt_repair_pdn_vias] 0]
set openroad_drt_via_repair_post_route [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index drt_via_repair_post_route] 0]
set openroad_drt_default_vias []
if {[dict exists $sc_cfg tool $sc_tool task $sc_task var $sc_step $sc_index drt_default_via]} {
  foreach via [dict exists $sc_cfg tool $sc_tool task $sc_task var $sc_step $sc_index drt_default_via] {
    lappend openroad_drt_default_vias $via
  }
}
set openroad_drt_unifirectional_layers []
if {[dict exists $sc_cfg tool $sc_tool task $sc_task var $sc_step $sc_index drt_unidirectional_layer]} {
  foreach layer [dict exists $sc_cfg tool $sc_tool task $sc_task var $sc_step $sc_index drt_unidirectional_layer] {
    lappend openroad_drt_unifirectional_layers [sc_get_layer_name $layer]
  }
}

set openroad_rsz_setup_slack_margin [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index rsz_setup_slack_margin] 0]
set openroad_rsz_hold_slack_margin [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index rsz_hold_slack_margin] 0]
set openroad_rsz_slew_margin [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index rsz_slew_margin] 0]
set openroad_rsz_cap_margin [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index rsz_cap_margin] 0]
set openroad_rsz_buffer_inputs [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index rsz_buffer_inputs] 0]
set openroad_rsz_buffer_outputs [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index rsz_buffer_outputs] 0]

set openroad_sta_early_timing_derate [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index sta_early_timing_derate] 0]
set openroad_sta_late_timing_derate [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index sta_late_timing_derate] 0]

set openroad_fin_add_fill [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index fin_add_fill] 0]

# PDK agnostic design rule translation
set sc_minmetal [sc_get_layer_name $sc_minmetal]
set sc_maxmetal [sc_get_layer_name $sc_maxmetal]
set sc_hpinmetal [sc_get_layer_name $sc_hpinmetal]
set sc_vpinmetal [sc_get_layer_name $sc_vpinmetal]
set sc_rc_clk [sc_get_layer_name $sc_rc_clk]
set sc_rc_signal [sc_get_layer_name $sc_rc_signal]
set openroad_grt_signal_min_layer [sc_get_layer_name $openroad_grt_signal_min_layer]
set openroad_grt_signal_max_layer [sc_get_layer_name $openroad_grt_signal_max_layer]
set openroad_grt_clock_min_layer [sc_get_layer_name $openroad_grt_clock_min_layer]
set openroad_grt_clock_max_layer [sc_get_layer_name $openroad_grt_clock_max_layer]
set openroad_drt_via_in_pin_bottom_layer [sc_get_layer_name $openroad_drt_via_in_pin_bottom_layer]
set openroad_drt_via_in_pin_top_layer [sc_get_layer_name $openroad_drt_via_in_pin_top_layer]
set openroad_drt_repair_pdn_vias [sc_get_layer_name $openroad_drt_repair_pdn_vias]

# Setup timing derating
if {$openroad_sta_early_timing_derate != 0.0} {
  set_timing_derate -early $openroad_sta_early_timing_derate
}
if {$openroad_sta_late_timing_derate != 0.0} {
  set_timing_derate -late $openroad_sta_late_timing_derate
}

# Check timing setup
# This produces a segfault on sky130
#check_setup

if { [llength [all_clocks]] == 0} {
  utl::warn FLW 1 "No clocks defined."
}

set_dont_use $sc_dontuse

set sc_parasitics [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index parasitics] 0]
source $sc_parasitics
set_wire_rc -clock  -layer $sc_rc_clk
set_wire_rc -signal -layer $sc_rc_signal

set_thread_count $sc_threads

if {$sc_step != "floorplan"} {
  ## Setup global routing

  # Adjust routing track density
  foreach layer [[ord::get_db_tech] getLayers] {
    if { [ $layer getRoutingLevel ] == 0 } {
      continue
    }

    set layername [$layer getName]
    set adjustment [lindex [dict get $sc_cfg pdk $sc_pdk {var} $sc_tool "${layername}_adjustment" $sc_stackup] 0]
    set_global_routing_layer_adjustment $layername $adjustment
  }

  set_macro_extension $openroad_grt_macro_extension
  set_routing_layers -signal "${openroad_grt_signal_min_layer}-${openroad_grt_signal_max_layer}"
  set_routing_layers -clock "${openroad_grt_clock_min_layer}-${openroad_grt_clock_max_layer}"
}

if { $sc_step == "show" || $sc_step == "screenshot" } {
  if { $sc_step == "screenshot" } {
    source "$sc_refdir/sc_screenshot.tcl"
  }

  set show_exit [lindex [dict get $sc_cfg tool $sc_tool task $sc_task {var} $sc_step $sc_index show_exit] 0]
  if { $show_exit == "true" } {
    exit
  }
} else {
  ###############################
  # Source Step Script
  ###############################

  report_units_metric

  utl::set_metrics_stage "sc__prestep__{}"
  if {[dict exists $sc_cfg tool $sc_tool task $sc_task prescript $sc_step $sc_index]} {
    foreach sc_pre_script [dict get $sc_cfg tool $sc_tool task $sc_task prescript $sc_step $sc_index] {
      puts "Sourcing pre script: ${sc_pre_script}"
      source -echo $sc_pre_script
    }
  }
  utl::pop_metrics_stage

  utl::set_metrics_stage "sc__step__{}"
  if { [llength $openroad_dont_touch] > 0} {
    # set don't touch list
    set_dont_touch $openroad_dont_touch
  }

  source -echo "$sc_refdir/sc_$sc_step.tcl"

  if { [llength $openroad_dont_touch] > 0} {
    # unset for next step
    unset_dont_touch $openroad_dont_touch
  }
  utl::pop_metrics_stage

  utl::set_metrics_stage "sc__poststep__{}"
  if {[dict exists $sc_cfg tool $sc_tool task $sc_task postscript $sc_step $sc_index]} {
    foreach sc_post_script [dict get $sc_cfg tool $sc_tool task $sc_task postscript $sc_step $sc_index] {
      puts "Sourcing post script: ${sc_post_script}"
      source -echo $sc_post_script
    }
  }
  utl::pop_metrics_stage

  ###############################
  # Write Design Data
  ###############################

  utl::set_metrics_stage "sc__write__{}"
  source "$sc_refdir/sc_write.tcl"
  utl::pop_metrics_stage

  ###############################
  # Reporting
  ###############################

  utl::set_metrics_stage "sc__metric__{}"
  source "$sc_refdir/sc_metrics.tcl"
  utl::pop_metrics_stage
}
