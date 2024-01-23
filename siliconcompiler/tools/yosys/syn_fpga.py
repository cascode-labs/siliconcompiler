from siliconcompiler.tools.yosys.yosys import syn_setup, syn_post_process


######################################################################
# Make Docs
######################################################################
def make_docs(chip):
    chip.set('fpga', 'partname', 'ice40up5k-sg48')
    chip.load_target("fpgaflow_demo")


def setup(chip):
    '''
    Perform FPGA synthesis
    '''

    # Generic synthesis task setup.
    syn_setup(chip)

    # FPGA-specific setup.
    setup_fpga(chip)


def setup_fpga(chip):
    ''' Helper method for configs specific to FPGA steps (both syn and lec).
    '''

    tool = 'yosys'
    step = chip.get('arg', 'step')
    index = chip.get('arg', 'index')
    task = chip._get_task(step, index)
    design = chip.top()

    part_name = chip.get('fpga', 'partname')

    # Require that a lut size is set for FPGA scripts.
    chip.add('tool', tool, 'task', task, 'require',
             ",".join(['fpga', part_name, 'lutsize']),
             step=step, index=index)

    # Verify memory techmapping setup.  If a memory libmap
    # is provided a memory techmap verilog file is needed too
    if chip.valid('fpga', part_name, 'file', 'yosys_memory_libmap') and \
       chip.get('fpga', part_name, 'file', 'yosys_memory_libmap'):

        if chip.valid('fpga', part_name, 'file', 'yosys_memory_techmap') and \
           chip.get('fpga', part_name, 'file', 'yosys_memory_techmap'):
            chip.logger.info("yosys_memory_libmap setup check passed")
        else:
            chip.error("yosys_memory_techmap must be supplied if yosys_memory_libmap is supplied",
                       fatal=True)
            
    chip.add('tool', tool, 'task', task, 'output', design + '_netlist.json', step=step, index=index)
    chip.add('tool', tool, 'task', task, 'output', design + '.blif', step=step, index=index)


##################################################
def post_process(chip):
    syn_post_process(chip)
